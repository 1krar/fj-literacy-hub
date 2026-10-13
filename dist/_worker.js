const COOKIE='__Host-literacy_access', TTL=8*60*60;
const encoder=new TextEncoder();
const escape=value=>String(value).replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const secureHeaders={'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','X-Frame-Options':'DENY','Referrer-Policy':'same-origin',
  'Content-Security-Policy':"default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'"};
function nextPath(value) {
  return typeof value==='string' && value.startsWith('/') && !value.startsWith('//') && !/[\\\r\n]/.test(value) && value.length<2000 ? value : '/';
}
function login(next,error='',status=200) {
  return new Response(`<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>素养聚合 · 访问验证</title>
  <style>body{font:16px/1.6 system-ui,"Microsoft YaHei",sans-serif;background:#f4f7f2;color:#20382e;margin:0;min-height:100vh;display:grid;place-items:center}main{box-sizing:border-box;width:min(420px,calc(100% - 32px));padding:30px;background:#fff;border:1px solid #dce7dd;border-radius:16px}h1{font-size:23px;margin:0 0 10px}p{color:#61796b}label{display:block;margin:18px 0 6px}input,button{box-sizing:border-box;width:100%;font:inherit;border:1px solid #b6cebe;border-radius:9px;padding:12px}input:focus{outline:3px solid #a6dbb7}button{margin-top:16px;background:#25684f;color:white;cursor:pointer}.error{color:#a14132}.hint{font-size:13px}</style>
  <main><h1>素养聚合</h1><p>请输入访问密码，继续使用检索工作台。</p>${error?`<p class="error" role="alert">${escape(error)}</p>`:''}
  <form action="/__access/login" method="post"><input type="hidden" name="next" value="${escape(nextPath(next))}"><label for="password">访问密码</label><input id="password" name="password" type="password" autocomplete="current-password" required autofocus maxlength="128"><button type="submit">验证并进入</button></form><p class="hint">验证后 8 小时内无需重复输入。</p></main></html>`,{status,headers:{...secureHeaders,'Content-Type':'text/html; charset=utf-8'}});
}
async function key(secret) {return crypto.subtle.importKey('raw',encoder.encode(secret),{name:'HMAC',hash:'SHA-256'},false,['sign','verify']);}
const hex=bytes=>Array.from(new Uint8Array(bytes),value=>value.toString(16).padStart(2,'0')).join('');
async function validCookie(request,secret) {
  const token=(request.headers.get('Cookie') || '').split(';').map(value=>value.trim()).find(value=>value.startsWith(COOKIE+'='))?.slice(COOKIE.length+1);
  if (!token || !/^\d{10}\.[a-f0-9]{32}\.[a-f0-9]{64}$/.test(token))return false;
  const [expiry,nonce,signature]=token.split('.'),now=Math.floor(Date.now()/1000);
  if (Number(expiry)<=now || Number(expiry)>now+TTL+60)return false;
  const bytes=Uint8Array.from(signature.match(/../g),value=>parseInt(value,16));
  return crypto.subtle.verify('HMAC',await key(secret),bytes,encoder.encode(expiry+'.'+nonce));
}
async function handle(request,env) {
  if (!/^[a-f0-9]{64}$/.test(env.SITE_PASSWORD_SHA256 || '') || !env.SITE_SESSION_SECRET || env.SITE_SESSION_SECRET.length<32)
    return new Response('访问验证暂未配置，请联系维护者。',{status:503,headers:secureHeaders});
  const url=new URL(request.url);
  if (url.pathname==='/__access/login') {
    if (request.method==='GET')return login(url.searchParams.get('next'));
    if (request.method!=='POST' || request.headers.get('Origin')!==url.origin)
      return new Response('请从本站验证页面提交。',{status:403,headers:secureHeaders});
    if (Number(request.headers.get('Content-Length') || 0)>2048)return login('/','输入过长。',400);
    const raw=await request.text();if(raw.length>2048)return login('/','输入过长。',400);
    const form=new URLSearchParams(raw),password=form.get('password') || '',next=nextPath(form.get('next'));
    const digest=hex(await crypto.subtle.digest('SHA-256',encoder.encode(password)));
    if (digest!==env.SITE_PASSWORD_SHA256)return login(next,'密码不正确，请重新输入。',401);
    const data=Math.floor(Date.now()/1000)+TTL+'.'+hex(crypto.getRandomValues(new Uint8Array(16)));
    const signature=hex(await crypto.subtle.sign('HMAC',await key(env.SITE_SESSION_SECRET),encoder.encode(data)));
    return new Response(null,{status:303,headers:{...secureHeaders,'Location':next,
      'Set-Cookie':`${COOKIE}=${data}.${signature}; Path=/; Secure; HttpOnly; SameSite=Lax; Max-Age=${TTL}`}});
  }
  if (!await validCookie(request,env.SITE_SESSION_SECRET)) {
    if (url.pathname==='/' || /\.html?$/.test(url.pathname) || request.headers.get('Accept')?.includes('text/html'))
      return login(url.pathname+url.search);
    return new Response('需要访问密码验证。',{status:401,headers:secureHeaders});
  }
  const asset=await env.ASSETS.fetch(request),response=new Response(asset.body,asset);
  response.headers.set('Cache-Control','private, no-store');response.headers.set('Vary','Cookie');
  return response;
}
export default {async fetch(request,env) {
  try{return await handle(request,env);}catch{return new Response('验证服务暂时不可用，请稍后重试。',{status:503,headers:secureHeaders});}
}};
