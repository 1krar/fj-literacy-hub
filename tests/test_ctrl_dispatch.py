import json
import sys
from pathlib import Path
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from assistant_server import Jobs, read_input
from ctrl_multi import MultiCtrlJobs


class Provider:
    def __init__(self):
        self.entered = threading.Event()
        self.release = threading.Event()
        self.block = True
        self.calls = []

    def generate_with_progress(self, prompt, path, progress):
        if self.block:
            self.entered.set()
            if not self.release.wait(3):
                raise RuntimeError('test gate timed out')
        self.calls.append(prompt)
        return {'status': 'completed', 'text': json.dumps({'keywords': ['检索'], 'sites': []})}


class DispatchTests(unittest.TestCase):
    def setUp(self):
        self.providers = {name: Provider() for name in ('deepseek', 'gemini')}
        self.jobs = Jobs(self.providers)
        self.ctrl = MultiCtrlJobs(self.jobs, read_input)

    def tearDown(self):
        for provider in self.providers.values():
            provider.release.set()
        for name in self.providers:
            self.ctrl.dispatcher.set_ready(name, True)
        self.ctrl.shutdown()
        self.jobs.pool.shutdown()

    def start(self, text):
        return self.ctrl.start({'text': text, 'models': ['deepseek', 'gemini']})

    def test_global_queue_uses_first_free_model_without_pinning_waiting_question(self):
        first = self.start('第一题')
        self.assertTrue(self.providers['deepseek'].entered.wait(1))
        second = self.start('第二题')
        self.assertTrue(self.providers['gemini'].entered.wait(1))
        third = self.start('第三题')
        self.assertIsNone(self.ctrl.get_session(third['session'])['assigned'])
        self.assertEqual(set(self.jobs.get(third['id'])['results']), {'waiting'})
        self.providers['gemini'].release.set()
        self.ctrl.model_pools['gemini'].submit(lambda: None).result(timeout=3)
        # A dispatch may enqueue third behind this sentinel; wait explicitly for its result.
        deadline = __import__('time').monotonic()+2
        while self.jobs.get(third['id'])['state'] == 'running' and __import__('time').monotonic() < deadline:
            threading.Event().wait(.01)
        self.assertEqual(self.ctrl.get_session(third['session'])['assigned'], 'gemini')
        self.assertEqual(self.jobs.get(third['id'])['state'], 'completed')
        self.assertEqual(self.jobs.get(first['id'])['state'], 'running')
        self.providers['deepseek'].release.set()
        self.ctrl.wait_idle()
        self.assertEqual(sum(len(p.calls) for p in self.providers.values()), 3)
        self.assertEqual(self.ctrl.get_session(first['session'])['assigned'], 'deepseek')
        self.assertEqual(self.ctrl.get_session(second['session'])['assigned'], 'gemini')

    def test_manual_answer_has_priority_is_idempotent_and_keeps_assignee(self):
        ds = self.providers['deepseek']
        ds.block = False
        first = self.ctrl.start({'text': '已识别题目', 'models': ['deepseek']})
        self.ctrl.wait_idle()
        order = []
        generate = ds.generate_with_progress
        def track(prompt, path, progress):
            result = generate(prompt, path, progress)
            order.append('第三题' if '第三题' in prompt else '第二题')
            return result
        ds.generate_with_progress = track
        ds.block = True
        self.ctrl.start({'text': '第二题', 'models': ['deepseek']})
        self.assertTrue(ds.entered.wait(1))
        self.ctrl.start({'text': '第三题', 'models': ['deepseek']})
        def answer(job_id, session_id, name):
            order.append('答案')
            self.ctrl._mark(job_id, name, state='completed', answer='A')
        self.ctrl._answer_queued = answer
        answered = self.ctrl.answer({'session': first['session'], 'models': ['gemini']})
        again = self.ctrl.answer({'session': first['session']})
        self.assertEqual(again['id'], answered['id'])
        ds.release.set()
        self.ctrl.wait_idle()
        self.assertEqual(order, ['第二题', '答案', '第三题'])
        self.assertEqual(self.jobs.get(answered['id'])['models'], ['deepseek'])
        self.assertEqual(self.providers['gemini'].calls, [])

    def test_disconnected_model_is_skipped_and_waiting_queue_wakes_on_reconnect(self):
        self.ctrl.dispatcher.set_ready('deepseek', False)
        self.providers['gemini'].release.set()
        first = self.start('连接测试')
        self.ctrl.wait_idle()
        self.assertEqual(self.ctrl.get_session(first['session'])['assigned'], 'gemini')
        pending = self.ctrl.start({'text': '仅 DeepSeek', 'models': ['deepseek']})
        self.assertIsNone(self.ctrl.get_session(pending['session'])['assigned'])
        self.providers['deepseek'].release.set()
        self.ctrl.dispatcher.set_ready('deepseek', True)
        self.ctrl.wait_idle()
        self.assertEqual(self.ctrl.get_session(pending['session'])['assigned'], 'deepseek')


if __name__ == '__main__':
    unittest.main()
