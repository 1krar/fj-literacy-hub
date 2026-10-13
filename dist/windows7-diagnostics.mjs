const status=document.getElementById('status'), table=document.getElementById('checks');
let session='', rows=[];
async function call(path,body) {
  const response=await fetch('/api/'+path,{cache:'no-store',method:body?'POST':'GET',
    headers:{'X-Assistant-Session':session,...(body?{'Content-Type':'application/json'}:{})},
    ...(body?{body:JSON.stringify(body)}:{})});
  const value=await response.json(); if (!response.ok) throw Error(value.error || '后台请求失败');return value;
}
function render() {
  table.replaceChildren(...rows.map(row => { const tr=document.createElement('tr');
    for (const field of ['name','state','detail']) { const td=document.createElement('td');td.textContent=row[field];tr.append(td); }return tr; }));
}
async function check(network=false) {
  status.textContent=network?'正在检查网络…':'正在检查环境…';
  try {
    const response=await fetch('/api/session',{cache:'no-store'}); if (!response.ok) throw Error('后台未连接');
    session=(await response.json()).session;
    rows=(await call('diagnostics')).checks;
    if (network) rows.push(...(await call('diagnostics/network',{})).checks);
    render();status.textContent='检查完成';
  } catch(error) { status.textContent='检查失败：'+error.message+'；请重新运行“启动 CTRL 助手.cmd”。'; }
}
document.getElementById('refresh').onclick=()=>check();
document.getElementById('network').onclick=()=>check(true);
document.getElementById('copy').onclick=async()=> {
  const value='CTRL API 兼容版诊断\n'+rows.map(row=>[row.name,row.state,row.detail].join(' | ')).join('\n');
  try { await navigator.clipboard.writeText(value);status.textContent='报告已复制，不含题目或凭证。'; }
  catch { const box=document.createElement('textarea');box.value=value;document.body.append(box);box.select();
    status.textContent='请按 Ctrl+C 复制报告。'; }
};
check();
