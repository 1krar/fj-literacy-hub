import sys
from pathlib import Path
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from api_only import validate_api_request
import assistant_server
import start_assistant

class Win7ApiTests(unittest.TestCase):
    def test_web_models_are_rejected_before_queue(self):
        for data in ({'models':['deepseek']},{'model':'gemini'},{'ocr_model':'deepseek'}, {'answer_model':'gemini'}):
            with self.assertRaisesRegex(ValueError,'API'):validate_api_request(data)
        with self.assertRaises(ValueError):validate_api_request({},'/api/jobs')
        with self.assertRaises(ValueError):validate_api_request({},'/api/ctrl/start')

    def test_api_models_and_gateway_ids_are_accepted(self):
        validate_api_request({'models':['qwen','intern'],'ocr_model':'intern:deepseek-v4-flash-vision'},'/api/ctrl/start')
        validate_api_request({'model':'deepseek-v4-flash-0731'},'/api/ctrl/intern-config')

    def test_api_only_does_not_import_playwright_or_browser_adapters(self):
        with patch.object(assistant_server,'API_ONLY',True),patch.object(assistant_server.importlib.util,'spec_from_file_location') as loader:
            providers=assistant_server.load_provider(Path('does-not-exist'))
            loader.assert_not_called()
            self.assertEqual(providers['gemini'].status()['status'],'unavailable')
        with patch.object(start_assistant,'API_ONLY',True),patch.object(Path,'is_file',return_value=True),patch.object(start_assistant.importlib.util,'find_spec') as find:
            start_assistant.ensure_environment();find.assert_not_called()

    def test_query_prefix_replacement_preserves_input(self):
        self.assertEqual(assistant_server.query_value('/api/status?model=qwen','model='),'qwen')
        self.assertEqual(assistant_server.query_value('/api/x?id=some-id','id='),'some-id')
        self.assertEqual(assistant_server.query_value('/api/x?bad-id=some','id='),'bad-id=some')

if __name__=='__main__':unittest.main()
