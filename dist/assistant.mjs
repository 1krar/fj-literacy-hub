import {catalogFromData,makePrompt,parsePlan,stepText,arithmeticPlan,consumeModelResults,makeAnswerPrompt,consumeAnswerResults,answerWarnings,formatErrorReport} from './assistant-core.mjs?v=7864357e60';
const local=location.hostname==='127.0.0.1'&&location.port==='8771',sites=catalogFromData(window.LITERACY_DATA,window.BOOKMARK_DATA);
let plan=null,active=0,image=null,originalImage=null,csrf='',rules='',busy=false,pipWindow=null,toastTimer,modelPlans={},modelErrors={},chosenModel='',pendingModels=[],modelStages={};
const memory={get(k,f=null){try{return JSON.parse(sessionStorage.getItem('literacy-assistant-'+k))??f;}catch{return f;}},set(k,v){try{sessionStorage.setItem('literacy-assistant-'+k,JSON.stringify(v));}catch{}},remove(k){try{sessionStorage.removeItem('literacy-assistant-'+k);}catch{}}};
let statusRevision=0,connectionRetryTimer,autoConnectDeadline=0;const autoOpenedModels=new Set();
let faultRecords=memory.get('fault-records',{}),routeRequest=memory.get('route-request'),routeImage=null;
let answerState={question:'',mode:'',answers:{},errors:{},chosen:'',models:[],status:''};
const done=new Set(),$=id=>document.getElementById(id)||pipWindow?.document.getElementById(id),node=(tag,cls,text)=>{const n=document.createElement(tag);if(cls)n.className=cls;if(text!==undefined)n.textContent=text;return n;};
function toast(message){$('toast').textContent=message;$('toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('toast').hidden=true,3200);if(pipWindow){$('route-notice').textContent=message;}}
async function copy(text){let ok=false;try{const nav=pipWindow?.document.hasFocus()?pipWindow.navigator:navigator;await nav.clipboard.writeText(text);ok=true;}catch{const d=pipWindow?.document.hasFocus()?pipWindow.document:document,t=d.createElement('textarea');t.value=text;t.style.position='fixed';t.style.opacity='0';d.body.append(t);t.select();try{ok=d.execCommand('copy');}catch{}t.remove();}toast(ok?'已复制，可到网站粘贴':'复制失败，请选中文本后按 Ctrl+C');return ok;}
async function api(path,body){const response=await fetch('/api/'+path,{signal:AbortSignal.timeout(path.startsWith('browser/')?20000:15000),method:body?'POST':'GET',headers:{'Content-Type':'application/json','X-Assistant-Session':csrf},body:body?JSON.stringify(body):undefined,cache:'no-store'});let result;try{result=await response.json();}catch{throw new Error('本机服务未返回有效数据，请检查服务是否运行');}if(!response.ok)throw new Error(result.error||'本机请求失败');return result;}
function setBusy(value){busy=value;$('analyze').disabled=value;$('pip-analyze').disabled=value;$('pip-question').disabled=value;$('pip-remove-image').disabled=value;$('question').disabled=value;$('image-input').disabled=value;$('remove-image').disabled=value;$('import-plan').disabled=value;for(const name of ['gemini','deepseek'])$('model-'+name).disabled=value;$('analyze').textContent=value?'模型正在处理…':'生成检索路线';updateAnswerControls();renderFaults();}
function setStatus(result){const labels={ready:'Gemini 已连接',unavailable:'Gemini 未连接',login_required:'Gemini 需要登录',human_required:'Gemini 需要人工验证',rate_limited:'Gemini 暂时限额',busy:'Gemini 正在处理',window_opened:'Gemini 窗口已打开',launch_failed:'Gemini 窗口未能启动'};$('connection').textContent=labels[result.status]||'检查 Gemini 状态';$('connection-help').textContent=result.status==='unavailable'?'Gemini 窗口尚未连接。点击打开按钮复用原登录配置。':result.status==='ready'?'已复用 Gemini 网页会话。数据库网站在当前 Edge 的新标签页打开。':result.detail||'点击“打开 Gemini 登录窗口”，在网页中完成登录后再检查。';}
async function refresh(autoStart=false){if(autoStart===true)autoConnectDeadline=Date.now()+45000;const revision=++statusRevision;try{const names=selectedModels();if(!names.length){$('connection-help').textContent='先选择至少一个模型';return;}const results=await Promise.all(names.map(async name=>{let result=await api('status?model='+name);if(autoStart===true&&result.status==='unavailable'&&!autoOpenedModels.has(name)){autoOpenedModels.add(name);const opening=await api('browser/open',{model:name});if(opening.status==='window_opened'){result=await api('status?model='+name);if(result.status==='unavailable'){result.detail='模型窗口已启动，正在加载；登录状态会从原配置复用。';}}else result=opening;}return {name,...result};}));if(revision!==statusRevision)return;clearTimeout(connectionRetryTimer);if(!busy&&Date.now()<autoConnectDeadline&&results.some(r=>['unavailable','busy'].includes(r.status)))connectionRetryTimer=setTimeout(()=>refresh(false),1500);$('connection').textContent=results.map(r=>(r.name==='gemini'?'Gemini':'DeepSeek')+(r.status==='ready'?' 已连接':r.status==='login_required'?' 需要登录':r.status==='busy'?' 正在处理':' 未连接')).join(' · ');$('connection-help').textContent=results.map(r=>r.detail||'已复用本机专用窗口登录配置').join('；');}catch(e){if(revision!==statusRevision)return;$('connection').textContent='连接失败';$('connection-help').textContent=e.message;if(!busy&&Date.now()<autoConnectDeadline){clearTimeout(connectionRetryTimer);connectionRetryTimer=setTimeout(()=>refresh(false),1500);}}}
function savePlan(){if(plan)memory.set('plan',{plan,active,done:[...done],modelPlans,modelErrors,chosenModel});}
function showPlan(value){if(answerState.question&&answerState.question!==value.question)resetAnswers();plan=value;if(answerState.question===plan.question){answerState.mode=plan.mode;renderAnswers();}updateAnswerControls();active=0;done.clear();if(!busy)memory.remove('job');memory.remove('raw');savePlan();$('route-empty').hidden=true;$('route-result').hidden=false;$('float-route').disabled=false;render();if(matchMedia('(max-width:750px)').matches)$('route-board').scrollIntoView({behavior:'smooth'});}
function render(){if(!plan)return;renderOriginal();renderModels();const s=$('plan-summary');s.replaceChildren();const heading=node('div','plan-heading'),names={direct:'直接作答',retrieve:'需要检索',mixed:'混合题',clarify:'先确认题干'};heading.append(node('h3','',plan.title),node('span','mode-tag',names[plan.mode]));s.append(heading);if(plan.answer)s.append(node('div','plan-answer',plan.answer));if(plan.explanation)s.append(node('p','plan-explanation',plan.explanation));if(plan.issues.length){const issues=node('div','plan-issues');issues.append(node('strong','','需要留意'),...plan.issues.map(x=>node('div','',x)));s.append(issues);}
  $('step-nav').replaceChildren(...plan.steps.map((step,i)=>{const b=node('button','step-button'+(done.has(step.id)?' completed':''));b.type='button';if(i===active)b.setAttribute('aria-current','step');b.append(node('span','step-number',done.has(step.id)?'✓':i+1));const text=node('span','',step.title);text.append(node('small','step-site',step.site?.name||'人工选网站'));b.append(text);b.addEventListener('click',()=>{active=i;renderDetail();renderNav();savePlan();});return b;}));$('step-nav').parentElement.hidden=!plan.steps.length;renderDetail();
}
function renderNav(){[...$('step-nav').children].forEach((b,i)=>{b.removeAttribute('aria-current');if(i===active)b.setAttribute('aria-current','step');b.classList.toggle('completed',done.has(plan.steps[i].id));b.querySelector('.step-number').textContent=done.has(plan.steps[i].id)?'✓':i+1;});}
function fieldInput(input,kind,index){const box=node('div','input-field'),head=node('div','input-field-head'),id='field-'+kind+'-'+index,label=node('label','',input.field);label.htmlFor=id;const b=node('button','','复制');b.type='button';const area=node('textarea');area.id=id;area.rows=2;area.value=input.value;area.maxLength=2000;area.addEventListener('input',()=>{input.value=area.value;savePlan();});b.addEventListener('click',()=>copy(input.value));head.append(label,b);box.append(head,area);return box;}
function block(title,list,cls=''){if(!list.length)return null;const b=node('section','detail-block '+cls),ul=node('ul');b.append(node('h4','',title));ul.append(...list.map(t=>node('li','',t)));b.append(ul);return b;}
function renderDetail(){const d=$('step-detail');d.replaceChildren();if(!plan?.steps.length)return;const step=plan.steps[active],heading=node('div','step-heading');heading.append(node('h3','',`${active+1}. ${step.title}`));if(step.depends_on.length)heading.append(node('p','',`先完成：${step.depends_on.map(id=>plan.steps.find(s=>s.id===id).title).join('、')}，再填入查到的值。`));d.append(heading);
  const open=node('div','step-open');if(step.site){const a=node('a','',`打开 ${step.site.name} ↗`);a.href=step.site.url;a.target='_blank';a.rel='noopener noreferrer';const b=node('a','copy-open',step.inputs.length>1?'复制首项并打开 ↗':'复制输入并打开 ↗');b.href=step.site.url;b.target='_blank';b.rel='noopener noreferrer';b.addEventListener('click',e=>{const pending=step.inputs.some(x=>/\[.*?(填入|待查|查到|不清楚).*?\]/.test(x.value));if(pending){e.preventDefault();toast('先把占位文字替换成上一步查到的真实信息');return;}copy(step.inputs[0]?.value||step.title);if(memory.get('auto-float',true))openFloat();});const floatOption=node('label','auto-float'),toggle=node('input');toggle.type='checkbox';toggle.checked=memory.get('auto-float',true);toggle.addEventListener('change',()=>memory.set('auto-float',toggle.checked));floatOption.append(toggle,document.createTextNode('置顶小窗'));open.append(a,b,floatOption);}else open.append(node('p','hint','请在导航中选择适合的网站，再使用下方输入。'));const copyStep=node('button','','复制本步');copyStep.addEventListener('click',()=>copy(stepText(step)));open.append(copyStep);d.append(open,...step.inputs.map((f,i)=>fieldInput(f,'main',i)));
  [block('筛选与限定条件',step.conditions),block('在结果中查找这些信息',step.find,'find-block'),block('提交答案前核对',step.checks,'checks-block')].filter(Boolean).forEach(b=>d.append(b));if(step.alternative_inputs.length){const extra=node('details'),summary=node('summary','','没有结果？试试备选输入');extra.append(summary,...step.alternative_inputs.map((f,i)=>fieldInput(f,'alternative',i)));d.append(extra);}
  const bottom=node('div','step-bottom'),complete=node('button','',done.has(step.id)?'取消完成标记':'✓ 标记本步完成');complete.addEventListener('click',()=>{done.has(step.id)?done.delete(step.id):done.add(step.id);renderDetail();renderNav();savePlan();});bottom.append(complete);if(active<plan.steps.length-1){const next=node('button','','下一步 →');next.addEventListener('click',()=>{active++;renderDetail();renderNav();savePlan();});bottom.append(next);}d.append(bottom);
}
function renderOriginal(){const panel=$('original-question');panel.hidden=false;const text=$('original-text');text.replaceChildren();const pattern=/(?:GB(?:\/T)?\s*\d+(?:[.－—-]\d+)*|(?:CN|ISBN|DOI)\s*[\w./-]+|(?:19|20)\d{2}(?:年|[-/.]\d{1,2}(?:[-/.]\d{1,2})?)?|不正确|不属于|不包括|不能|错误|正确|最新|现行|截至|至少|最多|首次|除外)/gi;let from=0;for(const match of plan.question.matchAll(pattern)){text.append(document.createTextNode(plan.question.slice(from,match.index)),node('mark','',match[0]));from=match.index+match[0].length;}text.append(document.createTextNode(plan.question.slice(from)));$('view-original').hidden=!originalImage;}
function resetModels(){modelPlans={};modelErrors={};chosenModel='';pendingModels=[];modelStages={};$('model-results').hidden=true;}
function renderModels(){const panel=$('model-results');panel.replaceChildren();const names=[...new Set([...Object.keys(modelPlans),...Object.keys(modelErrors),...pendingModels])];panel.hidden=!names.length;if(names.length>1)panel.append(node('p','hint','分别核对两条路线。识别文本、答案或检索步骤不同，请以原图和数据库记录为准。'));for(const name of names){if(modelPlans[name]){const b=node('button',chosenModel===name?'selected-model':'',name==='gemini'?'Gemini 路线':'DeepSeek 路线');b.type='button';b.setAttribute('aria-pressed',String(chosenModel===name));b.addEventListener('click',()=>{chosenModel=name;showPlan(modelPlans[name]);});panel.append(b);}else if(modelErrors[name])panel.append(node('p','model-error',(name==='gemini'?'Gemini':'DeepSeek')+'：'+modelErrors[name]));else panel.append(node('p','model-pending',(name==='gemini'?'Gemini':'DeepSeek')+'：'+(modelStages[name]?.stage||'正在处理')+'…'));}}
$('view-original').addEventListener('click',()=>{if(!originalImage)return;const d=$('view-original').ownerDocument;if(d!==document){const dialog=d.createElement('dialog'),close=d.createElement('button'),img=d.createElement('img');dialog.id='original-dialog';close.textContent='关闭原图 ×';img.src=originalImage;img.alt='当前题目原图';close.addEventListener('click',()=>dialog.close());dialog.addEventListener('close',()=>dialog.remove());dialog.append(close,img);d.body.append(dialog);dialog.showModal();}else{$('original-dialog-image').src=originalImage;$('original-dialog').showModal();}});$('close-original').addEventListener('click',()=>$('original-dialog').close());
function selectedModels(){return ['gemini','deepseek'].filter(n=>$('model-'+n).checked);}
async function loadImage(file){if(busy)return false;if(!['image/png','image/jpeg'].includes(file.type)||file.size>5*1024*1024){toast('请选择不超过5MB的 PNG 或 JPEG 图片');return false;}image=await new Promise((resolve,reject)=>{const r=new FileReader();r.onload=()=>resolve(r.result);r.onerror=reject;r.readAsDataURL(file);});$('image-preview').src=image;$('image-box').hidden=false;$('pip-image-note').textContent='截图已载入';$('pip-remove-image').hidden=false;return true;}
$('image-input').addEventListener('change',e=>{if(e.target.files[0])loadImage(e.target.files[0]).catch(()=>toast('图片读取失败'));});$('question').addEventListener('paste',e=>{const items=[...e.clipboardData.items],item=items.find(x=>['image/png','image/jpeg'].includes(x.type));if(item){e.preventDefault();loadImage(item.getAsFile()).catch(()=>toast('截图读取失败'));}});$('remove-image').addEventListener('click',()=>{image=null;$('image-input').value='';$('image-preview').removeAttribute('src');$('image-box').hidden=true;$('pip-image-note').textContent='';$('pip-remove-image').hidden=true;});
// Catch file drops before the browser navigates away to the image file.
const dropPanel=document.querySelector('.input-panel');
let fileDragDepth=0;
const hasFiles=e=>[...(e.dataTransfer?.types||[])].includes('Files');
function resetFileDrag(){fileDragDepth=0;dropPanel.classList.remove('dragging-image');}
document.addEventListener('dragenter',e=>{if(!hasFiles(e))return;e.preventDefault();fileDragDepth++;if(!busy)dropPanel.classList.add('dragging-image');});
document.addEventListener('dragover',e=>{if(!hasFiles(e))return;e.preventDefault();e.dataTransfer.dropEffect=busy?'none':'copy';});
document.addEventListener('dragleave',e=>{if(!fileDragDepth)return;if(--fileDragDepth<=0)resetFileDrag();});
document.addEventListener('drop',e=>{if(!hasFiles(e))return;e.preventDefault();resetFileDrag();if(busy){toast('当前正在拆题，请等待完成后再拖入截图');return;}const files=[...e.dataTransfer.files];if(files.length!==1){toast('每次请拖入一张题目截图');return;}loadImage(files[0]).then(loaded=>{if(loaded)toast('截图已载入，点击生成检索路线');}).catch(()=>toast('图片读取失败'));});
window.addEventListener('blur',resetFileDrag);
function waitingRoute(){resetAnswers();resetModels();$('original-question').hidden=true;plan=null;updateAnswerControls();done.clear();memory.remove('plan');$('route-result').hidden=true;$('route-empty').hidden=false;$('route-empty').querySelector('h3').textContent='正在拆解这道题';$('route-empty').querySelector('p').textContent='等待所选模型的完整回答。刷新可恢复同一次任务，不重新发送题目。';$('float-route').disabled=false;}
async function watchJob(job){
  const deadline=Date.now()+340000;
  pendingModels=job.models||selectedModels();renderModels();
  while(Date.now()<deadline){
    const result=await api('jobs/'+job.id);
    const elapsed=Math.max(0,Math.floor(Date.now()/1000-(result.started_at||Date.now()/1000)));
    const stagesChanged=JSON.stringify(modelStages)!==JSON.stringify(result.progress||{});
    modelStages=result.progress||{};
    const responses=result.results||(result.state==='completed'?{gemini:{state:'completed',text:result.text}}:{});
    const current={plans:modelPlans,errors:modelErrors,chosen:chosenModel};
    const changed=consumeModelResults(current,responses,sites);
    const first=!chosenModel&&current.chosen;
    chosenModel=current.chosen;
    if(Object.keys(modelErrors).length)recordFault('route',pendingModels,modelErrors,result.stage,job.id);
    if(first)showPlan(modelPlans[chosenModel]);
    else if(changed||stagesChanged){renderModels();savePlan();}
    const finished=Object.keys(modelPlans).length;
    const waiting=pendingModels.filter(name=>!modelPlans[name]&&!modelErrors[name]);
    $('job-status').textContent=finished
      ? `${finished}个模型结果可用；`+(waiting.length?waiting.map(n=>n==='gemini'?'Gemini':'DeepSeek').join('、')+'仍在处理，可先检索。':'所选模型处理结束。')+` · ${elapsed}秒`
      : (result.stage||'所选模型正在分析')+` · ${elapsed}秒`;
    if(['completed','failed'].includes(result.state)){
      memory.remove('job');pendingModels=[];renderModels();savePlan();refresh();
      if(Object.values(result.results||{}).some(r=>r.tab_cleanup==='closed'))$('job-status').textContent+=' 已关闭完成任务页，保留模型浏览器。';
      memory.set('last-status',$('job-status').textContent);
      if(chosenModel)return;
      const invalid=Object.values(responses).find(r=>r.state==='completed'&&r.text);
      if(invalid){memory.set('raw',invalid.text);$('model-json').value=invalid.text;$('manual-panel').querySelector('details').open=true;}
      throw new Error(result.error||'所选模型未给出可显示的完整路线，请查看模型提示');
    }
    await new Promise(resolve=>setTimeout(resolve,500));
  }
  throw new Error('本机等待超时；已有路线仍可使用。请检查所选模型原会话，不要重复提交。');
}
function failure(error,started,hadImage){recordFault('route',routeRequest?.models||selectedModels(),modelErrors,error.message,memory.get('job')?.id);memory.remove('job');$('route-empty').querySelector('h3').textContent='本次尚未生成路线';$('route-empty').querySelector('p').textContent='查看左侧提示，或通过手动模型网页流程导入完整回答。';$('job-status').textContent=error.message+(started?' 本次未自动重发。':'')+(hadImage?' 如需重新提交，请重新选择截图。':'');memory.set('last-status',$('job-status').textContent);}
$('question').addEventListener('input',()=>{memory.set('draft',$('question').value);if($('pip-question').value!==$('question').value)$('pip-question').value=$('question').value;});
$('pip-question').addEventListener('input',()=>{$('question').value=$('pip-question').value;memory.set('draft',$('question').value);});
$('pip-question').addEventListener('paste',e=>{const item=[...e.clipboardData.items].find(x=>['image/png','image/jpeg'].includes(x.type));if(item){e.preventDefault();loadImage(item.getAsFile()).catch(()=>toast('截图读取失败'));}});
$('pip-question').addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.isComposing&&!e.shiftKey&&!e.ctrlKey&&!e.altKey&&!e.metaKey){e.preventDefault();if(!busy){$('pip-question').blur();$('question-form').requestSubmit();}}});
$('pip-analyze').addEventListener('click',()=>{$('pip-question').blur();$('question-form').requestSubmit();});$('pip-remove-image').addEventListener('click',()=>$('remove-image').click());
const pipCapture=$('pip-question').parentElement;
pipCapture.addEventListener('dragover',e=>{if([...(e.dataTransfer?.types||[])].includes('Files')){e.preventDefault();e.dataTransfer.dropEffect=busy?'none':'copy';pipCapture.classList.toggle('dragging',!busy);}});
pipCapture.addEventListener('dragleave',()=>pipCapture.classList.remove('dragging'));
pipCapture.addEventListener('drop',e=>{if(![...(e.dataTransfer?.types||[])].includes('Files'))return;e.preventDefault();pipCapture.classList.remove('dragging');if(busy){toast('当前正在拆题，请等待完成后再拖入截图');return;}const files=[...e.dataTransfer.files];if(files.length!==1){toast('每次请拖入一张题目截图');return;}loadImage(files[0]).then(loaded=>{if(loaded)toast('截图已载入，点击生成检索路线');}).catch(()=>toast('图片读取失败'));});

async function runRoute(request,retry=false){
 if(busy)return;
 const question=request.question,models=request.models;
 if(!models.length){toast('请至少选择一个拆题模型');return;}
 const attachment=retry?(routeImage||image):image;
 if(retry&&request.hadImage&&!attachment){toast('原截图在刷新后未保留，请重新上传同一张截图，再点重试');return;}
 routeRequest=request;routeImage=attachment;memory.set('route-request',request);clearFault('route');
 if(!retry){memory.set('draft',$('question').value.trim());originalImage=attachment;resetModels();const arithmetic=!attachment&&arithmeticPlan(question);if(arithmetic){showPlan(arithmetic);$('job-status').textContent='本地四则计算已完成，未调用AI。';memory.set('last-status',$('job-status').textContent);return;}}
 if(!local){$('job-status').textContent='请打开本机助手使用自动拆题。';return;}
 setBusy(true);
 if(!retry)waitingRoute();else for(const name of models){delete modelErrors[name];delete modelPlans[name];}
 let started=false;
 try{
  const job=await api('jobs',{models,question,image:attachment,prompt:makePrompt(rules,question,sites)});started=true;
  const savedJob={id:job.id,hadImage:!!attachment,models};memory.set('job',savedJob);await watchJob(savedJob);
 }catch(error){failure(error,started,!!attachment);}finally{setBusy(false);}
}
$('question-form').addEventListener('submit',e=>{e.preventDefault();const question=$('question').value.trim();if(!question&&!image){toast('先输入题目或截图');return;}runRoute({question:question||'请识别并分析所附题目截图',models:selectedModels(),hadImage:!!image});});
$('retry-route').addEventListener('click',()=>{
 if(!routeRequest){toast('请重新输入题目再生成路线');return;}
 const failed=Object.keys(modelErrors);runRoute({...routeRequest,models:failed.length?failed:routeRequest.models},true);
});
$('copy-prompt').addEventListener('click',()=>{const question=$('question').value.trim();if(!question&&!image){toast('先输入题目或截图');return;}copy(makePrompt(rules,question||'请识别并分析所附题目截图',sites));});$('import-plan').addEventListener('click',()=>{try{const imported=parsePlan($('model-json').value,sites);resetModels();originalImage=image;showPlan(imported);$('job-status').textContent='已导入模型路线。';memory.set('last-status',$('job-status').textContent);}catch(e){$('job-status').textContent=e.message;recordFault('route',selectedModels(),{},e.message);}});
for(const name of ['gemini','deepseek'])$('model-'+name).addEventListener('change',()=>{memory.set('models',selectedModels());if(local)refresh(true);});
$('refresh-status').addEventListener('click',refresh);$('open-gemini').addEventListener('click',async()=>{try{setStatus(await api('browser/open',{model:'gemini'}));}catch(e){toast(e.message);}});
$('open-deepseek').addEventListener('click',async()=>{try{const result=await api('browser/open',{model:'deepseek'});$('connection-help').textContent=result.detail||'DeepSeek窗口已打开';await refresh();}catch(e){toast(e.message);}});
function returnRoute(){pipWindow?.close();}
$('return-route').addEventListener('click',returnRoute);$('back-to-assistant').addEventListener('click',()=>{returnRoute();window.focus();$('question').scrollIntoView({behavior:'smooth',block:'center'});if(!busy)$('question').focus({preventScroll:true});});$('float-route').addEventListener('click',()=>pipWindow?returnRoute():openFloat());async function openFloat(){if(pipWindow)return;if(!window.documentPictureInPicture){$('route-notice').textContent='当前浏览器不支持置顶小窗。可以复制各步检索信息，或把助手页与数据库并排放置。';return;}try{let expired=false;const opening=window.documentPictureInPicture.requestWindow({width:480,height:700});opening.then(w=>{if(expired)w.close();}).catch(()=>{});let waitTimer;try{pipWindow=await Promise.race([opening,new Promise((_,reject)=>{waitTimer=setTimeout(()=>{expired=true;reject(new Error('timeout'));},5000);})]);}finally{clearTimeout(waitTimer);}const link=pipWindow.document.createElement('link');link.rel='stylesheet';link.href=document.querySelector('link[rel=stylesheet]').href;pipWindow.document.head.append(link);pipWindow.document.title='检索路线 · 素养聚合';pipWindow.document.body.className='pip-body';pipWindow.document.body.append($('route-board'));$('pip-question').value=$('question').value;$('pip-analyze').disabled=busy;$('pip-question').disabled=busy;$('pip-remove-image').disabled=busy;$('pip-return').hidden=false;$('float-route').textContent='收回小窗';pipWindow.addEventListener('pagehide',()=>{const board=pipWindow.document.getElementById('route-board');if(board)$('pip-return').parentElement.prepend(board);pipWindow=null;$('pip-return').hidden=true;$('float-route').textContent='置顶小窗 ↗';});}catch(e){pipWindow=null;$('route-notice').textContent='置顶小窗未能打开，请复制需要的检索信息，或把窗口并排放置。';}}
for(const kind of ['route','answer'])$('report-'+kind).addEventListener('click',()=>copy(formatErrorReport(kind,faultRecords[kind])));
renderFaults();
const restoredModels=memory.get('models',['deepseek']);for(const name of ['gemini','deepseek'])$('model-'+name).checked=restoredModels.includes(name);
try{const response=await fetch('assistant-prompt.txt',{cache:'no-store'});if(!response.ok)throw new Error('拆题规则读取失败');rules=await response.text();if(local){const session=await api('session');csrf=session.session;$('local-link').hidden=true;$('model-controls').hidden=false;renderFaults();refresh(true);}else{$('connection').textContent='网页模式';$('connection-help').textContent='点击“启动并连接本机助手”自动启动环境并拆题；也可复制提示词，在已登录的模型网页操作后导入回答。';}$('analyze').disabled=false;}catch(e){$('connection').textContent='准备失败';$('connection-help').textContent=e.message;}

// Restore only this tab's own draft/route; resume a saved job via GET, never POST.
$('question').value=memory.get('draft','');
$('job-status').textContent=memory.get('last-status','');
const recovered=memory.get('plan');
if(recovered){try{plan=parsePlan(JSON.stringify(recovered.plan),sites);modelErrors=recovered.modelErrors||{};for(const [name,value] of Object.entries(recovered.modelPlans||{})){try{modelPlans[name]=parsePlan(JSON.stringify(value),sites);}catch{}}chosenModel=recovered.chosenModel||'';active=Math.min(Math.max(0,recovered.active||0),Math.max(0,plan.steps.length-1));(recovered.done||[]).filter(id=>plan.steps.some(s=>s.id===id)).forEach(id=>done.add(id));$('route-empty').hidden=true;$('route-result').hidden=false;$('float-route').disabled=false;render();}catch{memory.remove('plan');}}
const rawRecovered=memory.get('raw');if(rawRecovered){$('model-json').value=rawRecovered;$('manual-panel').querySelector('details').open=true;}
const unfinished=local&&memory.get('job');
if(unfinished&&csrf){setBusy(true);if(!plan){waitingRoute();routeRequest=routeRequest||{question:$('question').value||'请识别所附题目截图',models:unfinished.models,hadImage:unfinished.hadImage};}try{await watchJob(unfinished);}catch(error){failure(error,true,unfinished.hadImage);}finally{setBusy(false);}}


function answerModels(){return ['gemini','deepseek'].filter(n=>$('answer-'+n).checked);}
function updateAnswerControls(){
 $('answer-now').disabled=busy||!plan||!local;
 $('answer-now').title=!local?'自动作答需打开本机助手':!plan?'请先识别题目或生成路线':busy?'等待当前模型调用结束，避免向同一会话同时发送两道任务':'';
 for(const n of ['gemini','deepseek'])$('answer-'+n).disabled=busy;
}
function resetAnswers(){clearFault('answer');answerState={question:'',mode:'',answers:{},errors:{},chosen:'',models:[],status:''};memory.remove('answer');memory.remove('answer-job');renderAnswers();}
function renderAnswers(){
 memory.set('answer',answerState);
 $('answer-status').textContent=answerState.status;
 const models=$('answer-models');models.replaceChildren();
 for(const name of answerState.models){
  const label=name==='gemini'?'Gemini':'DeepSeek';
  if(answerState.answers[name]){
   const b=node('button',answerState.chosen===name?'selected-model':'',label+' 作答');b.type='button';b.setAttribute('aria-pressed',String(answerState.chosen===name));b.addEventListener('click',()=>{answerState.chosen=name;renderAnswers();});models.append(b);
  }else models.append(node('p','hint',label+'：'+(answerState.errors[name]||'正在作答…')));
 }
 const output=$('answer-output'),answer=answerState.answers[answerState.chosen];output.replaceChildren();output.hidden=!answer;$('copy-answer').hidden=!answer;if(!answer)return;
 const warnings=answerWarnings(answer,answerState.mode,answerState.answers);
 if(warnings.length){const risk=node('div','answer-risk');risk.append(node('strong','','提交前请核验'),...warnings.map(w=>node('div','',w)));output.append(risk);}
 output.append(node('p','answer-meta','模型自评把握：'+({high:'高',medium:'一般',low:'低'}[answer.confidence])+' · 尚未独立验证'),node('p','plan-answer',answer.answer||'无法可靠给出答案'),node('p','',answer.explanation));
 const checks=block('需要核验',answer.checks,'checks-block');if(checks)output.append(checks);
}
async function watchAnswer(job){
 const deadline=Date.now()+340000;
 while(Date.now()<deadline){
  const result=await api('jobs/'+job.id);
  consumeAnswerResults(answerState,result.results||{});
  if(Object.keys(answerState.errors).length)recordFault('answer',answerState.models,answerState.errors,result.stage,job.id);
  const waiting=answerState.models.filter(n=>!answerState.answers[n]&&!answerState.errors[n]);
  const count=Object.keys(answerState.answers).length;
  answerState.status=(count?`${count}个模型答案可用，可先查看。 `:'')+waiting.map(n=>(n==='gemini'?'Gemini':'DeepSeek')+'：'+(result.progress?.[n]?.stage||'正在作答')).join('；');
  if(['completed','failed'].includes(result.state)){
   memory.remove('answer-job');answerState.status=count?'作答结束。请核对模型依据和提示。':(result.error||'没有可用的完整答案，请检查模型原窗口。');if(Object.values(result.results||{}).some(r=>r.tab_cleanup==='closed'))answerState.status+=' 已关闭完成任务页，保留模型浏览器。';renderAnswers();return;
  }
  renderAnswers();await new Promise(resolve=>setTimeout(resolve,500));
 }
 throw new Error('等待作答超时；已显示的答案仍可查看。本次未自动重发。');
}

async function runAnswer(models,retry=false){
 if(busy||!plan)return;
 if(!models.length){toast('请至少选择一个作答模型');return;}
 if(!local){toast('请先打开本机助手');return;}
 clearFault('answer');
 if(!retry)answerState={question:plan.question,mode:plan.mode,answers:{},errors:{},chosen:'',models,status:'正在提交当前识别的原题…'};
 else {for(const n of models){delete answerState.errors[n];delete answerState.answers[n];}answerState.status='正在重试失败模型…';}
 renderAnswers();setBusy(true);
 try{
  const job=await api('jobs',{models,question:answerState.question,image:originalImage,prompt:makeAnswerPrompt(answerState.question,answerState.mode)});
  const saved={id:job.id,models};memory.set('answer-job',saved);await watchAnswer(saved);
 }catch(e){recordFault('answer',models,answerState.errors,e.message,memory.get('answer-job')?.id);memory.remove('answer-job');for(const n of models)if(!answerState.answers[n]&&!answerState.errors[n])answerState.errors[n]='本次未完成，请检查原模型窗口';answerState.status=e.message;renderAnswers();}
 finally{setBusy(false);}
}
$('answer-now').addEventListener('click',()=>runAnswer(answerModels()));
$('retry-answer').addEventListener('click',()=>{const failed=Object.keys(answerState.errors);runAnswer(failed.length?failed:answerState.models,true);});
$('copy-answer').addEventListener('click',()=>{
 const a=answerState.answers[answerState.chosen];if(!a)return;
 copy([answerState.question,'答案：'+(a.answer||'无法可靠作答'),a.explanation,'模型自评把握：'+a.confidence+'（非实际准确率）',...answerWarnings(a,answerState.mode,answerState.answers),...a.checks.map(x=>'核验：'+x)].join('\n\n'));
});
const restoredAnswerModels=memory.get('answer-models',['deepseek']);for(const n of ['gemini','deepseek']){
 $('answer-'+n).checked=restoredAnswerModels.includes(n);$('answer-'+n).addEventListener('change',()=>memory.set('answer-models',answerModels()));
}
const recoveredAnswer=memory.get('answer');if(recoveredAnswer&&plan&&recoveredAnswer.question===plan.question){answerState=recoveredAnswer;renderAnswers();}
updateAnswerControls();
const unfinishedAnswer=local&&memory.get('answer-job');
if(unfinishedAnswer&&csrf&&answerState.question===plan?.question){setBusy(true);try{await watchAnswer(unfinishedAnswer);}catch(e){recordFault('answer',unfinishedAnswer.models,answerState.errors,e.message,unfinishedAnswer.id);memory.remove('answer-job');answerState.status=e.message;for(const n of answerState.models)if(!answerState.answers[n]&&!answerState.errors[n])answerState.errors[n]='本次未完成';renderAnswers();}finally{setBusy(false);}}


function renderFaults(){for(const kind of ['route','answer']){$(kind+'-error-actions').hidden=!faultRecords[kind];$('retry-'+kind).disabled=busy||!local||!csrf;}}
function clearFault(kind){delete faultRecords[kind];memory.set('fault-records',faultRecords);renderFaults();}
function recordFault(kind,models,errors,message,jobId){
 faultRecords[kind]={time:new Date().toISOString(),models:models||[],errors:{...errors},message:message||'模型调用或回答校验失败',jobId:jobId||'',hadImage:kind==='route'?!!routeRequest?.hadImage:!!originalImage};memory.set('fault-records',faultRecords);renderFaults();
}

