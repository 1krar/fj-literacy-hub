import base64
import importlib.util
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
spec = importlib.util.spec_from_file_location('assistant_server_for_ctrl', ROOT / 'scripts/assistant_server.py')
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)
from ctrl_assistant import CATALOG, parse_route, route_prompt
from ctrl_multi import MultiCtrlJobs, selected_models


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

    def test_dual_screenshot_ocr_then_route_and_independent_answer(self):
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
        jobs.pool.shutdown(wait=True)
        result = jobs.get(job['id'])
        self.assertEqual(result['state'], 'completed')
        self.assertEqual(set(result['results']), {'deepseek', 'gemini'})
        self.assertTrue(all(value['original'].startswith('下列哪项') for value in result['results'].values()))
        self.assertEqual(len(followups), 2)
        self.assertTrue(all(value[2].endswith('-receipt') for value in followups))
        jobs.pool = __import__('concurrent.futures').futures.ThreadPoolExecutor(max_workers=1)
        answer = ctrl.answer({'session': job['session'], 'models': ['gemini']})
        jobs.pool.shutdown(wait=True)
        self.assertEqual(jobs.get(answer['id'])['results']['gemini']['answer'][:6], 'gemini')

    def test_retry_recovers_existing_reply_without_resending(self):
        provider = FakeProvider('deepseek')
        jobs = server.Jobs({'gemini': FakeProvider('gemini'), 'deepseek': provider})
        ctrl = MultiCtrlJobs(jobs, server.read_input)
        started = ctrl.start({'text': '国家标准在哪里查？', 'models': ['deepseek']})
        jobs.pool.shutdown(wait=True)
        original_calls = len(provider.calls)
        jobs.items[started['id']]['results']['deepseek']['state'] = 'failed'
        jobs.items[started['id']]['state'] = 'failed'
        ctrl.sessions[started['session']]['models']['deepseek']['route'] = None
        ctrl._read_saved_reply = lambda name, model: json.dumps({'keywords': ['国家标准'],
            'sites': [{'name': '国家标准全文公开系统', 'url': 'https://openstd.samr.gov.cn/bzgk/std/'}]}, ensure_ascii=False)
        jobs.pool = __import__('concurrent.futures').futures.ThreadPoolExecutor(max_workers=1)
        retried = ctrl.retry({'job': started['id']})
        jobs.pool.shutdown(wait=True)
        self.assertEqual(jobs.get(retried['id'])['state'], 'completed')
        self.assertEqual(len(provider.calls), original_calls)

    def test_retry_missing_conversation_resends_only_failed_model(self):
        providers = {name: FakeProvider(name) for name in ('gemini', 'deepseek')}
        jobs = server.Jobs(providers)
        ctrl = MultiCtrlJobs(jobs, server.read_input)
        started = ctrl.start({'text': '国家标准在哪里查？', 'models': ['deepseek', 'gemini']})
        jobs.pool.shutdown(wait=True)
        jobs.items[started['id']]['results']['deepseek']['state'] = 'failed'
        ctrl._read_saved_reply = lambda name, model: None
        jobs.pool = __import__('concurrent.futures').futures.ThreadPoolExecutor(max_workers=1)
        retried = ctrl.retry({'job': started['id']})
        jobs.pool.shutdown(wait=True)
        self.assertEqual(retried['retried'], ['deepseek'])
        self.assertEqual(jobs.get(retried['id'])['state'], 'completed')
        self.assertEqual(len(providers['deepseek'].calls), 2)
        self.assertEqual(len(providers['gemini'].calls), 1)

    def test_retry_running_job_reattaches_without_second_submission(self):
        jobs = server.Jobs({'gemini': FakeProvider('gemini'), 'deepseek': FakeProvider('deepseek')})
        ctrl = MultiCtrlJobs(jobs, server.read_input)
        ctrl.sessions['s'] = {'models': {}, 'original': '题目'}
        jobs.items['j'] = {'id': 'j', 'kind': 'ctrl-start', 'session': 's', 'state': 'running',
                           'results': {'deepseek': {'state': 'running'}}}
        self.assertEqual(ctrl.retry({'job': 'j'}), {'id': 'j', 'session': 's', 'resumed': True})
        jobs.pool.shutdown(wait=True)

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
        jobs.pool.shutdown(wait=True)
        self.assertEqual(jobs.get(retried['id'])['state'], 'completed')
        self.assertEqual(len(provider.calls), 0)


if __name__ == '__main__':
    unittest.main()
