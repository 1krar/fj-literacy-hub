import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source=fs.readFileSync(new URL('../dist/launch-assistant.mjs',import.meta.url),'utf8');
test('offline launch page waits for a real click and keeps native protocol navigation',async()=>{
  const elements=new Map(['#status','#detail','#start','#enter','h1','main>p:nth-of-type(2)'].map(key=>[key,{textContent:'',addEventListener(type,fn){this.click=fn;}}]));
  const location={href:'https://fj-literacy-hub.pages.dev/launch-assistant.html',search:'',replace(){throw Error('unexpected redirect');}};
  let scheduled=0;
  vm.runInNewContext(source,{
    document:{querySelector:key=>elements.get(key),title:''},window:{location},location,URLSearchParams,
    fetch:()=>Promise.reject(Error('offline')),
    AbortSignal:{timeout:()=>undefined},
    setTimeout:()=>{scheduled++;return scheduled;},clearTimeout:()=>{},
  });
  await new Promise(resolve=>setImmediate(resolve));
  assert.match(elements.get('#status').textContent,/尚未检测到/);
  assert.equal(location.href,'https://fj-literacy-hub.pages.dev/launch-assistant.html');
  assert.equal(scheduled,0);
  let prevented=false;
  elements.get('#start').click({preventDefault(){prevented=true;}});
  assert.equal(prevented,false);
  assert.equal(scheduled,1);
});
test('CTRL launch keeps the native start link and points direct entry to CTRL page',async()=>{
  const elements=new Map(['#status','#detail','#start','#enter','h1','main>p:nth-of-type(2)'].map(key=>[key,{textContent:'',href:'',addEventListener(){}}]));
  const location={search:'?tool=ctrl',replace(){throw Error('offline must not redirect');}};
  vm.runInNewContext(source,{
    document:{querySelector:key=>elements.get(key),title:''},window:{location},location,URLSearchParams,
    fetch:()=>Promise.reject(Error('offline')),AbortSignal:{timeout:()=>undefined},
    setTimeout:()=>1,clearTimeout:()=>{},
  });
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(elements.get('#enter').href,'http://127.0.0.1:8771/ctrl-assistant.html');
  assert.equal(elements.get('h1').textContent,'打开 CTRL 助手');
});
