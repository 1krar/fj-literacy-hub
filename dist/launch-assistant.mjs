const status=document.querySelector('#status'),detail=document.querySelector('#detail');
const start=document.querySelector('#start'),local='http://127.0.0.1:8771';
const ctrl=new URLSearchParams(location.search).get('tool')==='ctrl';
const target=ctrl?'ctrl-assistant.html':'assistant.html';
if(ctrl){document.title='启动 CTRL 助手 · 素养聚合';document.querySelector('h1').textContent='打开 CTRL 助手';document.querySelector('main>p:nth-of-type(2)').textContent='连接本机助手，快速 OCR、提取关键词和检索网站。';}
document.querySelector('#enter').href=local+'/'+target;
let deadline=0,timer,checking=false,attempted=false;
function schedule(){clearTimeout(timer);timer=setTimeout(check,1500);}
async function check(){
  if(checking)return;
  checking=true;
  try{
    const response=await fetch(local+'/api/launch-status',{cache:'no-store',credentials:'omit',signal:AbortSignal.timeout(1800)});
    const result=await response.json();
    if(response.ok&&result.app==='literacy-assistant'&&result.ready===true){
      clearTimeout(timer);status.textContent='本机助手已就绪，正在进入…';
      detail.textContent='进入后会检查所选模型的连接状态。';window.location.replace(local+'/'+target);return;
    }
  }catch{/* A blocked local-network probe does not imply that the helper failed. */}
  finally{checking=false;}
  if(!attempted){
    status.textContent='尚未检测到本机助手';
    detail.textContent='如果刚登录 Windows，请稍等片刻再点“直接进入助手”；否则点击下方“启动本机助手”。';
    return;
  }
  if(Date.now()<deadline){schedule();return;}
  status.textContent='启动后仍未确认连接';
  detail.textContent='可能没有放行打开应用，或浏览器限制了本机检测。请点“直接进入助手”确认；仍打不开时展开下方处理方法。';
}
// Preserve the anchor's native navigation and the user's click activation.
start.addEventListener('click',()=>{
  attempted=true;deadline=Date.now()+45000;
  status.textContent='已请求启动，正在等待本机助手…';
  detail.textContent='如 Edge 询问是否打开应用，请选择允许。若没有提示，也可运行安装器启用登录后预启动。';
  schedule();
});
check();
