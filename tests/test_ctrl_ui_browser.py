"""Browser smoke checks with mocked AI endpoints; never sends a real question."""
import json
import mimetypes
from pathlib import Path
import unittest
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]


class CtrlBrowserTests(unittest.TestCase):
    def test_api_modes_and_independent_answer_in_compact_window(self):
        with sync_playwright() as p:
            browser = p.chromium.launch(channel='msedge', headless=True)
            page = browser.new_page(viewport={'width':480,'height':850})
            errors, tasks, sessions, answers, reviews, retries = [], [], {}, [], [], []
            page.on('pageerror', lambda error: errors.append(str(error)))
            def static(route):
                file = ROOT/'dist'/urlsplit(route.request.url).path.lstrip('/')
                if not file.is_file() or not file.resolve().is_relative_to((ROOT/'dist').resolve()):
                    route.fulfill(status=404)
                    return
                mime = 'text/javascript' if file.suffix == '.mjs' else mimetypes.guess_type(file)[0]
                route.fulfill(status=200,body=file.read_bytes(),content_type=mime or 'application/octet-stream',
                              headers={'Content-Security-Policy': "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: blob:; connect-src 'self'"})
            page.route('http://127.0.0.1:8771/**', static)
            def mock(route):
                path = route.request.url.split('/api/')[1]
                body = route.request.post_data_json if route.request.method == 'POST' else {}
                if path == 'session': value = {'session':'mock-session'}
                elif path == 'ctrl/qwen-config': value = {'configured':True,'remembered':True,'base_url':'https://maas.qianwenaiapi.com/compatible-mode/v1','model':'qwen3.8-flash'}
                elif path == 'ctrl/intern-config': value = {'configured':True,'remembered':False,'base_url':'https://discovery-api.intern-ai.org.cn/v1','model':'deepseek-v4-flash-vision','models':['deepseek-v4-flash-vision','deepseek-v4-flash-0731'],'vision_models':['deepseek-v4-flash-vision']}
                elif path.startswith('status'): value = {'status':'ready'}
                elif path == 'ctrl/tasks': value = {'tasks':tasks,'dispatch':{'models':{'qwen':{'active':0,'ready':True}},'api_active':0,'api_limit':6,'waiting':0}}
                elif path == 'ctrl/start':
                    key = 's'+str(len(tasks)); job = 'j'+key
                    tasks.append({'session':key,'client_id':body['client_id'],'job':job,'title':body['text'],'state':'completed','assigned':'qwen','ready':True,'has_original':True})
                    sessions[key] = {'original':body['text'],'state':'completed','assigned':'qwen','job':job,'kind':'ctrl-start','models':{'qwen':{'original':body['text'],'route':{'keywords':['检索词'],'sites':[]},'answer':''},'intern':{'original':'','route':None,'answer':''}},'activity':{'qwen':{'state':'completed','stage':'原题和建议已返回'}}}
                    value = {'id':job,'session':key}
                elif path.startswith('ctrl/session'): value = sessions[path.split('id=')[1]]
                elif path == 'ctrl/review':
                    reviews.append(body)
                    if body['stage'] == 'answer':
                        session = sessions[body['session']]
                        session['versions']['answer'].append({'id':'review-answer-new','answer':'复核答案 C','model':'intern','requested_model':'deepseek-v4-flash-0731','actual_model':'dsv4-flash-vision','source_job':'answer-review-job','based_on':'base'})
                        session['job']='answer-review-job'; session['kind']='ctrl-review-answer'
                        session['activity']['intern']={'state':'completed','stage':'答案复核完成'}
                        route.fulfill(status=200,content_type='application/json',body=json.dumps({'id':'answer-review-job','session':body['session']}))
                        return
                    session = sessions[body['session']]
                    session['versions'] = {'ocr':[{'id':'base','text':session['original'],'model':'qwen'}],
                        'analysis':[{'id':'base-route','route':session['models']['qwen']['route'],'model':'qwen','based_on':'base'},
                                    {'id':'review-route','route':{'keywords':['复核检索词'],'sites':[]},'model':'intern','requested_model':'deepseek-v4-flash-0731','actual_model':'dsv4-flash-vision','source_job':'review-job','based_on':'base'}],
                        'answer':[{'id':'base-answer','answer':'答案 B，待核验','model':'intern','requested_model':'deepseek-v4-flash-0731','actual_model':'dsv4-flash-vision','source_job':'review-job','based_on':'base'}]}
                    session['job']='review-job'; session['kind']='ctrl-review-analysis'
                    session['activity']['intern']={'state':'completed','stage':'复核完成'}
                    value={'id':'review-job','session':body['session']}
                elif path == 'ctrl/archive':
                    tasks[:] = [t for t in tasks if t['session'] != body['session']]
                    sessions.pop(body['session'],None); value={'archived':True}
                elif path == 'ctrl/retry':
                    retries.append(body); value={'id':'review-job','session':tasks[0]['session']}
                elif path == 'ctrl/answer':
                    answers.append(body)
                    value = {'id':'answer-job','session':body['session']}
                    session = sessions[body['session']]
                    session['job'] = 'answer-job'; session['kind'] = 'ctrl-answer'
                    session['models']['intern']['answer'] = '答案 B，待核验'
                    session['activity']['intern'] = {'state':'completed','answer':'答案 B，待核验'}
                else: value = {}
                route.fulfill(status=200,content_type='application/json',body=json.dumps(value))
            page.route('**/api/**', mock)
            page.goto('http://127.0.0.1:8771/ctrl-assistant.html')
            expect(page.locator('#route-qwen')).to_be_enabled()
            self.assertEqual(page.locator('#call-mode').input_value(), 'api')
            expect(page.locator('#answer-section')).to_be_hidden()
            expect(page.locator('.stage-tools:visible')).to_have_count(0)
            expect(page.locator('#refresh-card')).to_be_disabled()
            out = ROOT/'output/playwright'
            out.mkdir(parents=True,exist_ok=True)
            page.screenshot(path=str(out/'ctrl-empty-480.png'),full_page=True)
            page.locator('#question').fill('哪一项不正确？A甲 B乙')
            page.locator('#start').click()
            page.locator('#original-section').wait_for(state='visible')
            expect(page.locator('#version-answer')).to_be_hidden()
            expect(page.locator('#review-answer')).to_be_hidden()
            page.locator('#answer-model').select_option('intern:deepseek-v4-flash-0731')
            page.locator('#ask-answer').click()
            expect(page.locator('#answer')).to_contain_text('答案 B')
            self.assertEqual(answers[0]['model'], 'intern:deepseek-v4-flash-0731')
            page.locator('#review-analysis').click()
            self.assertEqual(page.locator('#review-model').input_value(),'intern')
            page.locator('#review-model').select_option('intern:deepseek-v4-flash-0731')
            page.locator('#submit-review').click()
            expect(page.locator('#version-analysis option')).to_have_count(2)
            self.assertLessEqual(page.locator('#version-analysis').bounding_box()['width'],170)
            expect(page.locator('#review-analysis')).to_have_text('复核')
            expect(page.locator('#keywords')).to_have_text('复核检索词')
            page.locator('#version-analysis').select_option('base-route')
            expect(page.locator('#keywords')).to_have_text('检索词')
            page.locator('#version-analysis').select_option('review-route')
            expect(page.locator('#keywords')).to_have_text('复核检索词')
            self.assertEqual(reviews[0]['stage'],'analysis')
            expect(page.locator('#version-analysis')).to_contain_text('书生 API')
            page.locator('#toggle-marks').click()
            page.get_by_role('button',name='标记选项 A',exact=True).click()
            page.get_by_role('button',name='标记选项 B',exact=True).click()
            expect(page.locator('#toggle-marks')).to_have_text('已选 AB')
            page.locator('#review-answer').click()
            self.assertEqual(page.locator('#review-model').input_value(),'intern')
            page.locator('#submit-review').click()
            expect(page.locator('#answer')).to_have_text('复核答案 C')
            expect(page.locator('#answer-source')).to_contain_text('书生 API · deepseek-v4-flash-0731')
            expect(page.locator('#toggle-marks')).to_have_text('已选 AB')
            self.assertFalse(page.locator('#call-mode').is_visible())
            page.locator('#settings-open').click()
            page.locator('#call-mode').select_option('web')
            self.assertTrue(page.locator('#route-deepseek').is_visible())
            self.assertFalse(page.locator('#route-qwen').is_visible())
            page.locator('#call-mode').select_option('api')
            page.locator('#close-settings').click()
            # A failed review makes both direct shortcuts available without opening the menu.
            sessions[tasks[0]['session']]['activity']['intern']={'state':'failed','error':'读取失败'}
            sessions[tasks[0]['session']]['state']='failed'
            page.locator('#refresh-card').click()
            expect(page.locator('#retry-card')).to_be_enabled()
            expect(page.locator('#refresh-feedback')).to_have_text('已同步后台结果')
            self.assertEqual(len(answers),1)
            self.assertEqual(len(reviews),2)
            page.locator('#retry-card').click(modifiers=['Shift'])
            expect(page.locator('#retry-card')).to_be_enabled()
            page.keyboard.press('Alt+Shift+Enter')
            expect(page.locator('#retry-card')).to_be_enabled()
            self.assertEqual([x['mode'] for x in retries], ['restart','restart'])
            for width in (480,360):
                page.set_viewport_size({'width':width,'height':850})
                self.assertTrue(page.evaluate('() => document.documentElement.scrollWidth <= innerWidth'), f'overflow at {width}')
            out = ROOT/'output/playwright'
            out.mkdir(parents=True,exist_ok=True)
            page.screenshot(path=str(out/'ctrl-api-360.png'),full_page=True)
            with page.context.expect_page() as new_window:
                page.locator('#float').click()
            small = new_window.value
            small.locator('#pip-question').wait_for(state='visible')
            for width in (480,360):
                small.set_viewport_size({'width':width,'height':700})
                self.assertTrue(small.evaluate('() => document.documentElement.scrollWidth <= innerWidth'), f'PiP overflow at {width}')
            small.locator('#pip-question').fill('小窗第二题')
            small.locator('#pip-start').click()
            expect(small.locator('#task-tabs button')).to_have_count(2)
            expect(small.locator('#answer-model')).to_be_visible()
            small.locator('#task-tabs button').nth(1).click()
            expect(small.locator('#toggle-marks')).to_have_text('标记')
            small.locator('#toggle-marks').click()
            small.get_by_role('button',name='标记选项 C',exact=True).click()
            small.locator('#task-tabs button').nth(0).click()
            expect(small.locator('#toggle-marks')).to_have_text('已选 AB')
            small.locator('#task-tabs button').nth(1).click()
            expect(small.locator('#toggle-marks')).to_have_text('已选 C')
            small.locator('#pip-question').fill('第三题 A甲 B乙 C丙 D丁')
            small.locator('#pip-start').click()
            expect(small.locator('#task-tabs button')).to_have_count(3)
            small.locator('#task-tabs button').nth(2).click()
            # Preserve an in-flight left task, archive the other, leave current selected.
            tasks[1]['state']='running'; sessions[tasks[1]['session']]['state']='running'
            expect(small.locator('#task-tabs button').nth(1)).to_have_attribute('aria-label','第 2 题，小窗第二题，可检索')
            small.locator('#archive-left').click()
            expect(small.locator('#task-tabs button')).to_have_count(2)
            expect(small.locator('#task-tabs button').nth(1)).to_have_attribute('aria-pressed','true')
            expect(small.locator('#stage')).to_contain_text('保留 1 道处理中的题目')
            for width in (480,360):
                small.set_viewport_size({'width':width,'height':700})
                self.assertTrue(small.evaluate('() => document.documentElement.scrollWidth <= innerWidth'))
            small.screenshot(path=str(out/'ctrl-api-pip-360.png'),full_page=True)
            small.close()
            self.assertEqual(errors, [])
            browser.close()


if __name__ == '__main__':
    unittest.main()
