import base64
import importlib.util
import json
from pathlib import Path
import threading
import unittest
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from http.server import ThreadingHTTPServer

spec = importlib.util.spec_from_file_location('assistant_server', Path(__file__).resolve().parents[1] / 'scripts/assistant_server.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class Provider:
    def __init__(self):
        self.result = {'status': 'completed', 'text': '{"fixture":"not a real AI answer"}'}
        self.images = []
    def status(self):
        return {'status': 'ready', 'detail': 'mock'}
    def start_browser(self):
        return {'status': 'window_opened'}
    def generate_with_progress(self, prompt, path, progress):
        if path:
            self.images.append(path)
            assert path.is_file()
        progress('mock progress')
        return self.result


class InputTests(unittest.TestCase):
    def test_question_and_prompt_bounds(self):
        for data in [{}, {'question': '', 'prompt': 'x'}, {'question': 'q', 'prompt': 'x' * 24001}]:
            with self.assertRaises(ValueError): module.read_input(data)
    def test_image_validation(self):
        for image in ['data:text/html;base64,PHNjcmlwdD4=', 'data:image/png;base64,AAAA', 'data:image/png;base64,!!!']:
            with self.assertRaises(ValueError): module.read_input({'question': 'q', 'prompt': 'p', 'image': image})
    def test_failure_never_becomes_completed(self):
        p = Provider(); p.result = {'status': 'timeout', 'partial_text': 'partial'}
        jobs = module.Jobs(p)
        job = jobs.submit({'question': 'q', 'prompt': 'p'})
        jobs.pool.shutdown(wait=True)
        self.assertEqual(jobs.get(job['id'])['state'], 'failed')
        self.assertNotIn('text', jobs.get(job['id']))
    def test_image_removed_after_job(self):
        p = Provider(); jobs = module.Jobs(p)
        raw = b'\x89PNG\r\n\x1a\nfixture'
        job = jobs.submit({'question': 'q', 'prompt': 'p', 'image': 'data:image/png;base64,' + base64.b64encode(raw).decode()})
        jobs.pool.shutdown(wait=True)
        self.assertEqual(jobs.get(job['id'])['state'], 'completed')
        self.assertFalse(p.images[0].exists())

    def test_dual_models_keep_failure_separate(self):
        gemini = Provider(); deepseek = Provider()
        deepseek.result = {'status': 'timeout', 'detail': 'fixture timeout', 'partial_text': 'do not use'}
        jobs = module.Jobs({'gemini': gemini, 'deepseek': deepseek})
        job = jobs.submit({'question': 'q', 'prompt': 'p', 'models': ['gemini', 'deepseek']})
        jobs.pool.shutdown(wait=True)
        result = jobs.get(job['id'])
        self.assertEqual(result['state'], 'completed')
        self.assertEqual(result['results']['gemini']['state'], 'completed')
        self.assertEqual(result['results']['deepseek']['state'], 'failed')
        self.assertNotIn('text', result['results']['deepseek'])
    def test_screenshot_sent_independently_to_both(self):
        gemini = Provider(); deepseek = Provider()
        jobs = module.Jobs({'gemini': gemini, 'deepseek': deepseek})
        raw = b'\x89PNG\r\n\x1a\nfixture'
        job = jobs.submit({'question': 'q', 'prompt': 'p', 'models': ['deepseek', 'gemini'], 'image': 'data:image/png;base64,' + base64.b64encode(raw).decode()})
        jobs.pool.shutdown(wait=True)
        self.assertEqual(len(gemini.images), 1)
        self.assertEqual(gemini.images, deepseek.images)
        self.assertFalse(gemini.images[0].exists())
        self.assertEqual(set(jobs.get(job['id'])['results']), {'gemini', 'deepseek'})
    def test_models_validated_before_submission(self):
        jobs = module.Jobs({'gemini': Provider(), 'deepseek': Provider()})
        for names in [[], ['unknown'], ['gemini', 'gemini']]:
            with self.assertRaises(ValueError): jobs.submit({'question': 'q', 'prompt': 'p', 'models': names})
        jobs.pool.shutdown(wait=True)
    def test_deepseek_only_does_not_call_gemini(self):
        class CountProvider(Provider):
            def __init__(self): super().__init__(); self.calls = 0
            def generate_with_progress(self, *args): self.calls += 1; return super().generate_with_progress(*args)
        gemini = CountProvider(); deepseek = CountProvider()
        jobs = module.Jobs({'gemini': gemini, 'deepseek': deepseek})
        jobs.submit({'question': 'q', 'prompt': 'p', 'models': ['deepseek']})
        jobs.pool.shutdown(wait=True)
        self.assertEqual(gemini.calls, 0)
        self.assertEqual(deepseek.calls, 1)

    def test_models_start_in_parallel_and_publish_first_result_while_running(self):
        gate = threading.Event(); slow_started = threading.Event(); fast_finished = threading.Event()
        class Slow(Provider):
            def generate_with_progress(self, *args):
                slow_started.set()
                if not gate.wait(3): raise RuntimeError('fixture gate expired')
                return super().generate_with_progress(*args)
        class Fast(Provider):
            def generate_with_progress(self, *args):
                if not slow_started.wait(1): raise RuntimeError('models were not parallel')
                result = super().generate_with_progress(*args)
                fast_finished.set()
                return result
        jobs = module.Jobs({'gemini': Slow(), 'deepseek': Fast()})
        try:
            job = jobs.submit({'question': 'q', 'prompt': 'p', 'models': ['gemini','deepseek']})
            self.assertTrue(fast_finished.wait(1))
            # Read a published snapshot while the slow provider is still gated.
            import time
            deadline = time.monotonic() + 1
            while 'deepseek' not in jobs.get(job['id'])['results'] and time.monotonic() < deadline: time.sleep(.01)
            result = jobs.get(job['id'])
            self.assertEqual(result['state'], 'running')
            self.assertEqual(result['results']['deepseek']['state'], 'completed')
            self.assertEqual(result['progress']['gemini']['state'], 'running')
            self.assertNotIn('gemini', result['results'])
        finally:
            gate.set(); jobs.pool.shutdown(wait=True)

    def test_completed_tab_closes_after_result_published(self):
        class CleanupProvider(Provider):
            def close_saved_response(inner, receipt):
                self.assertEqual(jobs.get(job_id)['results']['gemini']['state'], 'completed')
                inner.closed = receipt
                return {'status':'closed'}
        p = CleanupProvider(); p.result['cleanup_receipt'] = 'owned'
        jobs = module.Jobs(p)
        # Execute synchronously so the assertion can reference the known ID.
        job_id = 'fixture'
        jobs.items[job_id] = {'results':{},'progress':{'gemini':{}}}
        jobs.run(job_id, 'p', None, None, ['gemini'])
        jobs.pool.shutdown(wait=True)
        self.assertEqual(p.closed, 'owned')
        self.assertEqual(jobs.get(job_id)['results']['gemini']['tab_cleanup'], 'closed')

    def test_failed_tab_retained_until_next_request(self):
        class CleanupProvider(Provider):
            def __init__(inner): super().__init__(); inner.closed=[]
            def close_saved_response(inner, receipt): inner.closed.append(receipt); return {'status':'closed'}
        p=CleanupProvider(); p.result={'status':'timeout','detail':'fixture timeout','cleanup_receipt':'failed-tab'}
        jobs=module.Jobs(p)
        for index in range(2):
            job_id=str(index); jobs.items[job_id]={'results':{},'progress':{'gemini':{}}}
            if index: p.result={'status':'completed','text':'answer','cleanup_receipt':'new-tab'}
            jobs.run(job_id,'p',None,None,['gemini'])
            if not index:self.assertEqual(p.closed,[])
        jobs.pool.shutdown(wait=True)
        self.assertEqual(p.closed,['failed-tab','new-tab'])

    def test_cleanup_error_does_not_discard_complete_answer(self):
        class CleanupProvider(Provider):
            def close_saved_response(inner, receipt): raise RuntimeError('cleanup failed')
        p=CleanupProvider(); p.result['cleanup_receipt']='owned'
        jobs=module.Jobs(p); job=jobs.submit({'question':'q','prompt':'p'}); jobs.pool.shutdown(wait=True)
        self.assertEqual(jobs.get(job['id'])['state'],'completed')
        self.assertEqual(jobs.get(job['id'])['results']['gemini']['tab_cleanup'],'retained')


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.jobs = module.Jobs(Provider())
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), module.handler_for(self.jobs, 'test-session'))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True); self.thread.start()
        self.url = 'http://127.0.0.1:' + str(self.server.server_port)
    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.jobs.pool.shutdown(wait=True)
    def request(self, path, headers=None, data=None):
        req = Request(self.url + path, data=json.dumps(data).encode() if data is not None else None, headers=headers or {})
        return urlopen(req, timeout=3)
    def test_external_origins_cannot_call(self):
        for headers in [{'Origin': 'https://evil.example'}, {'Sec-Fetch-Site': 'cross-site'}]:
            with self.assertRaises(HTTPError) as e: self.request('/api/session', headers)
            self.assertEqual(e.exception.code, 403)
    def test_mutation_requires_session(self):
        with self.assertRaises(HTTPError) as e: self.request('/api/jobs', data={'question': 'q', 'prompt': 'p'})
        self.assertEqual(e.exception.code, 403)
    def test_production_launch_probe_is_read_only_and_has_no_session(self):
        h={'Origin':'https://fj-literacy-hub.pages.dev','Sec-Fetch-Site':'cross-site'}
        with self.request('/api/launch-status',h) as r:
            self.assertEqual(json.load(r),{'app':'literacy-assistant','ready':True})
            self.assertEqual(r.headers['Access-Control-Allow-Origin'],h['Origin'])
        for path in ['/api/session','/api/status','/api/jobs/example']:
            with self.assertRaises(HTTPError) as e:self.request(path,h)
            self.assertEqual(e.exception.code,403)
        with self.assertRaises(HTTPError) as e:self.request('/api/jobs',h,{'question':'q','prompt':'p'})
        self.assertEqual(e.exception.code,403)
    def test_launch_probe_rejects_other_origins(self):
        with self.assertRaises(HTTPError) as e:self.request('/api/launch-status',{'Origin':'https://evil.example'})
        self.assertEqual(e.exception.code,403)
    def test_launch_preflight_only_allows_production_readiness_get(self):
        h={'Origin':'https://fj-literacy-hub.pages.dev','Access-Control-Request-Method':'GET'}
        req=Request(self.url+'/api/launch-status',method='OPTIONS',headers=h)
        with urlopen(req,timeout=3) as r:self.assertEqual(r.headers['Access-Control-Allow-Private-Network'],'true')
        for path,method in [('/api/session','GET'),('/api/launch-status','POST')]:
            req=Request(self.url+path,method='OPTIONS',headers={**h,'Access-Control-Request-Method':method})
            with self.assertRaises(HTTPError) as e:urlopen(req,timeout=3)
            self.assertEqual(e.exception.code,403)
    def test_only_public_static_files(self):
        for path in ['/.runtime/assistant.pid', '/scripts/assistant_server.py', '/../DEPLOY.md']:
            with self.assertRaises(HTTPError) as e: self.request(path)
            self.assertEqual(e.exception.code, 404)
    def test_public_navigation_allowed_but_not_public_api(self):
        h = {'Sec-Fetch-Site': 'cross-site', 'Sec-Fetch-Mode': 'navigate'}
        with self.request('/assistant.html', h) as r: self.assertEqual(r.status, 200)
        with self.assertRaises(HTTPError): self.request('/api/session', h)
    def test_job_submission(self):
        with self.request('/api/jobs', {'X-Assistant-Session': 'test-session'}, {'question': 'q', 'prompt': 'p'}) as r:
            self.assertEqual(r.status, 202)
            self.assertIn('id', json.load(r))


if __name__ == '__main__': unittest.main()
