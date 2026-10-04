import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

// Exercise the real preference handlers against controlled browser state.
const source=fs.readFileSync(new URL('../web/app.js',import.meta.url),'utf8');
function segment(start,end){
  assert.equal(source.split(start).length,2);
  assert.equal(source.split(end).length,2);
  return source.slice(source.indexOf(start),source.indexOf(end));
}
const setup=segment('const READING_DEFAULTS=','async function api(');
const handlers=segment("for(const [id,key]of[['brightness'","$('#settings-open').onclick=");
function fixture(saved){
  const elements=new Map(),styles=new Map(),storage=new Map(saved?[['minnie-reading',JSON.stringify(saved)]]:[]);
  const context={document:{documentElement:{style:{setProperty:(k,v)=>styles.set(k,v)}}},localStorage:{getItem:k=>storage.get(k),setItem:(k,v)=>storage.set(k,v)},$:id=>{if(!elements.has(id))elements.set(id,{});return elements.get(id);}};
  vm.runInNewContext(setup+handlers,context);
  return {elements,styles,prefs:()=>JSON.parse(storage.get('minnie-reading'))};
}
const existing=fixture({brightness:103,size:25,spacing:22});
assert.equal(existing.styles.get('--body-size'),'25px');
assert.equal(existing.styles.get('--leading'),2.2);
assert.equal(existing.elements.get('#gradient-opacity').value,14);
existing.elements.get('#gradient-color').oninput({target:{value:'#445566'}});
existing.elements.get('#gradient-opacity').oninput({target:{value:'20'}});
assert.equal(existing.styles.get('--bottom-gradient-opacity'),.2);
assert.equal(existing.prefs().gradientColor,'#445566');
existing.elements.get('#reset-reading').onclick();
assert.equal(existing.prefs().size,12);
assert.equal(existing.prefs().gradientColor,'#445566');
existing.elements.get('#font-size').oninput({target:{value:'21'}});
existing.elements.get('#reset-gradient').onclick();
assert.equal(existing.prefs().size,21);
assert.equal(existing.prefs().gradientColor,'#777a68');
const reopened=fixture(existing.prefs());
assert.equal(reopened.styles.get('--body-size'),'21px');
const fresh=fixture();
assert.equal(fresh.styles.get('--body-size'),'12px');
console.log('Appearance preference persistence and independent resets passed.');
