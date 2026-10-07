import {formatErrorReport} from './assistant-core.mjs?v=7864357e60';
import {bindImageCapture} from './capture-input.mjs?v=67d6498f62';
const ids = ['call-mode','ocr-model','analysis-model','answer-model','answer-thinking','route-intern','intern-base','intern-model','intern-key','intern-remember','intern-save','intern-status','connection','connection-detail','open-deepseek','open-gemini','route-deepseek','route-gemini',
  'route-qwen','dispatch-state','assigned-model','qwen-settings','qwen-base','qwen-key','qwen-remember',
  'qwen-save','qwen-status','question','pip-question','pip-start','pip-image-note','pip-remove-image',
  'image-input','auto-ocr','image-box','image-preview','remove-image','start','input-status','offline',
  'ctrl-board','task-tabs','fast-answer','archive-task','float','refresh-card','retry-card','rerun-card','back','stage','progress',
  'progress-fill','progress-label','elapsed','model-progress','route-tabs','answer-tabs','original-section',
  'original','view-image','copy-original','search-section','keywords','copy-keywords','sites','ask-answer',
  'answer','copy-answer','error','copy-error','pip-return','return-card','image-dialog','full-image','close-image'];
const ui = Object.fromEntries(ids.map(id => [id, document.getElementById(id)]));
const local = location.hostname === '127.0.0.1' && location.port === '8771';
const names = {deepseek:'DeepSeek', gemini:'Gemini', qwen:'千问 Flash', intern:'书生 API'};
const defaultQwenBase = 'https://maas.qianwenaiapi.com/compatible-mode/v1';
const boardHome = ui['ctrl-board'].parentElement;
let csrf = '', pip = null, draftImage = null, selectedId = '', tasks = [], nextNumber = 1;
let connectionState = {}, watchRunning = false;
let tabSignature = '';
let imageQueue = Promise.resolve(), renderSignature = '';
const connecting = new Set();
const selected = () => tasks.find(task => task.id === selectedId);
const chosen = prefix => Object.keys(names).filter(name => ui[prefix+'-'+name].checked && (ui['call-mode'].value === 'api' ? ['qwen','intern'].includes(name) : ['deepseek','gemini'].includes(name))); 
const originalOf = task => task?.data?.[task.routeSelected]?.original ||
  Object.values(task?.data || {}).find(value => value.original)?.original || '';
function stage(message) { ui.stage.textContent = message; ui['input-status'].textContent = message; }
function error(message) { ui.error.textContent = message || ''; ui.error.hidden = !message; ui['copy-error'].hidden = !message; }
function persistSelection() { try { sessionStorage.setItem('ctrl-selected-task', selected()?.session || ''); } catch {} }
function controls() {
  ui.start.disabled = !local; ui['pip-start'].disabled = !local;
  const task = selected();
  const answering = task?.jobData && /answer$/.test(task.jobData.kind || '') && task.state === 'running';
  ui['ask-answer'].disabled = !local || !task?.session || !task.assigned || !originalOf(task) || task.answerPending || answering;
  ui['ask-answer'].textContent = answering ? '答案已入队 / 正在回答' : '问答案';
  ui['refresh-card'].disabled = !local || !task?.session;
  const retryable = task && ((!task.session && task.state === 'failed') ||
    Object.values(task.jobData?.results || {}).some(value => value.state === 'failed'));
  ui['retry-card'].disabled = !local || !retryable || task.state === 'running' || task.retryPending;
  ui['rerun-card'].disabled = ui['retry-card'].disabled;
  ui['qwen-save'].disabled = !local || ui['qwen-save'].dataset.saving === 'true';
  ui['archive-task'].disabled = !local || !task || task.state === 'running';
  ui['pip-remove-image'].disabled = !draftImage;
}
async function api(path, body) {
  const response = await fetch('/api/'+path, {method:body ? 'POST':'GET',
    headers:{'Content-Type':'application/json','X-Assistant-Session':csrf},
    body:body ? JSON.stringify(body):undefined, cache:'no-store',
    signal:AbortSignal.timeout(body?.image ? 30000 : 18000)});
  let value;
  try { value = await response.json(); } catch { throw new Error('本机服务未返回有效数据'); }
  if (!response.ok) throw new Error(value.error || '本机请求失败');
  return value;
}
async function copy(value) {
  if (!value) return;
  try { await (pip?.document.hasFocus() ? pip.navigator : navigator).clipboard.writeText(value); }
  catch {
    const doc = pip?.document.hasFocus() ? pip.document : document;
    const box = doc.createElement('textarea'); box.value = value; doc.body.append(box);
    box.select(); if (!doc.execCommand('copy')) { stage('复制失败，请选中文字后按 Ctrl+C。'); box.remove(); return; }
    box.remove();
  }
  stage('已复制，可到检索网站粘贴。');
}
function taskLabel(task) {
  if (task.pending) return '提交中';
  if (task.state === 'failed') return '失败';
  if (task.state === 'completed') return task.hasFailure ? '部分就绪' : '已就绪';
  if (task.ready) return '可检索';
  if (task.hasOriginal) return '原题已出';
  if (task.jobData && Object.values(task.jobData.results || {}).some(item => item.route)) return '可检索';
  if (task.jobData && Object.values(task.jobData.results || {}).some(item => item.original)) return '原题已出';
  return '排队中';
}
function drawTaskTabs() {
  const signature = JSON.stringify(tasks.map(task => [task.id,task.title,task.state,task.ready,task.hasFailure,task.pending,task.id===selectedId]));
  if (signature === tabSignature) return;
  tabSignature = signature;
  const focused = ui['task-tabs'].ownerDocument.activeElement?.dataset?.taskId;
  ui['task-tabs'].replaceChildren(...tasks.map(task => {
    const button = document.createElement('button'); button.type = 'button';
    button.dataset.taskId = task.id;
    button.className = 'task-tab '+(task.state === 'failed' || task.hasFailure ? 'task-failed' : task.state === 'completed' || task.ready ? 'task-ready' : 'task-waiting');
    button.setAttribute('aria-pressed', String(task.id === selectedId));
    const title = (task.title || '截图识别中').replace(/\s+/g,' ').trim();
    button.setAttribute('aria-label', `第 ${task.number} 题，${title}，${taskLabel(task)}`);
    button.title = `第 ${task.number} 题 · ${title} · ${taskLabel(task)}`;
    const index = document.createElement('b'); index.textContent = String(task.number);
    const label = document.createElement('span'); label.textContent = title.slice(0, 10) || '截图识别中';
    const state = document.createElement('i'); state.textContent = task.state === 'failed' || task.hasFailure ? '!' : task.state === 'completed' || task.ready ? '✓' : '·';
    button.append(index, label, state);
    button.addEventListener('click', () => selectTask(task.id));
    return button;
  }));
  if (focused) [...ui['task-tabs'].children].find(button => button.dataset.taskId === focused)?.focus({preventScroll:true});
}
function drawModelTabs(container, task, field, picked, setter) {
  const available = Object.keys(names).filter(name => task.data[name]?.[field]);
  container.hidden = available.length < 2;
  container.replaceChildren(...available.map(name => {
    const button = document.createElement('button'); button.type = 'button';
    button.textContent = names[name]; button.setAttribute('aria-pressed', String(picked === name));
    button.addEventListener('click', () => { setter(name); drawSelected(); }); return button;
  }));
}
function drawProgress(task) {
  const job = task?.jobData;
  if (!job) {
    ui.elapsed.textContent = task ? '准备中' : '已用 0 秒';
    ui['progress-label'].textContent = task ? taskLabel(task) : '等待题目';
    ui.progress.setAttribute('aria-valuenow','0'); ui['progress-fill'].style.width = '0%';
    ui['model-progress'].replaceChildren(); return;
  }
  const ended = job.state !== 'running' ? Math.max(...Object.values(job.results || {}).map(value => value.completed_at || 0)) : 0;
  const seconds = Math.max(0, Math.floor((ended || Date.now()/1000) - (job.started_at || Date.now()/1000)));
  ui.elapsed.textContent = '已用 '+seconds+' 秒';
  const states = Object.values(job.results || {});
  const complete = states.filter(value => value.state === 'completed').length;
  const finished = job.state !== 'running';
  ui.progress.toggleAttribute('data-running', !finished);
  ui.progress.removeAttribute('aria-valuenow');
  ui.progress.setAttribute('aria-valuetext', finished ? '处理结束' : '正在处理，耗时未知');
  ui['progress-fill'].style.width = finished ? '100%' : '35%';
  ui['progress-label'].textContent = job.state === 'running' ? (task.assigned ? names[task.assigned]+' 处理中' : '等待空闲模型') :
    job.state === 'completed' ? '已完成' : '未完成';
  ui['model-progress'].replaceChildren(...Object.entries(job.results || {}).map(([name,value]) => {
    const badge = document.createElement('span'); badge.className = value.state === 'failed' ? 'failed' : '';
    badge.textContent = `${names[name] || '自动派单'} · ${value.state === 'completed' ? '完成' : value.state === 'failed' ? '失败' : value.stage || '排队中'}`;
    return badge;
  }));
}
function drawSelected() {
  const task = selected(); drawTaskTabs(); drawProgress(task);
  ui['assigned-model'].textContent = task?.assigned ? '识题：'+names[task.assigned] : '自动分配给空闲模型';
  ui['answer-model'].value = task?.answerChoice || '';
  ui['answer-thinking'].checked = !!task?.answerThinking;
  const signature = JSON.stringify([task?.id,task?.data,task?.jobData?.results,task?.state,task?.error,task?.hadImage]);
  if (signature === renderSignature) { controls(); return; }
  renderSignature = signature;
  if (!task) {
    for (const id of ['original-section','search-section','route-tabs','answer-tabs','answer','copy-answer']) ui[id].hidden = true;
    stage('连续粘贴题目，点击上方窄标签切换。'); error(''); controls(); return;
  }
  const data = task.data || {}, source = data[task.routeSelected] || {};
  const original = source.original || originalOf(task) || (!task.session ? task.inputText : ''), route = source.route;
  ui.original.textContent = original || '截图待识别'; ui['original-section'].hidden = !original && !task.hadImage;
  ui['view-image'].hidden = !task.hadImage;
  ui['search-section'].hidden = !route;
  ui.keywords.replaceChildren(...(route?.keywords || []).map(word => {
    const button = document.createElement('button'); button.type = 'button'; button.textContent = word;
    button.title = '点击复制'; button.addEventListener('click', () => copy(word)); return button;
  }));
  ui.sites.replaceChildren(...(route?.sites || []).map(site => {
    const card = document.createElement('div'); card.className = 'site';
    const top = document.createElement('div'); top.className = 'site-top';
    const link = document.createElement('a'); link.href = site.url; link.target = '_blank';
    link.rel = 'noopener noreferrer'; link.textContent = site.name+' ↗'; top.append(link);
    if (site.unlisted) { const tag = document.createElement('span'); tag.className = 'unlisted'; tag.textContent = '未收录'; top.append(tag); }
    card.append(top);
    if (site.why) { const why = document.createElement('p'); why.textContent = site.why; card.append(why); }
    if (site.query) { const query = document.createElement('div'); query.className = 'query'; query.textContent = site.query;
      const button = document.createElement('button'); button.type = 'button'; button.textContent = '复制检索词';
      button.addEventListener('click', () => copy(site.query)); card.append(query, button); }
    return card;
  }));
  const answer = data[task.answerSelected]?.answer || '';
  ui.answer.textContent = answer; ui.answer.hidden = !answer; ui['copy-answer'].hidden = !answer;
  drawModelTabs(ui['route-tabs'],task,'route',task.routeSelected,name => task.routeSelected = name);
  drawModelTabs(ui['answer-tabs'],task,'answer',task.answerSelected,name => task.answerSelected = name);
  const job = task.jobData;
  if (job?.state === 'running') stage(Object.entries(job.results || {}).map(([name,item]) => `${names[name] || '自动派单'}：${item.stage || '处理中'}`).join('；'));
  else if (task.state === 'failed') stage('当前题未完成；可以点击重试。');
  else stage(task.state === 'completed' ? '当前题已就绪，可复制或打开检索网站。' : '当前题排队处理中；可以继续粘贴下一题。');
  const failures = Object.entries(job?.results || {}).filter(([,value]) => value.state === 'failed');
  error(task.error || failures.map(([name,value]) => `${names[name]}：${value.error || '请检查原窗口'}`).join('\n'));
  controls();
}
async function loadTask(task) {
  if (!task?.session) return;
  try {
    const session = await api('ctrl/session?id='+encodeURIComponent(task.session));
    task.data = session.models; task.title = (session.original || task.title || '截图识别中').replace(/\s+/g,' ').slice(0,45);
    task.state = session.state; task.job = session.job; task.error = '';
    task.assigned = session.assigned;
    task.jobData = {id:session.job,kind:session.kind,state:session.state,results:session.activity,started_at:session.started_at};
    if (!task.data[task.routeSelected]?.route) task.routeSelected = Object.keys(names).find(name => task.data[name]?.route) || session.assigned || '';
    task.answerSelected = Object.keys(session.activity || {}).find(name => session.activity[name].answer) || task.answerSelected;
    task.routeSelected ||= Object.keys(names).find(name => task.data[name]?.route) || '';
    task.answerSelected ||= Object.keys(names).find(name => task.data[name]?.answer) || '';
    if (task.id === selectedId) drawSelected();
  } catch (e) { task.error = e.message; if (task.id === selectedId) drawSelected(); }
}
async function selectTask(id) {
  const view = ui['ctrl-board'].ownerDocument.defaultView;
  if (selected()) selected().scrollY = view.scrollY;
  selectedId = id; persistSelection(); drawSelected();
  const task = selected(); if (task?.session) await loadTask(task);
  if (selectedId === id) view.scrollTo({top: task?.scrollY || 0, behavior:'instant'});
}
function clearDraft() {
  draftImage = null; ui.question.value = ''; ui['pip-question'].value = '';
  ui['image-input'].value = ''; ui['image-preview'].removeAttribute('src'); ui['image-box'].hidden = true;
  ui['pip-image-note'].textContent = ''; ui['pip-remove-image'].hidden = true;
}
async function submitCapture(text, image) {
  if (!local || (!text.trim() && !image)) { error('请粘贴原题文字或截图。'); return; }
  const models = chosen('route'); if (!models.length) { error('至少启用一个自动派单模型。'); return; }
  const task = {id:'pending-'+crypto.randomUUID(),number:nextNumber++,session:'',job:'',image,
    inputText:text,models,ocrModel:ui['ocr-model'].value,analysisModel:ui['analysis-model'].value,fastAnswer:ui['fast-answer'].checked,intakeAt:Date.now(),
    hadImage:!!image,title:text.trim().replace(/\s+/g,' ').slice(0,45) || '截图识别中',
    state:'running',pending:true,data:{deepseek:{},gemini:{}},routeSelected:'',answerSelected:'',error:''};
  tasks.push(task); if (!selectedId) selectedId = task.id;
  clearDraft(); drawSelected(); ui['input-status'].textContent = `第 ${task.number} 题已收下，可继续粘贴下一题。`;
  try {
    const started = await api('ctrl/start',{text,image,models,fast_answer:task.fastAnswer,client_id:task.id,ocr_model:task.ocrModel,analysis_model:task.analysisModel});
    const duplicate = tasks.find(value => value !== task && value.session === started.session);
    if (duplicate) tasks.splice(tasks.indexOf(duplicate),1);
    task.session = started.session; task.job = started.id; task.pending = false;
    persistSelection(); drawTaskTabs();
  } catch (e) { if (task.session) { await loadTask(task); return; }
    task.pending = false; task.state = 'failed'; task.error = e.message;
    if (task.id === selectedId) drawSelected(); else drawTaskTabs(); }
}
async function loadImage(file) {
  if (!file || !['image/png','image/jpeg'].includes(file.type) || file.size > 5*1024*1024) {
    error('只支持不超过 5 MB 的 PNG 或 JPEG 截图。'); return;
  }
  const value = await new Promise((resolve,reject) => { const reader = new FileReader();
    reader.onload = () => resolve(reader.result); reader.onerror = reject; reader.readAsDataURL(file); });
  if (ui['auto-ocr'].checked && local) { await submitCapture('',value); return; }
  draftImage = value; ui['image-preview'].src = value; ui['image-box'].hidden = false;
  ui['pip-image-note'].textContent = '截图待提交'; ui['pip-remove-image'].hidden = false;
  ui['input-status'].textContent = '截图已载入，按 Enter 提交新题。'; controls();
}
async function watch() {
  if (watchRunning || !local) return; watchRunning = true;
  while (watchRunning) {
    try {
      const listing = await api('ctrl/tasks');
      drawDispatch(listing.dispatch);
      for (const entry of listing.tasks) {
        let task = tasks.find(value => value.session === entry.session || value.id === entry.client_id);
        if (!task) { task = {id:entry.session,number:nextNumber++,session:entry.session,job:entry.job,
          image:null,hadImage:entry.had_image,title:entry.title,state:entry.state,
          data:{deepseek:{},gemini:{}},routeSelected:'',answerSelected:'',error:''}; tasks.push(task); }
        task.session = entry.session; task.pending = false;
        task.title = entry.title || task.title; task.state = entry.state; task.job = entry.job;
        task.ready = entry.ready; task.hasOriginal = entry.has_original;
        task.hasFailure = entry.has_failure;
        task.assigned = entry.assigned;
      }
      const serverIds = new Set(listing.tasks.map(entry => entry.session));
      tasks = tasks.filter(task => !task.session || serverIds.has(task.session) ||
        Date.now() - (task.intakeAt || 0) < 5000);
      if (selectedId && !selected()) { selectedId = tasks.at(-1)?.id || ''; persistSelection(); drawSelected(); }
      const active = selected();
      if (active?.job && !active.pending && (active.state === 'running' ||
          active.jobData?.id !== active.job || active.jobData?.state !== active.state))
        await loadTask(active);
      drawTaskTabs();
    } catch (e) { if (selected()) { selected().error = e.message; drawSelected(); } }
    await new Promise(resolve => setTimeout(resolve,750));
  }
}
ui.start.addEventListener('click', () => submitCapture(ui.question.value.trim(),draftImage));
ui['pip-start'].addEventListener('click', () => { ui['pip-question'].blur(); ui.start.click(); });
ui.question.addEventListener('input', () => ui['pip-question'].value = ui.question.value);
ui['pip-question'].addEventListener('input', () => ui.question.value = ui['pip-question'].value);
for (const box of [ui.question,ui['pip-question']]) {
  box.addEventListener('keydown', event => { if (event.key === 'Enter' && !event.isComposing && !event.shiftKey &&
    !event.ctrlKey && !event.altKey && !event.metaKey) { event.preventDefault(); ui.start.click(); } });
}
function enqueueImage(file) {
  imageQueue = imageQueue.then(() => loadImage(file)).catch(e => error('截图读取失败：'+e.message));
  return imageQueue;
}
bindImageCapture(document, enqueueImage, e => error(e.message));
ui['image-input'].addEventListener('change',event => { if (event.target.files[0]) enqueueImage(event.target.files[0]); });
ui['remove-image'].addEventListener('click',clearDraft);
ui['pip-remove-image'].addEventListener('click',clearDraft);
ui['auto-ocr'].checked = localStorage.getItem('ctrl-auto-ocr') !== 'false';
ui['auto-ocr'].addEventListener('change',() => localStorage.setItem('ctrl-auto-ocr',String(ui['auto-ocr'].checked)));
ui['fast-answer'].checked = localStorage.getItem('ctrl-auto-answer-v3') === 'true';
ui['fast-answer'].addEventListener('change',() => localStorage.setItem('ctrl-auto-answer-v3',String(ui['fast-answer'].checked)));
ui['answer-model'].addEventListener('change', () => { if (selected()) selected().answerChoice = ui['answer-model'].value; });
ui['answer-thinking'].addEventListener('change', () => { if (selected()) selected().answerThinking = ui['answer-thinking'].checked; });
ui['ask-answer'].addEventListener('click',async () => { const task = selected(); if (!task?.session || !originalOf(task)) return;
  task.answerPending = true; controls(); task.error = '';
  try { const started = await api('ctrl/answer',{session:task.session,model:ui['answer-model'].value,thinking:ui['answer-thinking'].checked}); task.job = started.id;
    task.state = 'running'; await loadTask(task); }
  catch (e) { task.error = e.message; drawSelected(); }
  finally { task.answerPending = false; controls(); }
});
ui['refresh-card'].addEventListener('click',() => loadTask(selected()));
ui['archive-task'].addEventListener('click',async () => {
  const task = selected(); if (!task || task.state === 'running') return;
  try { if (task.session) await api('ctrl/archive',{session:task.session});
    if (task.image?.startsWith('blob:')) URL.revokeObjectURL(task.image);
    const index = tasks.indexOf(task); tasks.splice(index,1);
    selectedId = tasks[Math.min(index,tasks.length-1)]?.id || ''; persistSelection();
    drawSelected(); if (selected()) await loadTask(selected()); }
  catch(e) { error(e.message); }
});
async function retrySelected(mode='read_first') { const task = selected(); if (!task || task.retryPending) return;
  task.retryPending = true; controls(); task.error = '';
  try { const result = task.session ? await api('ctrl/retry',{job:task.job,mode}) :
      await api('ctrl/start',{text:task.inputText,image:task.image,models:task.models,
        fast_answer:task.fastAnswer,client_id:task.id});
    task.session = result.session; task.job = result.id;
    task.state = 'running'; await loadTask(task); }
  catch (e) { task.error = e.message; drawSelected(); }
  finally { task.retryPending = false; controls(); }
}
ui['retry-card'].addEventListener('click',() => retrySelected());
ui['rerun-card'].addEventListener('click',() => { ui['rerun-card'].closest('details').open=false; retrySelected('restart'); });
ui['copy-original'].addEventListener('click',() => copy(originalOf(selected())));
ui['copy-keywords'].addEventListener('click',() => copy((selected()?.data?.[selected()?.routeSelected]?.route?.keywords || []).join(' ')));
ui['copy-answer'].addEventListener('click',() => copy(selected()?.data?.[selected()?.answerSelected]?.answer || ''));
ui['copy-error'].addEventListener('click',() => {
  const task = selected();
  copy(formatErrorReport('route',{time:new Date().toISOString(),models:task?.models || Object.keys(task?.jobData?.results || {}),
    jobId:task?.job,hadImage:task?.hadImage,message:ui.error.textContent,
    errors:Object.fromEntries(Object.entries(task?.jobData?.results || {}).filter(([,value]) => value.error)
      .map(([name,value]) => [name,value.error]))}));
});
ui['view-image'].addEventListener('click',async () => { const task = selected(); if (!task?.hadImage) return;
  let source = task.image;
  if (!source) { try { const response = await fetch('/api/ctrl/image?id='+encodeURIComponent(task.session),
    {headers:{'X-Assistant-Session':csrf},cache:'no-store'}); if (!response.ok) throw Error('原截图已过期');
    source = URL.createObjectURL(await response.blob()); task.image = source; } catch(e) { error(e.message); return; } }
  if (pip) { const dialog = pip.document.createElement('dialog'), close = pip.document.createElement('button'),
    img = pip.document.createElement('img'); dialog.id='image-dialog'; img.id='full-image'; close.textContent='关闭 ×';
    img.src=source; img.alt='题目原图'; close.addEventListener('click',() => dialog.close());
    dialog.addEventListener('close',() => dialog.remove()); dialog.append(close,img); pip.document.body.append(dialog); dialog.showModal(); }
  else { ui['full-image'].src = source; ui['image-dialog'].showModal(); }
});
ui['close-image'].addEventListener('click',() => ui['image-dialog'].close());
ui.back.addEventListener('click',() => { pip?.close(); window.focus(); ui.question.scrollIntoView({behavior:'smooth',block:'center'}); });
ui['return-card'].addEventListener('click',() => pip?.close());
ui.float.addEventListener('click',async () => { if (pip) { pip.close(); return; }
  if (!window.documentPictureInPicture) { error('此浏览器不支持置顶小窗。'); return; }
  try { pip = await documentPictureInPicture.requestWindow({width:480,height:700});
    try {
      const sheet = new pip.CSSStyleSheet();
      sheet.replaceSync([...document.styleSheets].flatMap(sheet => [...sheet.cssRules].map(rule => rule.cssText)).join('\n'));
      pip.document.adoptedStyleSheets = [sheet];
    } catch {
      const style = pip.document.createElement('link'); style.rel='stylesheet';
      style.href=document.querySelector('link[rel=stylesheet]').href; pip.document.head.append(style);
    }
    pip.document.title='CTRL 检索卡片'; pip.document.body.className='pip-body';
    bindImageCapture(pip.document, enqueueImage, e => error(e.message));
    pip.document.body.append(ui['ctrl-board']); ui['pip-return'].hidden=false;
    ui.float.textContent='收回小窗';
    pip.addEventListener('pagehide',() => { boardHome.prepend(ui['ctrl-board']); pip=null;
      ui['pip-return'].hidden=true; ui.float.textContent='置顶小窗 ↗'; }); }
  catch { pip=null; error('置顶小窗无法打开，请并排使用浏览器窗口。'); }
});
async function refreshConnections() { const statuses = await Promise.all(Object.keys(names).filter(name =>
  ['qwen','intern'].includes(name) === (ui['call-mode'].value === 'api')).map(async name => {
  try { return {name,...await api('status?model='+name)}; } catch(e) { return {name,status:'error',detail:e.message}; }
})); Object.assign(connectionState, Object.fromEntries(statuses.map(value => [value.name,value.status])));
  ui.connection.textContent = statuses.map(value => `${names[value.name]}${value.status === 'ready' ? (['qwen','intern'].includes(value.name) ? ' 已配置' : ' 已连接') : value.status === 'not_configured' ? ' 未配置' : value.status === 'login_required' ? ' 需登录' : ' 未连接'}`).join(' · ');
  ui['connection-detail'].textContent = statuses.map(value => value.detail || '').filter(Boolean).join('；');
  return connectionState; }
function drawDispatch(snapshot) {
  if (!snapshot) return;
  ui['dispatch-state'].textContent = Object.entries(snapshot.models || {}).filter(([name]) => chosen('route').includes(name))
    .map(([name,value]) => `${names[name]} ${value.ready ? (value.active ? value.active+' 请求运行' : '空闲') : '需配置/连接'}`).join(' · ')+
    ` · API ${snapshot.api_active || 0}/${snapshot.api_limit || 6}`+(snapshot.waiting ? ` · 排队 ${snapshot.waiting} 项` : '');
}
function setQwenConfig(config) {
  ui['qwen-base'].value = config.base_url || defaultQwenBase;
  ui['qwen-remember'].checked = !!config.remembered;
  ui['route-qwen'].disabled = !config.configured;
  ui['route-qwen'].checked = !!config.configured;
  ui['qwen-status'].textContent = config.detail || (config.configured ?
    '已配置 qwen3.8-flash；可加入自动派单。实际可用性以调用结果为准。' : '未配置，填写后才能启用千问。');
}
async function loadQwenConfig() {
  try { setQwenConfig(await api('ctrl/qwen-config')); }
  catch (e) { ui['qwen-status'].textContent = e.message; ui['route-qwen'].disabled = true; }
}
ui['qwen-save'].addEventListener('click', async () => {
  ui['qwen-save'].dataset.saving = 'true'; ui['qwen-save'].disabled = true;
  try {
    const base = (ui['qwen-base'].value.trim() || defaultQwenBase).replace(/\/chat\/completions\/?$/, '');
    const config = await api('ctrl/qwen-config', {model:'qwen3.8-flash', base_url:base,
      api_key:ui['qwen-key'].value.trim(), remember:ui['qwen-remember'].checked});
    ui['qwen-key'].value = ''; setQwenConfig(config); ui['route-qwen'].checked = true;
    await refreshConnections();
  } catch (e) { ui['qwen-status'].textContent = e.message; }
  finally { ui['qwen-save'].dataset.saving = 'false'; controls(); }
});
async function connectModel(name) { if (!local || !csrf || connecting.has(name)) return;
  connecting.add(name); ui['open-'+name].disabled=true; ui['connection-detail'].textContent=`正在连接 ${names[name]}…`;
  try { const result=await api('browser/open',{model:name});
    ui['connection-detail'].textContent=(result.detail || `${names[name]} 窗口已打开`)+'；如需登录，请在模型窗口完成后重连。';
    setTimeout(() => refreshConnections().catch(()=>{}),2500); }
  catch(e) { ui['connection-detail'].textContent=`${names[name]} 连接失败：${e.message}，可重试。`; }
  finally { connecting.delete(name); ui['open-'+name].disabled=false; }
}
for (const name of ['deepseek','gemini']) { ui['open-'+name].addEventListener('click',() => connectModel(name));
  ui['route-'+name].addEventListener('change',() => { if (ui['route-'+name].checked && connectionState[name] !== 'ready') connectModel(name); }); }
async function init() { if (!local) { ui.offline.hidden=false; ui.connection.textContent='静态预览'; controls(); return; }
  try { const response=await fetch('/api/session',{cache:'no-store'}); if (!response.ok) throw Error('本机服务不可用');
    csrf=(await response.json()).session;
    const listing=await api('ctrl/tasks'); const saved=sessionStorage.getItem('ctrl-selected-task');
    for (const entry of listing.tasks) { tasks.push({id:entry.session,number:nextNumber++,session:entry.session,
      job:entry.job,image:null,hadImage:entry.had_image,title:entry.title,state:entry.state,
      data:{deepseek:{},gemini:{}},routeSelected:'',answerSelected:'',error:''}); }
    selectedId=tasks.find(task => task.session === saved)?.id || tasks.at(-1)?.id || '';
    if (selected()) await loadTask(selected()); drawSelected(); watch();
    await loadQwenConfig();
    try { setInternConfig(await api('ctrl/intern-config')); } catch(e) { ui['intern-status'].textContent=e.message; }
    refreshConnections().then(state => { for (const name of chosen('route')) if (['deepseek','gemini'].includes(name) && state[name] !== 'ready') connectModel(name); }).catch(()=>{});
  } catch(e) { ui.connection.textContent='本机服务未连接'; ui['connection-detail'].textContent=e.message;
    ui.offline.hidden=false; }
  controls(); }
init();

function updateMode() {
  localStorage.setItem('ctrl-call-mode', ui['call-mode'].value);
  for (const name of Object.keys(names)) {
    const isApi = ['qwen','intern'].includes(name);
    ui['route-'+name].closest('label').hidden = isApi !== (ui['call-mode'].value === 'api');
  }
  document.querySelector('.model-tools').hidden = ui['call-mode'].value === 'api';
  if (ui['call-mode'].value === 'web' && !chosen('route').length) ui['route-deepseek'].checked = true;
}
ui['call-mode'].value = localStorage.getItem('ctrl-call-mode') || 'api';
ui['call-mode'].addEventListener('change', () => {
  ui['ocr-model'].value = ''; ui['analysis-model'].value = ''; updateMode();
  if (local) refreshConnections().then(state => {
    for (const name of chosen('route')) if (['deepseek','gemini'].includes(name) && state[name] !== 'ready') connectModel(name);
  }).catch(e => error(e.message));
});
updateMode();
for (const stage of ['ocr','analysis','answer']) ui[stage+'-model'].addEventListener('change', () => {
  const name = ui[stage+'-model'].value;
  if (['deepseek','gemini'].includes(name) && connectionState[name] !== 'ready') connectModel(name);
});
function setInternConfig(config) {
  ui['intern-base'].value = config.base_url;
  ui['intern-model'].replaceChildren(...(config.models || []).map(name => {
    const option = document.createElement('option'); option.value = option.textContent = name; return option;
  }));
  ui['intern-model'].value = config.model;
  for (const stage of ['ocr','analysis','answer']) {
    const select = ui[stage+'-model'];
    for (const old of [...select.options]) if (old.value.startsWith('intern:')) old.remove();
    for (const model of config.models || []) {
      if (stage === 'ocr' && !(config.vision_models || []).includes(model)) continue;
      const option = document.createElement('option'); option.value = 'intern:'+model;
      option.textContent = '书生 · '+model; select.append(option);
    }
  }
  ui['intern-remember'].checked = !!config.remembered;
  ui['route-intern'].disabled = !config.configured;
  ui['intern-status'].textContent = config.configured ? '已配置；思考使用平台默认。实际可用性以调用结果为准。' : '未配置，请填写 Key。';
}
ui['intern-save'].addEventListener('click', async () => {
  ui['intern-save'].disabled = true;
  try {
    setInternConfig(await api('ctrl/intern-config', {base_url:ui['intern-base'].value,
      model:ui['intern-model'].value,api_key:ui['intern-key'].value.trim(),remember:ui['intern-remember'].checked}));
    ui['intern-key'].value = ''; ui['route-intern'].checked = true;
    await refreshConnections();
  } catch(e) { ui['intern-status'].textContent = e.message; }
  finally { ui['intern-save'].disabled = false; }
});

