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

export function renderMarkdown(text,{citations=true}={}){
  const html=marked.parse(String(text||''),{gfm:true,breaks:false});
  const clean=DOMPurify.sanitize(html,{USE_PROFILES:{html:true},ALLOW_DATA_ATTR:false,FORBID_TAGS:['img','input','form','button','style','iframe'],FORBID_ATTR:['style']});
  const holder=document.createElement('div');holder.innerHTML=clean;
  holder.querySelectorAll('a').forEach(a=>{const href=a.getAttribute('href')||'';if(!/^(https?:|mailto:|#)/i.test(href)){a.removeAttribute('href');}else{a.target='_blank';a.rel='noopener noreferrer';}});
  if(citations){
    const walker=document.createTreeWalker(holder,NodeFilter.SHOW_TEXT);const nodes=[];
    while(walker.nextNode())if(!walker.currentNode.parentElement.closest('pre,code,a'))nodes.push(walker.currentNode);
    for(const node of nodes){
      const regex=/\[(\d+:\d+)\]/g;const text=node.textContent;let match,start=0;const fragment=document.createDocumentFragment();
      while((match=regex.exec(text))){fragment.append(document.createTextNode(text.slice(start,match.index)));const b=document.createElement('button');b.className='citation';b.dataset.context=match[1];b.setAttribute('aria-label','Open source '+match[1]);b.textContent=match[0];fragment.append(b);start=regex.lastIndex;}
      if(start){fragment.append(document.createTextNode(text.slice(start)));node.replaceWith(fragment);}
    }
  }
  return holder.innerHTML;
}
