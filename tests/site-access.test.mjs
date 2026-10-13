import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createHash} from 'node:crypto';
const worker=(await import('data:text/javascript;base64,'+readFileSync(new URL('../dist/_worker.js',import.meta.url)).toString('base64'))).default;
const password='fixture-only-password';
const env={SITE_PASSWORD_SHA256:createHash('sha256').update(password).digest('hex'),SITE_SESSION_SECRET:'test-session-secret-'.repeat(4),ASSETS:{fetch:()=>new Response('protected asset')}};
function request(path,options={}) {return new Request('https://example.com'+path,options);}
test('unauthenticated pages show verification and assets remain blocked',async()=>{
  const page=await worker.fetch(request('/bookmarks.html'),env);
  assert.match(await page.text(),/访问密码/);
  assert.equal((await worker.fetch(request('/bookmarks.json'),env)).status,401);
  assert.equal((await worker.fetch(request('/app.js'),env)).status,401);
});
test('incorrect password and cross-origin submissions do not grant access',async()=>{
  assert.equal((await worker.fetch(request('/__access/login',{method:'POST',headers:{Origin:'https://example.com'},body:'password=wrong'}),env)).status,401);
  assert.equal((await worker.fetch(request('/__access/login',{method:'POST',headers:{Origin:'https://other.example'},body:'password='+password}),env)).status,403);
});
test('valid password creates signed secure cookie and returns requested local page',async()=>{
  const response=await worker.fetch(request('/__access/login',{method:'POST',headers:{Origin:'https://example.com'},body:new URLSearchParams({password,next:'/bookmarks.html'})}),env);
  assert.equal(response.status,303);assert.equal(response.headers.get('Location'),'/bookmarks.html');
  const cookie=response.headers.get('Set-Cookie');assert.match(cookie,/Secure; HttpOnly; SameSite=Lax/);
  const access=await worker.fetch(request('/bookmarks.json',{headers:{Cookie:cookie.split(';')[0]}}),env);
  assert.equal(await access.text(),'protected asset');assert.equal(access.headers.get('Cache-Control'),'private, no-store');
  const tampered=cookie.split(';')[0].slice(0,-1)+'x';
  assert.equal((await worker.fetch(request('/bookmarks.json',{headers:{Cookie:tampered}}),env)).status,401);
});
test('redirect injection and absent secret configuration fail safely',async()=>{
  const response=await worker.fetch(request('/__access/login',{method:'POST',headers:{Origin:'https://example.com'},body:new URLSearchParams({password,next:'//outside.example/'})}),env);
  assert.equal(response.headers.get('Location'),'/');
  assert.equal((await worker.fetch(request('/'),{ASSETS:env.ASSETS})).status,503);
});
