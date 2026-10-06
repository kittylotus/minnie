export function initConsolidate({api,onRun}){
  const $=s=>document.querySelector(s),selected=new Map();let sequence=0,timer;
  const prompt=$('#consolidate-prompt'),status=$('#consolidate-status'),list=$('#conversation-list');
  const fallback='Summarize the selected full conversation trees. Make a detailed bullet list of the facts and claims, grouped by conversation and category. Attribute claims to their speakers, distinguish inference from explicit evidence, and preserve conditions and contradictory branches. Cite each factual bullet with individual [conversation:line] source IDs. Explain which conversations seem relevant for further research and why.';
  prompt.value=localStorage.getItem('minnie-consolidate-prompt')??fallback;
  prompt.oninput=()=>localStorage.setItem('minnie-consolidate-prompt',prompt.value);
  $('#consolidate-reset').onclick=()=>{prompt.value=fallback;localStorage.removeItem('minnie-consolidate-prompt');};
  function renderSelected(){
    const container=$('#conversation-selected');container.replaceChildren();
    for(const row of selected.values()){
      const button=document.createElement('button');button.type='button';button.className='secondary';
      button.textContent=`${row.id} · ${row.title} ×`;button.setAttribute('aria-label','Remove '+row.title);
      button.onclick=()=>{selected.delete(row.id);renderSelected();for(const box of list.querySelectorAll('input'))box.checked=selected.has(Number(box.value));};container.append(button);
    }
    $('#consolidate-run').disabled=!selected.size;$('#conversation-selection-count').textContent=`${selected.size} of 10 conversations selected`;
  }
  async function refresh(){
    const request=++sequence;status.textContent='Loading conversations…';
    try{
      const data=await api('conversations',{query:$('#conversation-filter').value});if(request!==sequence)return;
      list.replaceChildren();
      for(const row of data.conversations){
        const label=document.createElement('label'),box=document.createElement('input'),text=document.createElement('span'),detail=document.createElement('small');
        label.className='conversation-row';box.type='checkbox';box.value=row.id;box.checked=selected.has(row.id);
        text.textContent=row.title;detail.textContent=`${row.id} · ${row.records.toLocaleString()} records`;text.append(detail);label.append(box,text);list.append(label);
        box.onchange=()=>{if(box.checked&&selected.size>=10){box.checked=false;status.textContent='Select up to 10 conversations per summary.';return;}if(box.checked)selected.set(row.id,row);else selected.delete(row.id);renderSelected();};
      }
      status.textContent=data.more?'Showing 100 matches. Narrow the filter to find more conversations.':data.conversations.length?'Select entire conversations, including all branches.':'No conversations match this filter.';
    }catch(e){if(request===sequence)status.textContent=e.message;}
  }
  $('#conversation-filter').oninput=()=>{++sequence;clearTimeout(timer);timer=setTimeout(refresh,200);};
  $('#consolidate-run').onclick=()=>{
    const instructions=prompt.value.trim();if(!instructions){status.textContent='Enter summary instructions.';prompt.focus();return;}
    onRun({conversationIds:[...selected.keys()],query:instructions});
  };
  renderSelected();
  return {refresh,async add(id){
    const data=await api('conversations',{ids:[id]}),row=data.conversations[0];
    if(!row)throw Error('Conversation not found.');
    selected.clear();selected.set(row.id,row);$('#conversation-filter').value=row.title;renderSelected();await refresh();
  }};
}
