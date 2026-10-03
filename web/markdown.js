import {marked} from './vendor/marked.esm.js';
import DOMPurify from './vendor/purify.es.mjs';

export function evidenceMarkdown(nodes){
  const conversations=new Map();
  for(const n of nodes){
    const conversation=String(n.conversation??String(n.id||'').split(':')[0]);
    if(!conversations.has(conversation))conversations.set(conversation,{title:n.title||'Untitled conversation',lines:[]});
    const text=String(n.speaker||'').trim().toUpperCase()==='HUB'?'Dialogue choice point':String(n.text||'');
    conversations.get(conversation).lines.push(`${n.speaker||'Unknown speaker'} - ${text}\n\nSource: [${n.id}]`);
  }
  return [...conversations].map(([id,group])=>`## ${group.title} (conversation ${id})\n\n${group.lines.join('\n\n')}`).join('\n\n- - -\n\n')+(nodes.length?'\n':'');
}

export function citationGroups(text){return [...String(text).matchAll(/\[\s*\d+:\d+(?:\s*[,;]\s*\d+:\d+)*\s*\]/g)].map(m=>({text:m[0],index:m.index,ids:m[0].match(/\d+:\d+/g)}));}

export function renderMarkdown(text,{citations=true}={}){
  const html=marked.parse(String(text||''),{gfm:true,breaks:false});
  const clean=DOMPurify.sanitize(html,{USE_PROFILES:{html:true},ALLOW_DATA_ATTR:false,FORBID_TAGS:['img','input','form','button','style','iframe'],FORBID_ATTR:['style']});
  const holder=document.createElement('div');holder.innerHTML=clean;
  holder.querySelectorAll('a').forEach(a=>{const href=a.getAttribute('href')||'';if(!/^(https?:|mailto:|#)/i.test(href)){a.removeAttribute('href');}else{a.target='_blank';a.rel='noopener noreferrer';}});
  if(citations){
    const walker=document.createTreeWalker(holder,NodeFilter.SHOW_TEXT);const nodes=[];
    while(walker.nextNode())if(!walker.currentNode.parentElement.closest('pre,code,a'))nodes.push(walker.currentNode);
    for(const node of nodes){
      const text=node.textContent;let start=0;const fragment=document.createDocumentFragment();
      for(const group of citationGroups(text)){fragment.append(document.createTextNode(text.slice(start,group.index)));group.ids.forEach((id,index)=>{if(index)fragment.append(document.createTextNode(' '));const b=document.createElement('button');b.className='citation';b.dataset.context=id;b.setAttribute('aria-label','Open source '+id);b.textContent='['+id+']';fragment.append(b);});start=group.index+group.text.length;}
      if(start){fragment.append(document.createTextNode(text.slice(start)));node.replaceWith(fragment);}
    }
  }
  return holder.innerHTML;
}

export function evidenceInFolder(items,folder){return items.filter(n=>folder==='all'||(n.folderId||'')===folder);}
export function evidenceForExport(items,folder,selected){const rows=evidenceInFolder(items,folder);return selected.size?rows.filter(n=>selected.has(n.id)):rows;}
export function moveEvidenceItems(items,ids,folderId){return items.map(n=>ids.has(n.id)?{...n,folderId}:n);}
export function unfileEvidenceFolder(items,folderId){return items.map(n=>n.folderId===folderId?{...n,folderId:''}:n);}
export function contextPlainText(root){
  const blocks=new Set(['P','DIV','ARTICLE','SECTION','DETAILS','SUMMARY','OL','LI','H2']);
  function read(n){
    if(n.nodeType===3)return n.nodeValue;
    if(n.nodeType!==1)return '';
    if(n.matches('svg,script,style,.card-actions button,#context-back'))return '';
    const text=[...n.childNodes].map(read).join('');
    if(n.matches('.card-top'))return [...n.children].map(read).join(' · ')+'\n\n';
    if(n.matches('.choice-speaker'))return text+'\n\n';
    if(n.tagName==='BR')return '\n';
    return blocks.has(n.tagName)?'\n\n'+text+'\n\n':text;
  }
  return read(root).replace(/[ \t]+\n/g,'\n').replace(/\n{3,}/g,'\n\n').trim();
}
