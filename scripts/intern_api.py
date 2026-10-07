"""Intern InkStone adapter. Uses the shared local encrypted configuration workflow."""
import re
from urllib.parse import urlsplit
from qwen_api import QwenProvider

MODELS = {'deepseek-v4-flash-vision', 'deepseek-v4-flash-0731', 'intern-s2',
          'kimi-k2.6', 'qwen3.8-27b', 'Agents-A1', 'glm-5.3', 'minimax-m3',
          'deepseek-v4-pro-0813', 'Atria-Dawn-Preview'}
VISION_MODELS = {'deepseek-v4-flash-vision', 'intern-s2', 'kimi-k2.6', 'qwen3.8-27b', 'Agents-A1'}


class InternProvider(QwenProvider):
    default_base = 'https://discovery-api.intern-ai.org.cn/v1'
    default_model = 'deepseek-v4-flash-vision'
    label = '书生 API'

    def _validated(self, data):
        key = data.get('api_key', '')
        if not isinstance(key, str) or not re.fullmatch(r'[\x21-\x7e]{8,4096}', key):
            raise ValueError('请填写有效的书生 API Key')
        model = data.get('model', self.default_model)
        if model not in MODELS:
            raise ValueError('请选择书生平台已收录的模型 ID')
        parsed = urlsplit((data.get('base_url') or self.default_base).strip())
        if (parsed.scheme != 'https' or parsed.hostname != 'discovery-api.intern-ai.org.cn' or
                parsed.username or parsed.password or parsed.port not in (None, 443) or
                parsed.query or parsed.fragment or parsed.path.rstrip('/') not in ('/v1', '/v1/chat/completions')):
            raise ValueError('书生 Base URL 应为 https://discovery-api.intern-ai.org.cn/v1')
        return {'api_key': key, 'model': model, 'base_url': self.default_base}

    def _payload(self, config, messages):
        # Gateway thinking controls have not been verified: preserve platform default.
        return {'model': config['model'], 'messages': messages, 'max_tokens': 4096,
                'stream': True, 'stream_options': {'include_usage': True}}

    def public_config(self):
        config = super().public_config()
        config.update(models=sorted(MODELS), vision_models=sorted(VISION_MODELS), thinking='platform_default')
        return config

    def status(self):
        config = self.public_config()
        return {'status': 'ready' if config['configured'] else 'not_configured',
                'detail': '书生 API 已配置；实际可用性以调用为准，思考使用平台默认' if config['configured'] else
                          config['detail'] or '请在 API 设置填写书生 API Key'}
