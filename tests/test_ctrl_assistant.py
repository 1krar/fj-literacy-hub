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


if __name__ == '__main__':
    unittest.main()
