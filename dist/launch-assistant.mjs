const status=document.querySelector('#status'),detail=document.querySelector('#detail');
const local='http://127.0.0.1:8771';
let deadline=0,timer,checking=false,attempted=false;
function launch(){
  attempted=true;deadline=Date.now()+45000;
  status.textContent='已尝试启动，正在等待本机助手…';
  detail.textContent='如果 Edge 提示“打开应用”，请选择允许；启动成功后会自动进入。没有提示时，请使用下方按钮或处理方法。';
  try{window.location.href='literacy-assistant://open';}catch{detail.textContent='此浏览器没有打开启动应用，请改用普通 Edge，或双击“启动比赛助手.cmd”。';}
  schedule();
}
function schedule(){clearTimeout(timer);timer=setTimeout(check,1500);}
async function check(){
  if(checking)return;
  checking=true;
  try{
    const response=await fetch(local+'/api/launch-status',{cache:'no-store',credentials:'omit',signal:AbortSignal.timeout(1800)});
    const result=await response.json();
    if(response.ok&&result.app==='literacy-assistant'&&result.ready===true){
      clearTimeout(timer);status.textContent='本机助手已就绪，正在进入…';
      detail.textContent='进入后会自动连接所选模型。';window.location.replace(local+'/assistant.html');return;
    }
  }catch{/* A blocked local-network probe does not imply that the helper failed. */}
  finally{checking=false;}
  if(!attempted){launch();return;}
  if(Date.now()<deadline){schedule();return;}
  status.textContent='尚未确认连接，请选择下方操作';
  detail.textContent='可能未允许打开应用，或浏览器阻止了本地检测。请点“直接进入助手”；如果仍打不开，展开处理方法。';
}
document.querySelector('#start').addEventListener('click',event=>{event.preventDefault();launch();});
check();
