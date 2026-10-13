"""No browser automation dependencies in the legacy Windows API distribution."""
class DisabledWebProvider:
    is_api = False
    def status(self):
        return {'status':'unavailable','detail':'此兼容版仅支持千问与书生 API，不调用网页模型'}
    def start_browser(self):
        raise ValueError(self.status()['detail'])
    def generate_with_progress(self, *args, **kwargs):
        raise ValueError(self.status()['detail'])
    def close_saved_response(self, receipt):
        pass

def validate_api_request(data, path=''):
    if path == '/api/jobs':
        raise ValueError('此兼容版请使用 CTRL 助手与 API 模式')
    choices = list(data.get('models') or [])
    for field in ('model','ocr_model','analysis_model','answer_model'):
        if isinstance(data.get(field), str):choices.append(data[field].split(':',1)[0])
    if any(name in ('deepseek','gemini') for name in choices):
        raise ValueError('此兼容版仅支持千问与书生 API，请选择 API 模型')
    if path == '/api/ctrl/start' and not data.get('models'):
        raise ValueError('请先配置并选择千问或书生 API')
