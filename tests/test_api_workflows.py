import base64
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from assistant_server import Jobs, read_input
from ctrl_multi import MultiCtrlJobs
from qwen_api import QwenProvider
from intern_api import InternProvider


class ApiWorkflowTests(unittest.TestCase):
    def test_upgrade_handover_preserves_completed_results_without_credentials(self):
        self.ctrl.restore_completed([{'session':'upgrade-test', 'data': {
            'state':'completed','original':'原题','assigned':'qwen',
            'models':{'qwen':{'original':'原题','route':{'keywords':['原题'],'sites':[]},'answer':'答案'}},
            'activity':{'qwen':{'state':'completed','stage':'已返回'}}}}])
        restored = self.ctrl.get_session('upgrade-test')
        self.assertEqual(restored['models']['qwen']['answer'], '答案')
        self.assertEqual(self.ctrl.sessions['upgrade-test']['api_configs'], {})
        self.assertEqual(self.ctrl.list_tasks()[0]['state'], 'completed')
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.qwen = QwenProvider(Path(self.temp.name)/'qwen.dpapi')
        self.qwen.configure({'api_key': 'test-placeholder-key'})
        self.intern = InternProvider(Path(self.temp.name)/'intern.dpapi')
        self.intern.configure({'api_key': 'test-placeholder-key'})
        self.jobs = Jobs({'gemini': self.qwen, 'qwen': self.qwen, 'intern': self.intern})
        self.ctrl = MultiCtrlJobs(self.jobs, read_input)
        self.release = threading.Event()

    def tearDown(self):
        self.release.set()
        self.ctrl.shutdown()
        self.jobs.pool.shutdown()
        self.temp.cleanup()

    def test_six_requests_overlap_seventh_waits_and_results_stay_with_question(self):
        count = 0
        gate = threading.Condition()
        seen_keys = []
        def request(config, messages, progress):
            nonlocal count
            with gate:
                count += 1
                seen_keys.append(config['api_key'])
                gate.notify_all()
            self.release.wait(3)
            text = messages[-1]['content'].split('\n')[1]
            return {'status': 'completed', 'text': json.dumps({'keywords':[text], 'sites':[]})}
        self.qwen._request = request
        tasks = [self.ctrl.start({'text': f'第{i}题', 'models':['qwen']}) for i in range(7)]
        with gate:
            self.assertTrue(gate.wait_for(lambda: count == 6, timeout=2))
        state = self.ctrl.dispatcher.snapshot()
        self.assertEqual(state['api_active'], 6)
        self.assertEqual(state['waiting'], 1)
        self.qwen.configure({'api_key':'new-test-placeholder-key'})
        self.release.set()
        self.ctrl.wait_idle()
        self.assertEqual(count, 7)
        self.assertEqual(set(seen_keys), {'test-placeholder-key'})
        for i, task in enumerate(tasks):
            self.assertEqual(self.ctrl.get_session(task['session'])['models']['qwen']['route']['keywords'], [f'第{i}题'])

    def test_combined_image_publishes_complete_original_before_request_finishes(self):
        original_ready = threading.Event()
        def request(config, messages, progress):
            progress.on_text('{"original":"不正确的是？A甲 B乙",')
            original_ready.set()
            self.release.wait(3)
            return {'status':'completed', 'text':json.dumps({'original':'不正确的是？A甲 B乙','keywords':['甲'],'sites':[]})}
        self.qwen._request = request
        image = 'data:image/png;base64,'+base64.b64encode(b'\x89PNG\r\n\x1a\nfixture').decode()
        task = self.ctrl.start({'image':image,'models':['qwen']})
        self.assertTrue(original_ready.wait(2))
        session = self.ctrl.get_session(task['session'])
        self.assertEqual(session['original'], '不正确的是？A甲 B乙')
        self.assertEqual(session['state'], 'running')
        self.release.set()
        self.ctrl.wait_idle()
        self.assertEqual(self.ctrl.get_session(task['session'])['state'], 'completed')

    def test_two_api_providers_share_six_slots_and_use_idle_provider_first(self):
        def request(*args):
            self.release.wait(3)
            return {'status':'completed','text':'{"keywords":["甲"],"sites":[]}'}
        self.qwen._request = self.intern._request = request
        tasks = [self.ctrl.start({'text':f'题{i}', 'models':['qwen','intern']}) for i in range(7)]
        state = self.ctrl.dispatcher.snapshot()
        self.assertEqual(state['api_active'], 6)
        self.assertEqual(state['models']['qwen']['active'], 3)
        self.assertEqual(state['models']['intern']['active'], 3)
        self.assertEqual(state['waiting'], 1)
        self.assertEqual([self.ctrl.get_session(task['session'])['assigned'] for task in tasks[:2]], ['qwen','intern'])
        self.release.set()
        self.ctrl.wait_idle()

    def test_answer_can_use_another_provider_without_replacing_route_context(self):
        sent = []
        self.qwen._request = lambda *args: {'status':'completed','text':'{"keywords":["关键词"],"sites":[]}'}
        def request(config, messages, progress):
            sent.append(messages)
            return {'status':'completed','text':'答案 B，待核验'}
        self.intern._request = request
        task = self.ctrl.start({'text':'第一道题','models':['qwen']})
        self.ctrl.wait_idle()
        answer = self.ctrl.answer({'session':task['session'], 'model':'intern'})
        self.ctrl.wait_idle()
        session = self.ctrl.get_session(task['session'])
        self.assertEqual(session['assigned'], 'qwen')
        self.assertEqual(session['models']['intern']['answer'], '答案 B，待核验')
        self.assertEqual(len(sent[0]), 1)
        self.assertIn('第一道题', sent[0][0]['content'])
        self.assertTrue(session['models']['qwen']['route'])
        self.assertEqual(self.jobs.get(answer['id'])['models'], ['intern'])

    def test_split_ocr_routes_next_stage_on_different_provider(self):
        self.qwen._request = lambda *args: {'status':'completed','text':'题目原文'}
        self.intern._request = lambda *args: {'status':'completed','text':'{"keywords":["原文"],"sites":[]}'}
        image = 'data:image/png;base64,'+base64.b64encode(b'\x89PNG\r\n\x1a\nfixture').decode()
        task = self.ctrl.start({'image':image,'models':['qwen'], 'analysis_model':'intern'})
        self.ctrl.wait_idle()
        session = self.ctrl.get_session(task['session'])
        self.assertEqual(session['original'], '题目原文')
        self.assertEqual(session['models']['intern']['route']['keywords'], ['原文'])
        self.assertEqual(session['state'], 'completed')

    def test_retry_parses_saved_output_without_another_paid_request(self):
        self.qwen._request = lambda *args: {'status':'completed','text':'{"keywords":["甲"],"sites":[]}'}
        task = self.ctrl.start({'text':'原题','models':['qwen']})
        self.ctrl.wait_idle()
        self.jobs.items[task['id']]['state'] = 'failed'
        self.jobs.items[task['id']]['results']['qwen']['state'] = 'failed'
        def forbidden(*args):
            raise AssertionError('retry must reuse the saved complete output')
        self.qwen._request = forbidden
        retry = self.ctrl.retry({'job':task['id']})
        self.ctrl.wait_idle()
        self.assertEqual(self.jobs.get(retry['id'])['state'], 'completed')

    def test_intern_vision_ocr_then_text_model_analysis_uses_selected_ids(self):
        called = []
        def request(config, messages, progress):
            called.append(config['model'])
            return {'status':'completed', 'text':'题目原文' if len(called) == 1 else
                    '{"keywords":["题目"],"sites":[]}'}
        self.intern._request = request
        image = 'data:image/png;base64,'+base64.b64encode(b'\x89PNG\r\n\x1a\nfixture').decode()
        task = self.ctrl.start({'image':image, 'models':['intern'],
            'ocr_model':'intern:deepseek-v4-flash-vision', 'analysis_model':'intern:deepseek-v4-flash-0731'})
        self.ctrl.wait_idle()
        self.assertEqual(called, ['deepseek-v4-flash-vision','deepseek-v4-flash-0731'])
        self.assertEqual(self.ctrl.get_session(task['session'])['state'], 'completed')

    def test_intern_endpoint_and_thinking_are_not_silently_rewritten(self):
        payload = self.intern._payload(self.intern.config, [])
        self.assertNotIn('enable_thinking', payload)
        self.assertNotIn('thinking', payload)
        self.assertNotIn('api_key', self.intern.public_config())
        for endpoint in ['https://discovery-api.intern-ai.org.cn.evil.example/v1',
                         'https://key@discovery-api.intern-ai.org.cn/v1']:
            with self.assertRaises(ValueError):
                self.intern.configure({'api_key':'test-placeholder-key', 'base_url':endpoint})


if __name__ == '__main__':
    unittest.main()
