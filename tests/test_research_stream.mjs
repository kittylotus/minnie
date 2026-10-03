import assert from 'node:assert/strict';
import {parseFrames,watchResearch} from '../web/research.js';
let parsed=parseFrames(': keep-alive\r\n\r\nevent: snapshot\r\ndata: {"answer":"Partial","status":"pending"}\r\n\r\nevent: snapshot\ndata: {"answer":"Fin');
assert.equal(parsed.frames.length,1);assert.equal(parsed.frames[0].data.answer,'Partial');
parsed=parseFrames(parsed.buffer+'ished","status":"complete"}\n\n');
assert.equal(parsed.frames[0].data.answer,'Finished');assert.equal(parsed.frames[0].data.status,'complete');assert.equal(parsed.buffer,'');
console.log('Reconnect snapshot frame parsing checks passed.');
globalThis.document=new EventTarget();document.visibilityState='visible';globalThis.window=new EventTarget();
const identity={chatId:'chat',turnId:'turn',runId:'run'};const snapshots=[];let attempts=0,reconnects=0;
globalThis.fetch=async(url,options)=>{
  assert.equal(url,'/api/research/events');assert.deepEqual(JSON.parse(options.body),identity);
  const state=++attempts===1?{status:'pending',answer:'Partial'}:{status:'complete',answer:'Full answer',result:{answer:'Full answer'}};
  return {ok:true,body:new ReadableStream({start(controller){controller.enqueue(new TextEncoder().encode('event: snapshot\ndata: '+JSON.stringify(state)+'\n\n'));controller.close();}})};
};
const final=await watchResearch(identity,{signal:new AbortController().signal,onSnapshot:s=>snapshots.push(s),onReconnect:()=>reconnects++});
assert.equal(attempts,2);assert.equal(reconnects,1);assert.equal(final.status,'complete');assert.deepEqual(snapshots.map(s=>s.answer),['Partial','Full answer']);
console.log('Viewer reconnects to the same job without resubmitting generation.');
