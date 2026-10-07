import base64
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from qwen_api import DEFAULT_BASE, QwenProvider, validate_base


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.provider = QwenProvider(Path(self.temp.name) / 'config.dpapi')
        self.config = {'model':'qwen3.8-flash', 'base_url':'https://example.cn-beijing.maas.aliyuncs.com/compatible-mode/v1',
                       'api_key':'test-not-a-real-credential', 'remember':False}
        self.provider.configure(self.config)

    def tearDown(self):
        self.temp.cleanup()

    def stream(self, text, finish='stop'):
        parts = [json.dumps({'choices':[{'delta':{'content':text},'finish_reason':None}]}),
                 json.dumps({'choices':[{'delta':{},'finish_reason':finish}]}), '[DONE]']
        return io.BytesIO(('\n'.join('data: '+part for part in parts)+'\n').encode())

    def test_streaming_image_and_followup_keep_task_context_and_disable_thinking(self):
        image = Path(self.temp.name) / 'screenshot.png'
        image.write_bytes(b'\x89PNG\r\n\x1a\nfixture')
        sent, stages = [], []
        def open_request(request, timeout):
            sent.append(json.loads(request.data))
            return self.stream('原题 ABC' if len(sent) == 1 else '关键词结果')
        with patch('qwen_api.build_opener') as opener:
            opener.return_value.open.side_effect = open_request
            first = self.provider.generate_with_progress('OCR', image, stages.append)
            second = self.provider.continue_saved(first['cleanup_receipt'], '提取关键词', stages.append)
        self.assertEqual(second['status'], 'completed')
        self.assertEqual([item['role'] for item in sent[1]['messages']], ['user','assistant','user'])
        self.assertIn('data:image/png;base64,', sent[0]['messages'][0]['content'][1]['image_url']['url'])
        self.assertFalse(sent[0]['enable_thinking'])
        self.assertEqual(self.provider.read_saved_reply(first['cleanup_receipt']), '关键词结果')
        self.assertIn('正在接收千问 API 回复', stages)
        self.provider.close_saved_response(first['cleanup_receipt'])
        self.assertIsNone(self.provider.read_saved_reply(first['cleanup_receipt']))

    def test_truncated_reply_and_http_failure_are_not_cached_or_automatically_retried(self):
        with patch('qwen_api.build_opener') as opener:
            opener.return_value.open.return_value = self.stream('不完整', 'length')
            result = self.provider.generate_with_progress('题目', None, lambda value: None)
            self.assertEqual(result['status'], 'failed')
            self.assertIsNone(self.provider.read_saved_reply(result['cleanup_receipt']))
            self.assertEqual(opener.return_value.open.call_count, 1)
        with patch('qwen_api.build_opener') as opener:
            opener.return_value.open.side_effect = HTTPError('url',401,'secret server body',{},None)
            result = self.provider.generate_with_progress('题目', None, lambda value: None)
            self.assertIn('401', result['detail'])
            self.assertNotIn('secret', result['detail'])
            self.assertEqual(opener.return_value.open.call_count, 1)

    def test_config_is_not_exposed_and_only_official_https_endpoints_are_allowed(self):
        self.assertNotIn('api_key', self.provider.public_config())
        self.assertNotIn(self.config['api_key'], json.dumps(self.provider.status()))
        for value in ['http://dashscope.aliyuncs.com/compatible-mode/v1',
                      'https://evil.example/compatible-mode/v1',
                      'https://dashscope.aliyuncs.com.evil.example/compatible-mode/v1',
                      'https://maas.qianwenaiapi.com.evil.example/compatible-mode/v1',
                      'https://evil.qianwenaiapi.com/compatible-mode/v1',
                      'https://key@dashscope.aliyuncs.com/compatible-mode/v1',
                      'https://dashscope.aliyuncs.com/compatible-mode/v1?key=secret']:
            with self.assertRaises(ValueError):
                validate_base(value)

    def test_qwen_official_preset_and_full_request_url_normalize_to_base(self):
        for value in ('', '  ', DEFAULT_BASE, DEFAULT_BASE+'/', DEFAULT_BASE+'/chat/completions',
                      ' '+DEFAULT_BASE+'/chat/completions/ '):
            self.assertEqual(validate_base(value), DEFAULT_BASE)
        self.provider.configure({**self.config, 'base_url':DEFAULT_BASE+'/chat/completions'})
        self.assertEqual(self.provider.public_config()['base_url'], DEFAULT_BASE)
        with patch('qwen_api.build_opener') as opener:
            opener.return_value.open.return_value = self.stream('结果')
            result = self.provider.generate_with_progress('题目', None, lambda stage: None)
            self.assertEqual(result['status'], 'completed')
            request = opener.return_value.open.call_args.args[0]
            self.assertEqual(request.full_url, DEFAULT_BASE+'/chat/completions')
        fresh = QwenProvider(Path(self.temp.name)/'new.dpapi')
        self.assertEqual(fresh.public_config()['base_url'], DEFAULT_BASE)
        self.assertFalse(fresh.public_config()['configured'])

    @unittest.skipUnless(os.name == 'nt', 'Windows DPAPI')
    def test_remembered_config_is_encrypted_and_can_be_reloaded_then_removed(self):
        self.provider.configure({**self.config, 'remember':True})
        self.assertNotIn(self.config['api_key'].encode(), self.provider.path.read_bytes())
        loaded = QwenProvider(self.provider.path)
        self.assertTrue(loaded.public_config()['configured'])
        self.assertTrue(loaded.public_config()['remembered'])
        loaded.configure({**self.config, 'api_key':'', 'remember':False})
        self.assertFalse(loaded.path.exists())


if __name__ == '__main__':
    unittest.main()
