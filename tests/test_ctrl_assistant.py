import base64
import importlib.util
import json
from pathlib import Path
import sys
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
spec = importlib.util.spec_from_file_location('assistant_server_for_ctrl', ROOT / 'scripts/assistant_server.py')
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)
from ctrl_assistant import CATALOG, parse_route, route_prompt
from ctrl_multi import ConversationChanged, CtrlProgress, MultiCtrlJobs, selected_models


class FakeProvider:
    def __init__(self, name):
        self.name = name
        self.calls = []
    def generate_with_progress(self, prompt, path, progress):
        self.calls.append((prompt, path is not None))
        if path:
            assert path.is_file()
            progress('正在 OCR')
            return {'status': 'completed', 'text': '下列哪项是国家标准？A. GB/T 1.1 B. 示例',
                    'cleanup_receipt': self.name+'-receipt'}
        progress('正在生成')
        return {'status': 'completed', 'text': json.dumps({'keywords': ['GB/T 1.1'],
            'sites': [{'name': '国家标准全文公开系统', 'url': 'https://openstd.samr.gov.cn/bzgk/std/',
                       'query': 'GB/T 1.1', 'why': '标准'}]}, ensure_ascii=False),
                'cleanup_receipt': self.name+'-receipt'}
    def close_saved_response(self, receipt):
        return {'status': 'closed'}


class CtrlTests(unittest.TestCase):
    def test_catalog_route_marks_external_and_preserves_known(self):
        self.assertGreater(len(CATALOG), 100)
        result = parse_route(json.dumps({'keywords': ['GB/T 1.1'], 'sites': [
            {'name': '国家标准全文公开系统', 'url': 'https://wrong.example/', 'query': 'GB/T 1.1'},
            {'name': '库外来源', 'url': 'https://example.org/search', 'query': '标准'},
            {'name': '恶意链接', 'url': 'javascript:alert(1)'}]}, ensure_ascii=False))
        self.assertEqual(result['sites'][0]['url'], 'https://openstd.samr.gov.cn/bzgk/std/')
        self.assertFalse(result['sites'][0]['unlisted'])
        self.assertTrue(result['sites'][1]['unlisted'])
        self.assertEqual(len(result['sites']), 2)
        self.assertLess(len(route_prompt('国家标准 GB/T 1.1')), 4000)
        wrapped = 'json\n复制\n下载\n' + json.dumps({'keywords': ['标准'], 'sites': []}, ensure_ascii=False)
        self.assertEqual(parse_route(wrapped)['keywords'], ['标准'])
        gemini = 'JSON\n{"keywords":["残缺"],"sites":[{"name":"截断"\n```json\n'+json.dumps({
            'keywords': ['国家标准'], 'sites': [{'name': '国家标准全文公开系统',
            'url': '[标准](https://openstd.samr.gov.cn/bzgk/std/)', 'query': 'GB/T 1.1'}]}, ensure_ascii=False)
        self.assertEqual(parse_route(gemini)['sites'][0]['url'], 'https://openstd.samr.gov.cn/bzgk/std/')

    def test_model_choice_defaults_to_deepseek_and_allows_dual(self):
        self.assertEqual(selected_models({}), ['deepseek'])
        self.assertEqual(selected_models({'models': ['deepseek', 'gemini']}), ['deepseek', 'gemini'])
        for invalid in ([], ['deepseek', 'deepseek'], ['other']):
            with self.assertRaises(ValueError):
                selected_models({'models': invalid})

    def test_one_question_per_model_and_idle_model_takes_next_question(self):
        class BlockingProvider(FakeProvider):
            def __init__(self):
                super().__init__('deepseek')
                self.entered = threading.Event()
                self.release = threading.Event()
            def generate_with_progress(self, prompt, path, progress):
                if not self.calls:
                    self.entered.set()
                    self.release.wait(3)
                return super().generate_with_progress(prompt, path, progress)
        deepseek = BlockingProvider()
        gemini = FakeProvider('gemini')
        jobs = server.Jobs({'deepseek': deepseek, 'gemini': gemini})
        ctrl = MultiCtrlJobs(jobs, server.read_input)
        first = ctrl.start({'text': '第一题', 'models': ['deepseek', 'gemini']})
        self.assertTrue(deepseek.entered.wait(1))
        second = ctrl.start({'text': '第二题', 'models': ['deepseek', 'gemini']})
        ctrl.model_pools['gemini'].submit(lambda: None).result(timeout=3)
        self.assertEqual(len(gemini.calls), 1)
        self.assertEqual(len(deepseek.calls), 0)
        self.assertEqual(set(jobs.get(second['id'])['results']), {'gemini'})
        self.assertEqual(len(ctrl.list_tasks()), 2)
        deepseek.release.set()
        ctrl.wait_idle()
        self.assertEqual(jobs.get(first['id'])['state'], 'completed')
        self.assertEqual(jobs.get(second['id'])['state'], 'completed')
        self.assertIn('第一题', deepseek.calls[0][0])
        self.assertIn('第二题', gemini.calls[0][0])
        self.assertEqual(len(deepseek.calls), 1)
        ctrl.shutdown()
        jobs.pool.shutdown(wait=True)

    def test_fast_answer_uses_same_route_call(self):
        class AnswerProvider(FakeProvider):
            def generate_with_progress(self, prompt, path, progress):
                self.calls.append((prompt, path is not None))
                return {'status':'completed','text':json.dumps({'keywords':['标准'], 'sites':[],
                    'answer':'A；具体版本待核验'},ensure_ascii=False)}
        provider = AnswerProvider('deepseek')
        jobs = server.Jobs({'deepseek':provider,'gemini':FakeProvider('gemini')})
        ctrl = MultiCtrlJobs(jobs,server.read_input)
        started = ctrl.start({'text':'国家标准在哪查？','models':['deepseek'],'fast_answer':True})
        ctrl.wait_idle()
        result = jobs.get(started['id'])['results']['deepseek']
        self.assertEqual(len(provider.calls),1)
        self.assertIn('待核验',result['answer'])
        self.assertIn('标准',result['route']['keywords'])
        self.assertNotIn('answer',result['route'])
        ctrl.shutdown(); jobs.pool.shutdown(wait=True)

    def test_repeated_intake_id_does_not_submit_twice_and_archive_removes_task(self):
        provider = FakeProvider('deepseek')
        jobs = server.Jobs({'deepseek':provider,'gemini':FakeProvider('gemini')})
        ctrl = MultiCtrlJobs(jobs,server.read_input)
        request = {'text':'国家标准在哪里查？','models':['deepseek'],'client_id':'test-intake-1'}
        first = ctrl.start(request)
        second = ctrl.start(request)
        self.assertEqual(first,second)
        ctrl.wait_idle()
        self.assertEqual(len(provider.calls),1)
        self.assertEqual(len(ctrl.list_tasks()),1)
        ctrl.archive({'session':first['session']})
        self.assertEqual(ctrl.list_tasks(),[])
        ctrl.shutdown(); jobs.pool.shutdown(wait=True)

    def test_session_keeps_tracking_older_sibling_job_after_followup_finishes(self):
        jobs = server.Jobs({'deepseek':FakeProvider('deepseek'),'gemini':FakeProvider('gemini')})
        ctrl = MultiCtrlJobs(jobs,server.read_input)
        ctrl.sessions['s'] = {'original':'题目','input_text':'题目','had_image':False,
            'models':{name:{'original':'题目','route':None,'answer':''} for name in ('deepseek','gemini')}}
        jobs.items['route'] = {'id':'route','session':'s','state':'running','started_at':1,
            'results':{'deepseek':{'state':'completed'},'gemini':{'state':'running'}}}
        jobs.items['answer'] = {'id':'answer','session':'s','state':'completed','started_at':2,
            'results':{'deepseek':{'state':'completed','answer':'A'}}}
        state = ctrl.get_session('s')
        self.assertEqual(state['state'],'running')
        self.assertEqual(state['activity']['gemini']['state'],'running')
        self.assertEqual(state['activity']['deepseek']['answer'],'A')
        with self.assertRaises(ValueError):
            ctrl.archive({'session':'s'})
        ctrl.shutdown(); jobs.pool.shutdown(wait=True)

    def test_external_health_site_gets_provincial_and_national_catalog_alternatives(self):
        raw = json.dumps({'keywords': ['卫生健康政策'], 'sites': [
            {'name': '某市卫生健康局', 'url': 'https://health.example.org/',
             'query': '卫生健康政策'}]}, ensure_ascii=False)
        result = parse_route(raw, '福建省卫生健康政策应该到哪里核对？')
        self.assertTrue(result['sites'][0]['unlisted'])
        known = [site for site in result['sites'] if not site['unlisted']]
        self.assertGreaterEqual(len(known), 2)
        self.assertIn('https://wjw.fujian.gov.cn/', [site['url'] for site in known])
        self.assertIn('https://www.nhc.gov.cn/', [site['url'] for site in known])

    def test_screenshot_and_answer_stay_with_one_assignee(self):
        providers = {name: FakeProvider(name) for name in ('gemini', 'deepseek')}
        jobs = server.Jobs(providers)
        ctrl = MultiCtrlJobs(jobs, server.read_input)
        followups = []
        def continue_message(name, model, prompt, job_id):
            followups.append((name, prompt, model['receipt']))
            if 'JSON' in prompt:
                return providers[name].generate_with_progress(prompt, None, lambda stage: None)
            return {'status': 'completed', 'text': name+' 答案：A；以标准网页为准。'}
        ctrl._continue = continue_message
        image = 'data:image/png;base64,'+base64.b64encode(b'\x89PNG\r\n\x1a\nfixture').decode()
        job = ctrl.start({'image': image, 'models': ['deepseek', 'gemini']})
        ctrl.wait_idle(); jobs.pool.shutdown(wait=True)
        result = jobs.get(job['id'])
        self.assertEqual(result['state'], 'completed')
        self.assertEqual(set(result['results']), {'deepseek'})
        self.assertTrue(all(value['original'].startswith('下列哪项') for value in result['results'].values()))
        self.assertEqual(len(followups), 1)
        self.assertTrue(all(value[2].endswith('-receipt') for value in followups))
        jobs.pool = __import__('concurrent.futures').futures.ThreadPoolExecutor(max_workers=1)
        answer = ctrl.answer({'session': job['session'], 'models': ['gemini']})
        ctrl.wait_idle(); jobs.pool.shutdown(wait=True)
        self.assertTrue(jobs.get(answer['id'])['results']['deepseek']['answer'].startswith('deepseek'))
        self.assertEqual(len(providers['gemini'].calls), 0)
        ctrl.shutdown()

    def test_retry_recovers_existing_reply_without_resending(self):
        provider = FakeProvider('deepseek')
        jobs = server.Jobs({'gemini': FakeProvider('gemini'), 'deepseek': provider})
        ctrl = MultiCtrlJobs(jobs, server.read_input)
        started = ctrl.start({'text': '国家标准在哪里查？', 'models': ['deepseek']})
        ctrl.wait_idle(); jobs.pool.shutdown(wait=True)
        original_calls = len(provider.calls)
        jobs.items[started['id']]['results']['deepseek']['state'] = 'failed'
        jobs.items[started['id']]['state'] = 'failed'
        ctrl.sessions[started['session']]['models']['deepseek']['route'] = None
        ctrl._read_saved_reply = lambda name, model: json.dumps({'keywords': ['国家标准'],
            'sites': [{'name': '国家标准全文公开系统', 'url': 'https://openstd.samr.gov.cn/bzgk/std/'}]}, ensure_ascii=False)
        jobs.pool = __import__('concurrent.futures').futures.ThreadPoolExecutor(max_workers=1)
        retried = ctrl.retry({'job': started['id']})
        ctrl.wait_idle(); jobs.pool.shutdown(wait=True)
        self.assertEqual(jobs.get(retried['id'])['state'], 'completed')
        self.assertEqual(len(provider.calls), original_calls)

    def test_retry_missing_conversation_resends_only_failed_model(self):
        providers = {name: FakeProvider(name) for name in ('gemini', 'deepseek')}
        jobs = server.Jobs(providers)
        ctrl = MultiCtrlJobs(jobs, server.read_input)
        started = ctrl.start({'text': '国家标准在哪里查？', 'models': ['deepseek', 'gemini']})
        ctrl.wait_idle(); jobs.pool.shutdown(wait=True)
        jobs.items[started['id']]['results']['deepseek']['state'] = 'failed'
        ctrl._read_saved_reply = lambda name, model: None
        jobs.pool = __import__('concurrent.futures').futures.ThreadPoolExecutor(max_workers=1)
        retried = ctrl.retry({'job': started['id']})
        ctrl.wait_idle(); jobs.pool.shutdown(wait=True)
        self.assertEqual(retried['retried'], ['deepseek'])
        self.assertEqual(jobs.get(retried['id'])['state'], 'completed')
        self.assertEqual(len(providers['deepseek'].calls), 2)
        self.assertEqual(len(providers['gemini'].calls), 0)

    def test_retry_running_job_reattaches_without_second_submission(self):
        jobs = server.Jobs({'gemini': FakeProvider('gemini'), 'deepseek': FakeProvider('deepseek')})
        ctrl = MultiCtrlJobs(jobs, server.read_input)
        ctrl.sessions['s'] = {'models': {}, 'original': '题目'}
        jobs.items['j'] = {'id': 'j', 'kind': 'ctrl-start', 'session': 's', 'state': 'running',
                           'results': {'deepseek': {'state': 'running'}}}
        self.assertEqual(ctrl.retry({'job': 'j'}), {'id': 'j', 'session': 's', 'resumed': True})
        ctrl.wait_idle(); jobs.pool.shutdown(wait=True)

    def test_retry_recovers_ocr_from_original_tab_without_image_reattachment(self):
        provider = FakeProvider('deepseek')
        jobs = server.Jobs({'gemini': FakeProvider('gemini'), 'deepseek': provider})
        ctrl = MultiCtrlJobs(jobs, server.read_input)
        ctrl.sessions['s'] = {'models': {'deepseek': {'original': '', 'route': None, 'answer': '',
            'receipt': 'receipt', 'phase': 'ocr'}}, 'original': '', 'input_text': '', 'had_image': True}
        jobs.items['j'] = {'id': 'j', 'kind': 'ctrl-start', 'session': 's', 'state': 'failed',
                           'results': {'deepseek': {'state': 'failed'}}}
        ctrl._read_saved_reply = lambda name, model: 'OCR 原题：国家标准在哪里查？'
        ctrl._continue = lambda name, model, prompt, job: {'status': 'completed', 'text': json.dumps(
            {'keywords': ['国家标准'], 'sites': []}, ensure_ascii=False)}
        retried = ctrl.retry({'job': 'j'})
        ctrl.wait_idle(); jobs.pool.shutdown(wait=True)
        self.assertEqual(jobs.get(retried['id'])['state'], 'completed')
        self.assertEqual(len(provider.calls), 0)

    def test_conversation_locator_ignores_changed_tab_and_finds_original_chat(self):
        from types import SimpleNamespace
        ctrl = MultiCtrlJobs(server.Jobs({'gemini': FakeProvider('gemini'),
            'deepseek': FakeProvider('deepseek')}), server.read_input)
        old_url = 'https://chat.deepseek.com/a/chat/s/original-123'
        changed = SimpleNamespace(url='https://chat.deepseek.com/a/chat/s/another-456', target='saved-tab')
        found = SimpleNamespace(url=old_url, target='other-tab')
        browser = SimpleNamespace(contexts=[SimpleNamespace(pages=[changed, found])])
        ctrl._find_page = lambda browser, target: next((page for page in browser.contexts[0].pages
            if page.target == target), None)
        ctrl._page_target_id = lambda page: page.target
        owned = {'target_id': 'saved-tab', 'url': old_url}
        self.assertIs(ctrl._locate_conversation(browser, 'deepseek', owned), found)
        self.assertEqual(owned['target_id'], 'saved-tab')  # Never close a user-owned tab later.
        self.assertIsNone(ctrl._conversation_key('deepseek', 'https://chat.deepseek.com/'))
        self.assertIsNone(ctrl._conversation_key('deepseek', 'https://evil.example/a/chat/s/original-123'))
        self.assertIsNone(ctrl._conversation_key('gemini', 'https://gemini.google.com/app'))
        self.assertEqual(ctrl._conversation_key('gemini', 'https://gemini.google.com/app/chat-123'),
                         ('gemini.google.com', '/app/chat-123'))
        ctrl.wait_idle(); ctrl.jobs.pool.shutdown(wait=True)

    def test_conversation_locator_restores_saved_url_in_original_tab(self):
        from types import SimpleNamespace
        provider = FakeProvider('deepseek')
        provider._transport = SimpleNamespace(_page_state=lambda page: {'status': 'ready'})
        ctrl = MultiCtrlJobs(server.Jobs({'gemini': FakeProvider('gemini'),
            'deepseek': provider}), server.read_input)
        old_url = 'https://chat.deepseek.com/a/chat/s/original-123'
        changed = SimpleNamespace(url='https://chat.deepseek.com/a/chat/s/another-456', target='saved-tab')
        changed.goto = lambda url, **kwargs: setattr(changed, 'url', url)
        context = SimpleNamespace(pages=[changed])
        browser = SimpleNamespace(contexts=[context])
        ctrl._find_page = lambda browser, target: changed
        ctrl._page_target_id = lambda page: page.target
        owned = {'target_id': 'saved-tab', 'url': old_url}
        self.assertIs(ctrl._locate_conversation(browser, 'deepseek', owned), changed)
        self.assertEqual(owned['target_id'], 'saved-tab')
        self.assertEqual(changed.url, old_url)
        ctrl.wait_idle(); ctrl.jobs.pool.shutdown(wait=True)

    def test_bound_page_rejects_other_conversation_reply(self):
        from types import SimpleNamespace
        ctrl = MultiCtrlJobs(server.Jobs({'gemini': FakeProvider('gemini'),
            'deepseek': FakeProvider('deepseek')}), server.read_input)
        page = SimpleNamespace(url='https://chat.deepseek.com/a/chat/s/wrong-456')
        owned = {'target_id': 'same-tab', 'url': 'https://chat.deepseek.com/a/chat/s/wrong-456',
                 'bound_url': 'https://chat.deepseek.com/a/chat/s/correct-123'}
        with self.assertRaises(ConversationChanged):
            ctrl._assert_bound_conversation('deepseek', page, owned)
        ctrl.wait_idle(); ctrl.jobs.pool.shutdown(wait=True)

    def test_initial_reply_guard_requires_matching_submitted_message(self):
        from types import SimpleNamespace
        provider = FakeProvider('deepseek')
        transport = SimpleNamespace(_editor=lambda page: SimpleNamespace(evaluate=lambda script: ''),
                                    _last_request_receipt='receipt', _owned_targets={'receipt': {}})
        provider._transport = transport
        jobs = server.Jobs({'gemini': FakeProvider('gemini'), 'deepseek': provider})
        ctrl = MultiCtrlJobs(jobs, server.read_input)
        ctrl.jobs.items['j'] = {'results': {'deepseek': {}}}
        model = {}
        guard = CtrlProgress(ctrl, 'j', 'deepseek', model)
        page = SimpleNamespace(url='https://chat.deepseek.com/', wait_for_timeout=lambda ms: None,
                               evaluate=lambda script, marker: marker == guard.marker)
        guard.bind_page(page)
        guard.before_send(page)
        page.url = 'https://chat.deepseek.com/a/chat/s/original-123'
        guard.after_send(page)
        self.assertEqual(model['conversation_url'], page.url)
        page.url = 'https://chat.deepseek.com/a/chat/s/another-456'
        with self.assertRaises(ConversationChanged):
            guard.check(page)
        ctrl.wait_idle(); jobs.pool.shutdown(wait=True)

    def test_ocr_and_direct_answer_never_accept_switched_chat_reply(self):
        from types import SimpleNamespace
        class SwitchedProvider(FakeProvider):
            def __init__(inner):
                super().__init__('deepseek')
                inner._transport = SimpleNamespace(_last_request_receipt=None, _owned_targets={},
                    _editor=lambda page: SimpleNamespace(evaluate=lambda script: ''))
            def generate_with_progress(inner, prompt, path, progress):
                receipt = 'owned-tab'
                inner._transport._last_request_receipt = receipt
                inner._transport._owned_targets[receipt] = {'target_id': 'tab', 'url': 'https://chat.deepseek.com/'}
                page = SimpleNamespace(url='https://chat.deepseek.com/', wait_for_timeout=lambda ms: None,
                                       evaluate=lambda script, marker: marker in prompt)
                progress.bind_page(page)
                progress.before_send(page)
                page.url = 'https://chat.deepseek.com/a/chat/s/our-chat'
                progress.after_send(page)
                page.url = 'https://chat.deepseek.com/a/chat/s/other-chat'
                return {'status': 'completed', 'text': '错误对话的答案',
                        'conversation_url': page.url, 'cleanup_receipt': receipt}
        provider = SwitchedProvider()
        jobs = server.Jobs({'gemini': FakeProvider('gemini'), 'deepseek': provider})
        ctrl = MultiCtrlJobs(jobs, server.read_input)
        image = 'data:image/png;base64,'+base64.b64encode(b'\x89PNG\r\n\x1a\nfixture').decode()
        started = ctrl.start({'image': image, 'models': ['deepseek']})
        ctrl.wait_idle(); jobs.pool.shutdown(wait=True)
        result = jobs.get(started['id'])['results']['deepseek']
        self.assertEqual(result['state'], 'failed')
        self.assertFalse(result.get('original'))
        self.assertIn('另一段', result['error'])
        ctrl.sessions[started['session']]['original'] = '我们的题目'
        ctrl.sessions[started['session']]['models']['deepseek']['receipt'] = None
        jobs.pool = __import__('concurrent.futures').futures.ThreadPoolExecutor(max_workers=1)
        answered = ctrl.answer({'session': started['session'], 'models': ['deepseek']})
        ctrl.wait_idle(); jobs.pool.shutdown(wait=True)
        answer = jobs.get(answered['id'])['results']['deepseek']
        self.assertEqual(answer['state'], 'failed')
        self.assertNotIn('answer', answer)


if __name__ == '__main__':
    unittest.main()


