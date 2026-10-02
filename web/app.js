import {icon} from './icons.js';
import {renderMarkdown,evidenceMarkdown,evidenceInFolder,evidenceForExport,moveEvidenceItems,unfileEvidenceFolder,contextPlainText} from './markdown.js';
const $=s=>document.querySelector(s);
const escapeHTML=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let view='research',busy=false,status={},poll;
let currentChatId=null,currentChat=null,library={chats:[],folders:[]},folderFilter='all',nameAction=null,deleteAction=null;
const composerDock=document.createElement('div');composerDock.id='composer-dock';composerDock.hidden=true;document.querySelector('main').append(composerDock);
const dockResize=new ResizeObserver(()=>{document.documentElement.style.setProperty('--composer-height',composerDock.hidden?'0px':composerDock.getBoundingClientRect().height+'px');});dockResize.observe(composerDock);
const optionsDialog=document.createElement('dialog');optionsDialog.id='research-options-dialog';optionsDialog.innerHTML='<div class="dialog-top"><h2>Research options</h2><button type="button" class="close" aria-label="Close research options">'+icon('x')+'</button></div><div id="research-options-body"><section class="options-section" aria-labelledby="answer-options-heading"><h3 id="answer-options-heading">Answer settings</h3><div id="answer-options"></div></section><section class="options-section" aria-labelledby="source-options-heading"><h3 id="source-options-heading">Source filters</h3><div id="source-options"></div></section></div>';
document.body.append(optionsDialog);optionsDialog.querySelector('.close').onclick=()=>optionsDialog.close();
const optionsButton=document.createElement('button');optionsButton.type='button';optionsButton.id='research-options';optionsButton.hidden=true;optionsButton.setAttribute('aria-label','Open research options');optionsButton.setAttribute('aria-haspopup','dialog');optionsButton.innerHTML=icon('chevron-up');$('#submit').before(optionsButton);optionsButton.onclick=()=>optionsDialog.showModal();
let saved=JSON.parse(localStorage.getItem('minnie-evidence')||'[]');
let evidenceFolders=JSON.parse(localStorage.getItem('minnie-evidence-folders')||'[]'),evidenceTrash=JSON.parse(localStorage.getItem('minnie-evidence-trash')||'[]');
let evidenceFolder='all',evidenceSelecting=false,evidenceSelected=new Set();
function persistEvidence(){localStorage.setItem('minnie-evidence',JSON.stringify(saved));localStorage.setItem('minnie-evidence-folders',JSON.stringify(evidenceFolders));}
function visibleEvidence(){return evidenceInFolder(saved,evidenceFolder);}
function exportEvidence(){return evidenceForExport(saved,evidenceFolder,evidenceSelected);}

let reading=JSON.parse(localStorage.getItem('minnie-reading')||'{"brightness":112,"size":19,"spacing":18}');
function applyReading(){const b=reading.brightness;document.documentElement.style.setProperty('--text',`rgb(${b},${b+2},${b-3})`);document.documentElement.style.setProperty('--body-size',reading.size+'px');document.documentElement.style.setProperty('--leading',reading.spacing/10);$('#brightness').value=b;$('#font-size').value=reading.size;$('#line-spacing').value=reading.spacing;}
applyReading();
async function api(path,body){const r=await fetch('/api/'+path,body!==undefined?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{});const value=await r.json();if(!r.ok){if(r.status===401&&!$('#login-dialog').open)$('#login-dialog').showModal();throw Error(value.error||'Request failed.');}return value;}
function feedback(text,error=false){$('#feedback').textContent=text;$('#feedback').className=error?'error':'';}
function setView(next){if(busy)return;view=next;document.querySelectorAll('[data-view]').forEach(b=>{const active=b.dataset.view===view;b.classList.toggle('active',active);if(b.hasAttribute('role'))b.setAttribute('aria-selected',active)});const shelf=view==='saved';$('#page-label').textContent=shelf?'SAVED EVIDENCE':view==='search'?'DIALOGUE SEARCH':'RESEARCH';$('#heading').textContent=shelf?'Keep the receipts.':view==='search'?'Find the words.':'Follow a thread.';$('#intro').textContent=shelf?'A shelf for the lines you want to come back to.':view==='search'?'The dialogue itself. Exact terms, a speaker, a line you remember.':'A question, a half-remembered line, a very specific rabbit hole.';$('.tabs').hidden=shelf;$('#query-form').hidden=shelf;$('.filters').hidden=shelf;$('#saved-view').hidden=!shelf;$('#starting').hidden=shelf;$('#output').hidden=true;$('#depth-wrap').hidden=view!=='research';$('#verbosity-wrap').hidden=view!=='research';$('#mode-wrap').hidden=view!=='search';$('#submit').textContent=view==='search'?'Search':'Research';$('#query').placeholder=view==='search'?'A phrase, a name, a fragment of dialogue…':'What does the game say about memory and the Pale?';feedback('');if(shelf)renderSaved();}
document.querySelectorAll('[data-view]').forEach(b=>b.onclick=()=>{if(busy)return;setView(b.dataset.view);syncChatView();});
document.querySelectorAll('[data-prompt]').forEach(b=>b.onclick=()=>{$('#query').value=b.dataset.prompt;$('#query').focus();});
function card(n,focus=false){const isSaved=saved.some(x=>x.id===n.id);return `<article class="evidence-card ${focus?'evidence-focus':''}"><div class="card-top"><span class="speaker-name">${escapeHTML(n.speaker)}</span><span class="node-id">${escapeHTML(n.id)}</span></div><p class="dialogue-text">${escapeHTML(n.speaker.trim().toUpperCase()==='HUB'?'Dialogue choice point':n.text||'(Branch node without spoken dialogue)')}</p><div class="card-actions"><button class="text-button" data-context="${escapeHTML(n.id)}">Open dialogue context</button><button class="text-button" data-save="${escapeHTML(n.id)}">${isSaved?icon('check')+' Saved':'Save evidence'}</button><small>${escapeHTML(n.title)}</small></div>${n.retrieval?`<details><summary>Retrieval details</summary><pre>${escapeHTML(JSON.stringify(n.retrieval,null,2))}</pre></details>`:''}</article>`;}
const records=new Map();
function syncChatView(){
  const active=view==='research';$('#chat-toolbar').hidden=!active;$('#chat-history').hidden=!active||!currentChat?.turns.length;$('#current-question').hidden=!active||!currentChat;
  if(!active)conversationLayout(false);
  if(active&&currentChat)renderChat(currentChat);
}
function renderHistory(turns){
  const container=$('#chat-history');container.hidden=!turns.length;
  container.innerHTML=turns.map(t=>`<article class="chat-turn"><div class="turn-label">YOU</div><p class="user-question">${escapeHTML(t.question)}</p>${t.status==='complete'?`<div class="turn-label">ARCHIVE</div>${t.result.reasoning?`<details class="past-reasoning"><summary>Model reasoning</summary><div class="dialogue-text plain-reasoning">${escapeHTML(t.result.reasoning)}</div></details>`:''}<div class="markdown-answer">${renderAnswer(t.result.answer)}</div>${t.result.citationWarning?'<p class="notice">Check the evidence: this answer has missing or unverified citations.</p>':''}<details><summary>Cited evidence · ${t.result.evidence.length} sources</summary>${t.result.evidence.map(n=>card(n)).join('')}</details>`:`<p class="notice">${escapeHTML(t.error||'This answer is still in progress on the server.')}</p>`}</article>`).join('');
  bindCards(container,turns.flatMap(t=>t.result?.retrieved||t.result?.evidence||[]));
}
function renderChat(chat){
  conversationLayout(true);
  currentChat=chat;currentChatId=chat.id;$('#chat-title').textContent=chat.title;$('#query').placeholder='Ask a follow-up…';$('#starting').hidden=true;
  const last=chat.turns.at(-1);
  if(last?.status==='complete'){
    renderHistory(chat.turns.slice(0,-1));showResults(last.result);$('#current-question').textContent=last.question;$('#current-question').hidden=false;
  }else{renderHistory(chat.turns);$('#output').hidden=true;$('#current-question').hidden=true;if(last?.status==='error')feedback('This chat is saved. You can resend the question or ask a follow-up.');}
}
async function openChat(id){
  if(busy)return;
  try{const chat=await api('chat',{id});currentChat=chat;setView('research');syncChatView();$('#query').value='';localStorage.setItem('minnie-current-chat',id);if($('#chats-dialog').open)$('#chats-dialog').close();}
  catch(e){feedback(e.message,true);}
}
function newChat(){
  if(busy)return;currentChat=null;currentChatId=null;localStorage.removeItem('minnie-current-chat');setView('research');syncChatView();conversationLayout(false);$('#chat-history').hidden=true;$('#current-question').hidden=true;$('#chat-title').textContent='New research chat';$('#query').value='';$('#query').focus();
}
function conversationLayout(active){
  const form=$('#query-form'),filters=$('.filters'),question=$('#current-question'),output=$('#output'),status=$('#feedback');
  const docked=active&&view==='research';
  document.body.classList.toggle('chat-active',docked);composerDock.hidden=!docked;
  optionsButton.hidden=!docked;
  $('.tabs').hidden=view==='saved'||docked;
  $('#query').rows=docked?1:3;$('#query').style.height='';$('#submit').textContent=docked?'Send':view==='search'?'Search':'Research';$('#chat-organize').textContent=docked?'Organize':'Organize chats';
  if(docked){output.before(question);composerDock.append(form,status);$('#answer-options').append($('.tool-group'));$('#source-options').append(filters);$('#query').placeholder='Ask a follow-up…';}
  else{if(optionsDialog.open)optionsDialog.close();$('.query-tools').prepend($('.tool-group'));$('#chat-history').after(form);form.after(filters);filters.after(question);question.after(status);status.after(output);}
  document.documentElement.style.setProperty('--composer-height',docked?composerDock.getBoundingClientRect().height+'px':'0px');
}
async function refreshLibrary(){
  library=await api('chats');
  const recent=$('#recent-chats');recent.innerHTML=library.chats.slice(0,6).map(c=>`<button class="recent-chat ${c.id===currentChatId?'selected':''}" data-chat="${c.id}" title="${escapeHTML(c.title)}">${c.pinned?icon('pin'):''}${escapeHTML(c.title)}</button>`).join('');recent.querySelectorAll('[data-chat]').forEach(b=>b.onclick=()=>openChat(b.dataset.chat));
  const select=$('#folder-filter');select.replaceChildren(new Option('All chats','all'),new Option('Unfiled',''));
  for(const folder of library.folders)select.add(new Option((folder.pinned?'(Pinned) ':'')+folder.name,folder.id));
  if(folderFilter&&folderFilter!=='all'&&!library.folders.some(f=>f.id===folderFilter))folderFilter='all';select.value=folderFilter;
  renderLibrary();
}
function askName(action,id,title,value=''){
  nameAction={action,id};$('#name-title').textContent=title;$('#item-name').value=value;$('#name-error').textContent='';$('#name-dialog').showModal();$('#item-name').focus();
}
function askDelete(action,id,name){
  deleteAction={action,id};$('#delete-description').textContent=action==='deleteFolder'?`Delete folder “${name}”? Its chats will move to Unfiled.`:`Delete chat “${name}” and all its responses? This cannot be undone.`;$('#delete-error').textContent='';$('#delete-dialog').showModal();
}
async function libraryAction(payload){await api('chats/manage',payload);await refreshLibrary();if(currentChatId&&!library.chats.some(c=>c.id===currentChatId))newChat();else if(currentChatId){const c=library.chats.find(c=>c.id===currentChatId);$('#chat-title').textContent=c.title;if(currentChat)currentChat.title=c.title;}}
function renderLibrary(){
  const chats=library.chats.filter(c=>folderFilter==='all'||(c.folder_id||'')===folderFilter);
  const container=$('#chat-list');container.innerHTML=chats.length?chats.map(c=>`<article class="library-chat"><button class="chat-name" data-chat="${c.id}" title="${escapeHTML(c.title)}">${c.pinned?icon('pin'):''}${escapeHTML(c.title)}</button><p class="dialog-note">${escapeHTML(library.folders.find(f=>f.id===c.folder_id)?.name||'Unfiled')} · ${new Date(c.updated_at*1000).toLocaleDateString()}</p><div class="library-row-actions"><button class="text-button" data-rename="${c.id}">${icon('pencil')} Rename</button><button class="text-button" data-pin="${c.id}">${icon(c.pinned?'pin-off':'pin')} ${c.pinned?'Unpin':'Pin'}</button><button class="text-button" data-delete="${c.id}">${icon('trash-2')} Delete</button><label><span class="sr-only">Move to folder</span><select data-move="${c.id}" aria-label="Move ${escapeHTML(c.title)} to folder"><option value="">Unfiled</option>${library.folders.map(f=>`<option value="${f.id}" ${c.folder_id===f.id?'selected':''}>${escapeHTML(f.name)}</option>`).join('')}</select></label></div></article>`).join(''):'<p class="empty">No chats here yet. Start a research question to save a conversation.</p>';
  container.querySelectorAll('[data-chat]').forEach(b=>b.onclick=()=>openChat(b.dataset.chat));
  container.querySelectorAll('[data-rename]').forEach(b=>b.onclick=()=>{const c=library.chats.find(c=>c.id===b.dataset.rename);askName('renameChat',c.id,'Rename chat',c.title);});
  container.querySelectorAll('[data-pin]').forEach(b=>b.onclick=()=>{const c=library.chats.find(c=>c.id===b.dataset.pin);libraryAction({action:'pinChat',id:c.id,pinned:!c.pinned}).catch(e=>$('#library-feedback').textContent=e.message);});
  container.querySelectorAll('[data-delete]').forEach(b=>b.onclick=()=>{const c=library.chats.find(c=>c.id===b.dataset.delete);askDelete('deleteChat',c.id,c.title);});
  container.querySelectorAll('[data-move]').forEach(s=>s.onchange=()=>libraryAction({action:'moveChat',id:s.dataset.move,folderId:s.value}).catch(e=>$('#library-feedback').textContent=e.message));
  const folder=library.folders.find(f=>f.id===folderFilter);$('#folder-actions').innerHTML=folder?'<button class="text-button" id="rename-folder">Rename folder</button><button class="text-button" id="pin-folder">'+(folder.pinned?'Unpin folder':'Pin folder')+'</button><button class="text-button" id="delete-folder">Delete folder</button>':'';
  if(folder){$('#rename-folder').onclick=()=>askName('renameFolder',folder.id,'Rename folder',folder.name);$('#pin-folder').onclick=()=>libraryAction({action:'pinFolder',id:folder.id,pinned:!folder.pinned}).catch(e=>$('#library-feedback').textContent=e.message);$('#delete-folder').onclick=()=>askDelete('deleteFolder',folder.id,folder.name);}
}
async function showLibrary(){try{await refreshLibrary();$('#library-feedback').textContent='';$('#chats-dialog').showModal();}catch(e){feedback(e.message,true);}}
$('#chats-open').onclick=showLibrary;$('#chat-organize').onclick=showLibrary;$('#new-chat').onclick=newChat;
$('#folder-filter').onchange=e=>{folderFilter=e.target.value;renderLibrary();};
$('#create-folder').onclick=()=>askName('createFolder',null,'New folder');
$('#name-form').onsubmit=async e=>{e.preventDefault();try{if(nameAction.action.startsWith('evidence')){evidenceName(nameAction,$('#item-name').value);$('#name-dialog').close();return;}const result=await api('chats/manage',{...nameAction,name:$('#item-name').value});if(nameAction.action==='createFolder')folderFilter=result.id;$('#name-dialog').close();await refreshLibrary();if(currentChat){currentChat.title=library.chats.find(c=>c.id===currentChatId)?.title||currentChat.title;$('#chat-title').textContent=currentChat.title;}}catch(e){$('#name-error').textContent=e.message;}};
$('#delete-cancel').onclick=()=>$('#delete-dialog').close();
$('#delete-confirm').onclick=async()=>{try{if(deleteAction.action.startsWith('evidence')){evidenceDelete(deleteAction);$('#delete-dialog').close();return;}await libraryAction(deleteAction);$('#delete-dialog').close();}catch(e){$('#delete-error').textContent=e.message;}};
function bindCards(container,nodes){nodes.forEach(n=>records.set(n.id,n));container.querySelectorAll('[data-context]').forEach(b=>b.onclick=()=>openContext(b.dataset.context));container.querySelectorAll('[data-save]').forEach(b=>b.onclick=()=>{const id=b.dataset.save;const exists=saved.some(n=>n.id===id);saved=exists?saved.filter(n=>n.id!==id):[...saved,records.get(id)];localStorage.setItem('minnie-evidence',JSON.stringify(saved));b.innerHTML=exists?'Save evidence':icon('check')+' Saved';if(view==='saved')renderSaved();});}
function renderSaved(){
  const rows=visibleEvidence(),ids=new Set(rows.map(n=>n.id));evidenceSelected=new Set([...evidenceSelected].filter(id=>ids.has(id)));
  const filter=$('#evidence-folder-filter');filter.replaceChildren(new Option('All evidence','all'),new Option('Unfiled',''));
  for(const folder of evidenceFolders)filter.add(new Option(folder.name,folder.id));filter.value=evidenceFolder;
  const move=$('#evidence-move-folder'),target=move.value;move.replaceChildren(new Option('Unfiled',''));
  for(const folder of evidenceFolders)move.add(new Option(folder.name,folder.id));if([...move.options].some(o=>o.value===target))move.value=target;
  $('#evidence-folder-actions').hidden=!evidenceFolders.some(f=>f.id===evidenceFolder);
  $('#evidence-bulk').hidden=!evidenceSelecting;$('#evidence-select').textContent=evidenceSelecting?'Done':'Select';
  $('#evidence-undo').hidden=!evidenceTrash.length;$('#evidence-export-status').textContent='';
  $('#saved-list').innerHTML=rows.length?rows.map(n=>`<div class="saved-evidence-row ${evidenceSelected.has(n.id)?'selected':''}">${evidenceSelecting?`<label class="evidence-check"><input type="checkbox" data-evidence-select="${escapeHTML(n.id)}" ${evidenceSelected.has(n.id)?'checked':''}><span class="sr-only">Select source ${escapeHTML(n.id)}, ${escapeHTML(n.speaker)}</span></label>`:''}${card(n)}</div>`).join(''):'<p class="empty">'+(saved.length?'No evidence in this folder yet. Select snippets in All evidence to move them here.':'Your shelf is empty. Save a line from a search or a source citation.')+'</p>';
  bindCards($('#saved-list'),rows);
  $('#saved-list').querySelectorAll('[data-evidence-select]').forEach(input=>input.onchange=()=>{if(input.checked)evidenceSelected.add(input.dataset.evidenceSelect);else evidenceSelected.delete(input.dataset.evidenceSelect);input.closest('.saved-evidence-row').classList.toggle('selected',input.checked);updateEvidenceSelection();});
  updateEvidenceSelection();
}
function updateEvidenceSelection(){
  const rows=visibleEvidence(),count=evidenceSelected.size;
  $('#evidence-selection-count').textContent=`${count} selected`;
  const all=$('#evidence-select-all');all.checked=!!rows.length&&count===rows.length;all.indeterminate=count>0&&count<rows.length;all.disabled=!rows.length;
  $('#evidence-move').disabled=$('#evidence-remove').disabled=!count;
  $('#copy-evidence').disabled=$('#download-evidence').disabled=!exportEvidence().length;
  $('#copy-evidence').textContent=count?'Copy selected as Markdown':'Copy as Markdown';$('#download-evidence').textContent=count?'Download selected .md':'Download .md';
}
$('#evidence-folder-filter').onchange=e=>{evidenceFolder=e.target.value;evidenceSelected.clear();renderSaved();};
$('#evidence-select').onclick=()=>{evidenceSelecting=!evidenceSelecting;if(!evidenceSelecting)evidenceSelected.clear();renderSaved();};
$('#evidence-select-all').onchange=e=>{evidenceSelected=e.target.checked?new Set(visibleEvidence().map(n=>n.id)):new Set();renderSaved();};
$('#evidence-create-folder').onclick=()=>askName('evidenceCreateFolder',null,'New evidence folder');
$('#evidence-rename-folder').onclick=()=>{const f=evidenceFolders.find(f=>f.id===evidenceFolder);if(f)askName('evidenceRenameFolder',f.id,'Rename evidence folder',f.name);};
$('#evidence-delete-folder').onclick=()=>{const f=evidenceFolders.find(f=>f.id===evidenceFolder);if(f){deleteAction={action:'evidenceDeleteFolder',id:f.id};$('#delete-description').textContent=`Delete folder “${f.name}”? Its evidence will move to Unfiled.`;$('#delete-error').textContent='';$('#delete-dialog').showModal();}};
$('#evidence-move').onclick=()=>{const target=$('#evidence-move-folder').value;saved=moveEvidenceItems(saved,evidenceSelected,target);persistEvidence();evidenceSelected.clear();renderSaved();$('#evidence-export-status').textContent='Evidence moved.';};
$('#evidence-remove').onclick=()=>{deleteAction={action:'evidenceRemove',ids:[...evidenceSelected]};$('#delete-description').textContent=`Remove ${evidenceSelected.size} selected snippets from the evidence shelf? You can undo this removal.`;$('#delete-error').textContent='';$('#delete-dialog').showModal();};
$('#evidence-undo-remove').onclick=()=>{const ids=new Set(saved.map(n=>n.id));saved=[...saved,...evidenceTrash.filter(n=>!ids.has(n.id)).map(n=>({...n,folderId:evidenceFolders.some(f=>f.id===n.folderId)?n.folderId:''}))];persistEvidence();evidenceTrash=[];localStorage.setItem('minnie-evidence-trash','[]');evidenceFolder='all';renderSaved();$('#evidence-export-status').textContent='Removed evidence restored.';};
function evidenceName(action,name){
  name=name.trim();if(!name)throw Error('Enter a folder name.');
  if(action.action==='evidenceCreateFolder'){const id='evidence-'+(crypto.randomUUID?.()||Date.now().toString(36)+'-'+Math.random().toString(36).slice(2));evidenceFolders.push({id,name});evidenceFolder=id;}
  else{const f=evidenceFolders.find(f=>f.id===action.id);if(!f)throw Error('Folder not found.');f.name=name;}
  persistEvidence();evidenceSelected.clear();renderSaved();
}
function evidenceDelete(action){
  if(action.action==='evidenceDeleteFolder'){saved=unfileEvidenceFolder(saved,action.id);evidenceFolders=evidenceFolders.filter(f=>f.id!==action.id);evidenceFolder='';}
  else{const ids=new Set(action.ids);evidenceTrash=saved.filter(n=>ids.has(n.id));localStorage.setItem('minnie-evidence-trash',JSON.stringify(evidenceTrash));saved=saved.filter(n=>!ids.has(n.id));}
  persistEvidence();evidenceSelected.clear();renderSaved();
}

let contextTrail=[],contextCurrent=null,contextRequest=0;
function lineDetails(n){
  let html=n.passiveCheck?`<p class="passive-check">Passive ${escapeHTML(n.passiveCheck.skill)} check · approximately ${n.passiveCheck.estimatedSkill} skill required</p>`:'';
  if(n.conditions)html+=`<details><summary>Conditions for this line</summary><pre>${escapeHTML(n.conditions)}</pre></details>`;
  const alternatives=JSON.parse(n.alternates||'[]');
  if(alternatives.length)html+=`<details><summary>Alternate lines (${alternatives.length})</summary>${alternatives.map(a=>`<p class="dialogue-text">${escapeHTML(a.text)}</p><pre>${escapeHTML(a.condition)}</pre>`).join('')}</details>`;
  if(n.checks?.length)html+=`<details><summary>Skill checks & modifiers</summary><pre>${escapeHTML(JSON.stringify({checks:n.checks,modifiers:n.modifiers},null,2))}</pre></details>`;
  if(n.script)html+=`<details><summary>Effects of this line</summary><pre>${escapeHTML(n.script)}</pre></details>`;
  return html;
}
function manualCopy(text){$('#evidence-export-text').value=text;$('#copy-evidence-dialog').showModal();$('#evidence-export-text').focus();$('#evidence-export-text').select();}
$('#copy-dialogue-context').onclick=async()=>{
  const text=$('#evidence-title').textContent+'\n\n'+contextPlainText($('#evidence-body'));
  try{if(!navigator.clipboard?.writeText)throw Error('Clipboard unavailable');await navigator.clipboard.writeText(text);$('#context-copy-status').textContent='Full dialogue context copied.';}
  catch{manualCopy(text);$('#context-copy-status').textContent='Context is ready for manual copying.';}
};
$('#copy-evidence').onclick=async()=>{
  const items=exportEvidence();if(!items.length)return;
  const text=evidenceMarkdown(items),message=$('#evidence-export-status');
  try{
    if(!navigator.clipboard?.writeText)throw Error('Clipboard unavailable');
    await navigator.clipboard.writeText(text);
    message.textContent=`Copied ${items.length} saved ${items.length===1?'line':'lines'} as Markdown.`;
  }catch{
    manualCopy(text);
    message.textContent='Markdown is ready for manual copying. Download .md is also available.';
  }
};
$('#select-evidence-text').onclick=()=>{$('#evidence-export-text').focus();$('#evidence-export-text').select();};
$('#download-evidence').onclick=()=>{
  const items=exportEvidence();if(!items.length)return;
  const blob=new Blob([evidenceMarkdown(items)],{type:'text/markdown;charset=utf-8'}),url=URL.createObjectURL(blob),a=document.createElement('a');
  a.href=url;a.download='minnie-evidence.md';document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),10000);
  $('#evidence-export-status').textContent='Markdown download started.';
};
async function openContext(id,back=false){
  const d=$('#evidence-dialog'),request=++contextRequest;
  if(!d.open){contextTrail=[];contextCurrent=null;d.showModal();}
  if(!back&&contextCurrent&&contextCurrent!==id)contextTrail.push(contextCurrent);
  contextCurrent=id;$('#evidence-title').textContent='Source '+id;$('#context-copy-status').textContent='';$('#copy-dialogue-context').disabled=true;$('#evidence-body').textContent='Following dialogue links…';
  try{
    const data=await api('context',{nodeId:id,depth:1,includeBranch:true});if(request!==contextRequest)return;
    const branch=data.branch,center=data.center,parents=new Set(data.edges.filter(e=>e.to===id).map(e=>e.from));
    const prior=data.nodes.filter(n=>parents.has(n.id)&&n.id!==id);
    let html=contextTrail.length?'<button class="text-button" id="context-back">'+icon('chevron-up')+' Previous branch</button>':'';
    html+='<p class="dialog-note">Following database links in order. Conditions and skill checks are shown for reference; your game state is not applied.</p>';
    if(branch.sequence.length)html+=branch.sequence.map(n=>`<section class="branch-line">${card(n,n.id===id)}${lineDetails(n)}</section>`).join('');
    else html+=card(center,true);
    if(branch.choices.length){
      html+=`<div class="section-heading"><h2>${branch.stop==='choices'?'Next dialogue choices':'Possible continuations'}</h2><span>${escapeHTML(branch.choicePoint.id)}</span></div><ol class="dialogue-choices">`+branch.choices.map(n=>`<li><button class="dialogue-choice" data-context="${escapeHTML(n.id)}"><span class="choice-speaker">${escapeHTML(n.speaker==='HUB'?'Choice point':n.speaker)} · ${escapeHTML(n.id)}</span><span>${escapeHTML(n.structural?'Continue to dialogue choices':n.text||'Continue')}</span></button>${lineDetails(n)}</li>`).join('')+'</ol>';
    }else html+=`<p class="dialog-note">${({end:'End of this dialogue branch.',cycle:'This branch loops back to an earlier line.',limit:'Sequence paused after 100 linked nodes.',missing:'The next linked line is unavailable.'})[branch.stop]||'End of this dialogue branch.'}</p>`;
    if(branch.stop==='cycle'||branch.stop==='limit')html+='<button class="text-button" data-context="'+escapeHTML(branch.continueAt)+'">Continue from '+escapeHTML(branch.continueAt)+'</button>';
    if(prior.length)html+=`<details><summary>Leads into this line · ${prior.length} links</summary>${prior.map(n=>card(n)).join('')}</details>`;
    $('#evidence-body').innerHTML=html;bindCards($('#evidence-body'),[...data.nodes,...branch.sequence,...branch.choices]);
    if($('#context-back'))$('#context-back').onclick=()=>openContext(contextTrail.pop(),true);
    $('#copy-dialogue-context').disabled=false;d.scrollTop=0;
  }catch(e){if(request===contextRequest)$('#evidence-body').textContent=e.message;}
}

function renderAnswer(text){return renderMarkdown(text);}
async function streamArchive(payload){
  const response=await fetch('/api/research/stream',{method:'POST',headers:{'Content-Type':'application/json','Accept':'text/event-stream'},body:JSON.stringify(payload)});
  if(!response.ok){const data=await response.json();if(response.status===401&&!$('#login-dialog').open)$('#login-dialog').showModal();throw Error(data.error||'Research request failed.');}
  if(!response.body)throw Error('Streaming is unavailable in this browser.');
  const reader=response.body.getReader(),decoder=new TextDecoder();let pending='',result=null,roundReason='',completedReasons=[];
  const renderReason=()=>{const text=[...completedReasons,roundReason].filter(Boolean).join('\n\n');$('#reasoning-panel').hidden=!text;$('#reasoning-text').textContent=text;};
  const consume=frame=>{
    let event='message';const lines=[];
    for(const line of frame.split('\n')){if(line.startsWith('event:'))event=line.slice(6).trim();else if(line.startsWith('data:'))lines.push(line.slice(5).trimStart());}
    if(!lines.length)return;const data=JSON.parse(lines.join('\n'));
    if(event==='error')throw Error(data.error||'The research stream was interrupted.');
    if(event==='chat'){currentChatId=data.chatId;conversationLayout(true);localStorage.setItem('minnie-current-chat',currentChatId);refreshLibrary().catch(()=>{});}
    if(event==='status')feedback(data.message);
    if(event==='round'){if(roundReason)completedReasons.push(roundReason);roundReason='';$('#answer').textContent='';feedback(data.message);renderReason();}
    if(event==='delta'){$('#output').hidden=false;$('#output-title').textContent='Research in progress';$('#answer').hidden=false;$('#answer').innerHTML=renderMarkdown(data.answer||'',{citations:false});roundReason=data.reasoning||'';renderReason();}
    if(event==='done')result=data;
  };
  try{
    while(true){const {value,done}=await reader.read();pending+=(done?decoder.decode():decoder.decode(value,{stream:true}));pending=pending.replace(/\r\n/g,'\n');let split;while((split=pending.indexOf('\n\n'))!==-1){consume(pending.slice(0,split));pending=pending.slice(split+2);}if(done)break;}
    if(pending.trim())consume(pending);
    if(!result)throw Error('The research stream ended before the answer finished. Please retry.');
    return result;
  }finally{await reader.cancel().catch(()=>{});reader.releaseLock();}
}
function showResults(data){
  $('#output').hidden=false;$('#output-title').textContent=view==='search'?`${data.results.length} dialogue matches`:'Research notes';
  $('#answer').hidden=view==='search';$('#answer').innerHTML=view==='research'?renderAnswer(data.answer):'';
  $('#reasoning-panel').hidden=view!=='research'||!data.reasoning;$('#reasoning-text').textContent=data.reasoning||'';
  const nodes=data.results||data.evidence;
  $('#results').innerHTML=(view==='research'?'<div class="section-heading"><h2>Cited evidence</h2><span>Open a line to follow its branch.</span></div>':'')+(nodes.length?nodes.map(n=>card(n)).join(''):'<p class="empty">No matching dialogue found. Try fewer words or a different spelling.</p>');
  if(data.suggestion){$('#results').insertAdjacentHTML('afterbegin',`<p class="notice">Did you mean <button class="text-button" id="suggestion">${escapeHTML(data.suggestion)}</button>?</p>`);$('#suggestion').onclick=()=>{$('#query').value=data.suggestion;$('#query-form').requestSubmit();};}
  $('#citation-warning').hidden=!data.citationWarning;$('#citation-warning').textContent='This answer contains missing or unverified citations. Treat it as a research lead and check the dialogue.';
  if(data.trace?.length)$('#results').insertAdjacentHTML('beforeend',`<details><summary>Research trail · ${data.trace.length} follow-up searches</summary><pre>${escapeHTML(data.trace.join('\n'))}</pre></details>`);
  bindCards($('#results'),nodes);bindCards($('#answer'),data.retrieved||[]);
  feedback(data.semantic?'Lexical and semantic evidence retrieved.':'Lexical retrieval · semantic index not in use.');
}
$('#query-form').onsubmit=async e=>{
  e.preventDefault();const query=$('#query').value.trim();if(!query||busy)return;
  busy=true;document.body.classList.add('chat-busy');$('#submit').disabled=true;$('#starting').hidden=true;$('#output').hidden=true;$('#answer').textContent='';$('#results').textContent='';$('#reasoning-panel').hidden=true;$('#reasoning-panel').open=false;$('#reasoning-text').textContent='';$('#citation-warning').hidden=true;
  if(view==='research'){$('#query').value='';conversationLayout(true);}
  $('#feedback').className='';$('#feedback').innerHTML='<div class="progress-message"><span class="busy-dot"></span>'+(view==='search'?'Searching the archive…':'Following the evidence…')+'</div>';
  try{
    const common={query,speaker:$('#speaker').value,skill:$('#skill').value};
    if(view==='research'){
      if(currentChatId){currentChat=await api('chat',{id:currentChatId});renderHistory(currentChat.turns);}
      $('#current-question').textContent=query;$('#current-question').hidden=false;
    }
    const data=view==='search'?await api('search',{...common,mode:$('#mode').value,limit:50}):await streamArchive({...common,chatId:currentChatId,folderId:folderFilter==='all'?null:folderFilter,depth:$('#depth').value,verbosity:$('#verbosity').value});
    showResults(data);
    if(view==='research'){currentChatId=data.chatId;currentChat=await api('chat',{id:currentChatId});$('#query').placeholder='Ask a follow-up…';$('#chat-title').textContent=currentChat.title;await refreshLibrary();}
  }catch(err){feedback(err.message,true);if($('#answer').textContent||$('#reasoning-text').textContent){$('#output-title').textContent='Interrupted research · partial output';$('#output').hidden=false;}else $('#starting').hidden=false;}
  finally{busy=false;document.body.classList.remove('chat-busy');$('#submit').disabled=false;}
};
$('#query').onkeydown=e=>{if((e.ctrlKey||e.metaKey)&&e.key==='Enter'){$('#query-form').requestSubmit();e.preventDefault();}};
$('#clear-output').onclick=()=>{if(view==='research')newChat();else{$('#output').hidden=true;$('#starting').hidden=false;feedback('');}};
document.querySelectorAll('[data-close]').forEach(b=>b.onclick=()=>$('#'+b.dataset.close).close());
$('#reading-open').onclick=()=>$('#reading-dialog').showModal();
for(const [id,key]of[['brightness','brightness'],['font-size','size'],['line-spacing','spacing']])$('#'+id).oninput=e=>{reading[key]=+e.target.value;applyReading();localStorage.setItem('minnie-reading',JSON.stringify(reading));};
$('#reset-reading').onclick=()=>{reading={brightness:112,size:19,spacing:18};applyReading();localStorage.setItem('minnie-reading',JSON.stringify(reading));};
$('#settings-open').onclick=async()=>{try{const conf=await api('settings');const f=$('#settings-form');for(const kind of['llm','embedding']){f.elements[kind+'-url'].value=conf[kind]?.baseUrl||'';f.elements[kind+'-model'].value=conf[kind]?.model||'';f.elements[kind+'-key'].value='';f.elements[kind+'-key'].placeholder=conf[kind]?.hasKey?'Saved · leave blank to keep':'API key';}f.elements.instructions.value=conf.customInstructions||'';$('#settings-dialog').showModal();}catch(e){feedback(e.message,true);}};
function providerFields(kind){const f=$('#settings-form');return {baseUrl:f.elements[kind+'-url'].value.trim(),model:f.elements[kind+'-model'].value.trim(),apiKey:f.elements[kind+'-key'].value};}
async function saveSettings(kind){
  const f=$('#settings-form');const body=kind?{[kind]:providerFields(kind)}:{customInstructions:f.elements.instructions.value};
  await api('settings',body);
  if(kind){const key=f.elements[kind+'-key'];if(key.value)key.placeholder='Saved · leave blank to keep';key.value='';$('#'+kind+'-provider-status').textContent='Provider saved.';}
  else $('#settings-feedback').textContent='Custom instructions saved.';
  if(kind==='embedding')await refreshStatus();
}
$('#settings-form').onsubmit=async e=>{e.preventDefault();try{await saveSettings();}catch(e){$('#settings-feedback').textContent=e.message;}};
for(const kind of ['llm','embedding']){
  const button=$('#'+kind+'-load-models'),select=$('#'+kind+'-models'),wrap=$('#'+kind+'-models-wrap'),message=$('#'+kind+'-models-status');
  const filter=$('#'+kind+'-model-search'),filterWrap=$('#'+kind+'-model-search-wrap');
  const providerStatus=$('#'+kind+'-provider-status'),save=$('#'+kind+'-save'),ping=$('#'+kind+'-ping');
  let generation=0,models=[];
  const reset=()=>{generation++;models=[];wrap.hidden=true;filterWrap.hidden=true;filter.value='';select.replaceChildren(new Option('Choose a model…',''));message.textContent='';providerStatus.textContent='';};
  const form=$('#settings-form');
  const renderModels=()=>{
    const query=filter.value.trim().toLowerCase();const matches=models.filter(id=>id.toLowerCase().includes(query));
    select.replaceChildren(new Option(matches.length?'Choose a model…':'No matching models',''));
    for(const id of matches)select.add(new Option(id,id));
    const current=form.elements[kind+'-model'].value;if(matches.includes(current))select.value=current;
    select.disabled=!matches.length;
    message.textContent=models.length?`${matches.length} of ${models.length} models. Choose one above, or enter an ID manually.`:'No models returned. You can still enter a model ID manually.';
  };
  filter.oninput=renderModels;
  form.elements[kind+'-url'].addEventListener('input',reset);
  form.elements[kind+'-key'].addEventListener('input',reset);
  form.elements[kind+'-model'].addEventListener('input',()=>{generation++;providerStatus.textContent='';});
  $('#settings-open').addEventListener('click',reset);
  select.onchange=()=>{if(select.value){generation++;form.elements[kind+'-model'].value=select.value;providerStatus.textContent='';}};
  button.onclick=async()=>{
    const requestGeneration=++generation;button.disabled=true;wrap.hidden=true;filterWrap.hidden=true;message.textContent='Loading available models…';
    try{
      const {baseUrl,apiKey}=providerFields(kind);const data=await api('models',{kind,baseUrl,apiKey});
      if(requestGeneration!==generation)return;
      models=data.models;filter.value='';wrap.hidden=filterWrap.hidden=!models.length;renderModels();
    }catch(e){if(requestGeneration===generation)message.textContent=e.message+' You can still enter a model ID manually.';}
    finally{button.disabled=false;}
  };
  save.onclick=async()=>{save.disabled=true;try{await saveSettings(kind);}catch(e){providerStatus.textContent=e.message;}finally{save.disabled=false;}};
  ping.onclick=async()=>{
    const requestGeneration=generation;ping.disabled=true;providerStatus.textContent='Testing the selected model…';
    try{const result=await api('ping',{kind,...providerFields(kind)});if(requestGeneration===generation)providerStatus.textContent=result.message+` (${result.latencyMs} ms)`;}
    catch(e){if(requestGeneration===generation)providerStatus.textContent=e.message;}
    finally{ping.disabled=false;}
  };
}
$('#build-index').onclick=async()=>{try{await saveSettings('embedding');const result=await api('index',{});$('#index-status').textContent=result.alreadyComplete?'Semantic index is already complete.':'Starting semantic index…';await refreshStatus();if(status.index.running&&!poll)poll=setInterval(refreshStatus,2000);}catch(e){$('#index-status').textContent=e.message;}};
async function refreshStatus(){
  try{
    status=await api('status');const idx=status.index,n=v=>Number(v||0).toLocaleString();
    $('#side-count').textContent=n(status.nodes)+' archive records';$('#corpus-count').innerHTML=n(status.nodes)+' records<br>'+n(status.conversations)+' conversations';
    $('#retrieval-label').textContent=idx.complete&&idx.configured?`Semantic index complete · ${n(idx.ready)} / ${n(idx.eligible)} dialogue vectors`:(status.vectors?`${n(idx.ready)} / ${n(idx.eligible)} dialogue vectors · partial semantic index`:'Exact search ready · semantic index not built');
    if($('#speaker').options.length===1)for(const s of status.speakers)$('#speaker').add(new Option(s,s));
    if($('#skill').options.length===1)for(const s of status.skills)$('#skill').add(new Option(s,s));
    let message;
    if(!idx.configured)message=`${n(idx.eligible)} dialogue records can be indexed. Save an embedding provider to start.`;
    else if(idx.running)message=`Building: ${n(idx.ready)} / ${n(idx.eligible)} eligible vectors (${Math.round(100*idx.ready/Math.max(1,idx.eligible))}%). ${n(idx.remaining)} remaining.`;
    else if(idx.complete)message=`Complete: ${n(idx.ready)} / ${n(idx.eligible)} eligible dialogue vectors. Nothing left to build.`;
    else message=`Incomplete: ${n(idx.ready)} / ${n(idx.eligible)} eligible vectors. ${n(idx.remaining)} remaining; resume the build.`;
    message+=` ${n(idx.excluded)} HUB, empty, or non-dialogue records are excluded.`;
    if(idx.excludedStored)message+=` ${n(idx.excludedStored)} older vectors for excluded records remain stored but are not searched.`;
    if(idx.error)message+=` Last build error: ${idx.error}`;
    $('#index-status').textContent=message;$('#index-status').className=idx.error?'notice':'';
    $('#build-index').disabled=idx.running;
    $('#build-index').textContent=idx.running?'Building semantic index…':idx.complete&&idx.configured?'Check semantic index':idx.ready?'Resume semantic index':'Build semantic index';
    if(idx.running&&!poll)poll=setInterval(refreshStatus,2000);
    if(!idx.running&&poll){clearInterval(poll);poll=null;}
  }catch(e){feedback(e.message,true);}
}

async function mobileInfo(){try{const s=await api('status');if(s.mobile)$('#mobile-info').textContent=`On the same Wi-Fi, open ${s.mobile.url} and enter access code: ${s.mobile.code}. Keep this computer running.`;}catch{}}
$('#settings-open').addEventListener('click',mobileInfo);
$('#login-form').onsubmit=async e=>{e.preventDefault();try{const r=await fetch('/api/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token:$('#access-code').value.trim()})});if(!r.ok)throw Error((await r.json()).error);$('#login-dialog').close();await refreshStatus();}catch(e){$('#login-error').textContent=e.message;}};
async function initializeChats(){await refreshStatus();if(!status.nodes)return;try{await refreshLibrary();const id=localStorage.getItem('minnie-current-chat');if(id&&library.chats.some(c=>c.id===id))await openChat(id);}catch(e){feedback(e.message,true);}}
initializeChats();

