import test from 'node:test';
import assert from 'node:assert/strict';
import {bindImageCapture} from '../dist/capture-input.mjs';

function documentStub() {
  const handlers = {};
  return {handlers,addEventListener:(type,fn) => (handlers[type] ||= []).push(fn),
    emit(type,data) { let prevented=false; for (const fn of handlers[type] || []) fn({...data,preventDefault(){prevented=true;}}); return prevented; }};
}
test('whole-document images work in both documents and duplicate binding does not duplicate intake', () => {
  const main=documentStub(), pip=documentStub(), received=[], file={type:'image/png'};
  for (const doc of [main,pip]) {
    bindImageCapture(doc, value => received.push(value));
    bindImageCapture(doc, value => received.push(value));
    assert.equal(doc.emit('paste',{clipboardData:{items:[{kind:'file',type:'image/png',getAsFile:()=>file}]}}),true);
    assert.equal(doc.emit('drop',{dataTransfer:{types:['Files'],files:[file]}}),true);
  }
  assert.equal(received.length,4);
});
test('text paste is left native and several dropped images each become one intake', () => {
  const doc=documentStub(), received=[];
  bindImageCapture(doc, file => received.push(file));
  assert.equal(doc.emit('paste',{clipboardData:{items:[{kind:'string',type:'text/plain'}]}}),false);
  const files=[{type:'image/png'},{type:'image/jpeg'},{type:'text/plain'}];
  doc.emit('drop',{dataTransfer:{types:['Files'],files}});
  assert.deepEqual(received,files.slice(0,2));
});
