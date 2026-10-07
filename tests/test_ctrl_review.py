import base64
import json
import threading
import unittest
import test_api_workflows as workflow_fixtures


class ReviewTests(unittest.TestCase):
    setUp = workflow_fixtures.ApiWorkflowTests.setUp
    tearDown = workflow_fixtures.ApiWorkflowTests.tearDown

    def start(self, image=False):
        self.qwen._request = lambda *args: {'status':'completed','text':json.dumps({
            'original':'原题2024', 'keywords':['初始'], 'sites':[], 'answer':'初始答案A'})}
        data = {'text':'原题2024','models':['qwen'],'fast_answer':True}
        if image: data['image'] = 'data:image/png;base64,'+base64.b64encode(b'\x89PNG\r\n\x1a\nfixture').decode()
        task = self.ctrl.start(data); self.ctrl.wait_idle()
        return task['session']

    def test_review_keeps_first_answer_and_uses_independent_input(self):
        session = self.start()
        calls = []
        def request(config,messages,progress):
            calls.append(messages)
            self.assertEqual(config['model'],'deepseek-v4-flash-0731')
            return {'status':'completed','text':'复核答案B'}
        self.intern._request = request
        submitted = self.ctrl.reviews.submit({'session':session,'stage':'answer','model':'intern:deepseek-v4-flash-0731'})
        self.ctrl.wait_idle()
        saved = self.ctrl.get_session(session)
        self.assertEqual(saved['models']['qwen']['answer'],'初始答案A')
        self.assertEqual(len(saved['versions']['answer']),2)
        self.assertEqual(saved['versions']['answer'][-1]['answer'],'复核答案B')
        self.assertEqual(saved['versions']['answer'][-1]['requested_model'],'deepseek-v4-flash-0731')
        self.assertEqual(saved['versions']['answer'][-1]['source_job'],submitted['id'])
        self.assertNotIn('初始答案A',str(calls))
        self.assertEqual(len(calls[0]),1)

    def test_adopting_ocr_marks_old_analysis_and_inflight_review_without_overwriting(self):
        session = self.start(image=True)
        self.intern._request = lambda *args: {'status':'completed','text':'原题2025'}
        self.ctrl.reviews.submit({'session':session,'stage':'ocr','model':'intern:deepseek-v4-flash-vision'})
        self.ctrl.wait_idle()
        before = self.ctrl.get_session(session)
        revision = before['versions']['ocr'][-1]['id']
        entered = threading.Event()
        def analysis(*args):
            entered.set(); self.release.wait(3)
            return {'status':'completed','text':'{"keywords":["旧原题复核"],"sites":[]}'}
        self.intern._request = analysis
        data = {'session':session,'stage':'analysis','model':'intern:deepseek-v4-flash-0731'}
        first = self.ctrl.reviews.submit(data)
        self.assertTrue(entered.wait(2))
        again = self.ctrl.reviews.submit(data)
        self.assertEqual(first['id'],again['id'])
        self.ctrl.reviews.adopt({'session':session,'version':revision})
        self.release.set(); self.ctrl.wait_idle()
        saved = self.ctrl.get_session(session)
        self.assertEqual(saved['original'],'原题2025')
        self.assertEqual(saved['versions']['analysis'][-1]['based_on'],'base')
        self.assertNotEqual(saved['versions']['analysis'][-1]['based_on'],saved['original_revision'])

    def test_review_parse_failure_retry_reuses_complete_response(self):
        session = self.start()
        self.intern._request = lambda *args: {'status':'completed','text':'格式错误'}
        review = self.ctrl.reviews.submit({'session':session,'stage':'analysis','model':'intern'})
        self.ctrl.wait_idle()
        self.assertEqual(self.jobs.get(review['id'])['state'],'failed')
        run = self.ctrl.reviews.runs[review['id']]
        run['text'] = '{"keywords":["已恢复"],"sites":[]}'
        self.intern._request = lambda *args: self.fail('读取完整回复不应重新调用 API')
        retried = self.ctrl.retry({'job':review['id']})
        self.ctrl.wait_idle()
        self.assertEqual(self.jobs.get(retried['id'])['state'],'completed')
        self.assertEqual(len(self.ctrl.get_session(session)['versions']['analysis']),2)

    def test_text_model_cannot_review_ocr_and_secret_config_not_exposed(self):
        session = self.start(image=True)
        with self.assertRaises(ValueError):
            self.ctrl.reviews.submit({'session':session,'stage':'ocr','model':'intern:deepseek-v4-flash-0731'})
        saved = json.dumps(self.ctrl.get_session(session))
        self.assertNotIn('test-placeholder-key',saved)
        self.assertNotIn('api_key',saved)
        for _ in range(3): self.ctrl.get_session(session)
        self.assertEqual(len(self.ctrl.get_session(session)['versions']['analysis']),1)

    def test_failed_stage_remains_retryable_after_other_stage_succeeds(self):
        session = self.start()
        self.intern._request = lambda *args: {'status':'failed','detail':'fixture error'}
        failed = self.ctrl.reviews.submit({'session':session,'stage':'analysis','model':'intern'})
        self.ctrl.wait_idle()
        self.intern._request = lambda *args: {'status':'completed','text':'独立答案'}
        self.ctrl.reviews.submit({'session':session,'stage':'answer','model':'intern'})
        self.ctrl.wait_idle()
        self.assertEqual(self.ctrl.get_session(session)['failed_job'],failed['id'])
        retried = self.ctrl.retry({'job':failed['id'],'mode':'restart'})
        self.ctrl.wait_idle()
        self.assertEqual(self.ctrl.get_session(session)['failed_job'],retried['id'])


if __name__ == '__main__': unittest.main()
