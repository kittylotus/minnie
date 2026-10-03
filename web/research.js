export function parseFrames(buffer){
  buffer=buffer.replace(/\r\n/g,'\n');const frames=[];let split;
  while((split=buffer.indexOf('\n\n'))!==-1){const frame=buffer.slice(0,split);buffer=buffer.slice(split+2);let event='message';const lines=[];for(const line of frame.split('\n')){if(line.startsWith('event:'))event=line.slice(6).trim();else if(line.startsWith('data:'))lines.push(line.slice(5).trimStart());}if(lines.length)frames.push({event,data:JSON.parse(lines.join('\n'))});}
  return {frames,buffer};
}

function abortError(){return new DOMException('Observer stopped.','AbortError');}
function wait(ms,signal){return new Promise((resolve,reject)=>{if(signal.aborted){reject(abortError());return;}const timer=setTimeout(done,ms);function done(){signal.removeEventListener('abort',abort);resolve();}function abort(){clearTimeout(timer);signal.removeEventListener('abort',abort);reject(abortError());}signal.addEventListener('abort',abort,{once:true});});}
function foreground(signal){return new Promise((resolve,reject)=>{if(signal.aborted){reject(abortError());return;}if(document.visibilityState!=='hidden'){resolve();return;}function clean(){document.removeEventListener('visibilitychange',changed);window.removeEventListener('pageshow',changed);signal.removeEventListener('abort',abort);}function changed(){if(document.visibilityState!=='hidden'){clean();resolve();}}function abort(){clean();reject(abortError());}document.addEventListener('visibilitychange',changed);window.addEventListener('pageshow',changed);signal.addEventListener('abort',abort,{once:true});});}

export async function watchResearch(identity,{signal,onSnapshot,onReconnect=()=>{}}){
  while(!signal.aborted){
    await foreground(signal);
    const observer=new AbortController();let reader=null;
    const abort=()=>observer.abort();const hide=()=>{if(document.visibilityState==='hidden')observer.abort();};
    signal.addEventListener('abort',abort,{once:true});document.addEventListener('visibilitychange',hide);window.addEventListener('pagehide',abort);
    try{
      const response=await fetch('/api/research/events',{method:'POST',headers:{'Content-Type':'application/json','Accept':'text/event-stream'},body:JSON.stringify(identity),signal:observer.signal});
      if(!response.ok){const data=await response.json();const error=Error(data.error||'Could not reconnect to research.');error.fatal=[400,401,403,404].includes(response.status);throw error;}
      if(!response.body)throw Error('Streaming unavailable; reconnecting.');
      reader=response.body.getReader();const decoder=new TextDecoder();let buffer='';
      while(true){const {value,done}=await reader.read();buffer+=done?decoder.decode():decoder.decode(value,{stream:true});const parsed=parseFrames(buffer);buffer=parsed.buffer;for(const frame of parsed.frames){if(frame.event!=='snapshot')continue;onSnapshot(frame.data);if(frame.data.status!=='pending')return frame.data;}if(done)break;}
      onReconnect();
    }catch(e){if(signal.aborted)throw abortError();if(e.fatal)throw e;if(document.visibilityState!=='hidden')onReconnect();}
    finally{signal.removeEventListener('abort',abort);document.removeEventListener('visibilitychange',hide);window.removeEventListener('pagehide',abort);if(reader){reader.cancel().catch(()=>{});reader.releaseLock();}}
    if(document.visibilityState!=='hidden')await wait(1500,signal);
  }
  throw abortError();
}
