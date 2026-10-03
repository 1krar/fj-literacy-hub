import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source=fs.readFileSync(new URL('../dist/launch-assistant.mjs',import.meta.url),'utf8');
test('offline launch page waits for a real click and keeps native protocol navigation',async()=>{
  const elements=new Map(['#status','#detail','#start'].map(key=>[key,{textContent:'',addEventListener(type,fn){this.click=fn;}}]));
  const location={href:'https://fj-literacy-hub.pages.dev/launch-assistant.html',replace(){throw Error('unexpected redirect');}};
  let scheduled=0;
  vm.runInNewContext(source,{
    document:{querySelector:key=>elements.get(key)},window:{location},
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
