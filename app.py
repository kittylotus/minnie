"""Minnie: a local, evidence-first FAYDE research desk. Python 3.12+, no dependencies."""
import logging, logging.handlers, urllib.error
import argparse, array, collections, concurrent.futures, difflib, hashlib, http.cookies, json, math, os, pathlib, re, secrets, socket, sqlite3, threading, time, urllib.request, uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = pathlib.Path(__file__).resolve().parent
DATA = ROOT / 'data'
DATA.mkdir(exist_ok=True)
SOURCE = next((ROOT / 'source').glob('*.db'))
INDEX = DATA / 'normalized.sqlite'
CONFIG = DATA / 'settings.json'
CHATS = DATA / 'chats.sqlite'
ACCESS = DATA / 'access.json'
PRESETS=DATA/'presets.json'
PRESET_LOCK=threading.Lock()
MAIN_PROMPT='You research the Disco Elysium Jamais Vu corpus. All game facts must be supported by retrieved dialogue, not recalled training data. Cite every factual claim using only source IDs returned by tools. Clearly label inference. Do not invent lore or relationships. Explain when evidence is insufficient. Preserve attribution: an NPC claim is not necessarily an objective fact. Use tools to investigate. Search again if evidence is weak. Try ordinary words, synonyms, and alternate phrasings as well as specialist terms; do not claim exhaustive coverage without checking. Prior assistant answers are conversation context, not independent evidence. Resolve follow-up questions using chat history and additional supporting dialogue.'
CHAT_PROMPT='You are a helpful assistant. No archive search or database tools are available in this mode. Help with general questions, editing and formatting supplied text. Do not claim to have searched or verified the archive.'
ACCESS_LOCK=threading.Lock()
SKILLS = {'Logic','Encyclopedia','Rhetoric','Drama','Conceptualization','Visual Calculus','Volition','Inland Empire','Empathy','Authority','Esprit de Corps','Suggestion','Endurance','Pain Threshold','Physical Instrument','Electrochemistry','Shivers','Half Light','Hand/Eye Coordination','Perception','Reaction Speed','Savoir Faire','Interfacing','Composure'}
LOCK = threading.Lock()
STATUS = {'running': False, 'done': 0, 'total': 0, 'error': None}
MOBILE = None
LOG=logging.getLogger('minnie')
ELIGIBLE_CACHE={}
INVENTORY_LOCK=threading.Lock()
RUN_LOCK=threading.RLock()
RUNS={}
JOBS={}

class GenerationStopped(Exception):pass

class RunControl:
    def __init__(self):
        self.cancelled=threading.Event();self.response=None;self.condition=threading.Condition();self.state=None;self.result=None;self.previous_reasons=[];self.current_reason='';self.last_save=0
    def check(self):
        if self.cancelled.is_set():raise GenerationStopped('Response stopped.')
    def stop(self):
        self.cancelled.set()
        if self.response:
            threading.Thread(target=self.response.close,daemon=True).start()
    def publish(self,event,data):
        with self.condition:
            if self.state['status']!='pending':return
            if event=='round':
                if self.current_reason:self.previous_reasons.append(self.current_reason)
                self.current_reason='';self.state.update(answer='',reasoning='\n\n'.join(self.previous_reasons),message=data['message'])
            elif event=='delta':
                self.current_reason=data.get('reasoning','');self.state.update(answer=data.get('answer',''),reasoning='\n\n'.join([*self.previous_reasons,self.current_reason]).strip())
            elif event=='status':self.state['message']=data['message']
            elif event in ('complete','error','stopped'):
                self.state.update(status=event,error=data.get('error'),message=data.get('message',''));self.result=data.get('result')
            self.state['sequence']+=1;snapshot=dict(self.state);self.condition.notify_all()
        now=time.monotonic()
        if event!='delta' or now-self.last_save>=1:
            with RUN_LOCK:
                if RUNS.get(snapshot['turnId']) is self:
                    with chat_db() as c:c.execute('UPDATE turns SET progress=? WHERE id=?',(json.dumps(snapshot,ensure_ascii=False),snapshot['turnId']))
            self.last_save=now

def stop_turn(chat_id,turn_id,partial=None):
    with RUN_LOCK:
        control=RUNS.get(turn_id)
        chat=get_chat(chat_id)
        turn=next((t for t in chat['turns'] if t['id']==turn_id),None)
        if not turn:raise ValueError('Response not found in this chat.')
        if turn['status']!='pending':return {'stopped':False}
        if not control:raise ValueError('This response is not running on this server.')
        control.stop()
        with control.condition:partial=dict(control.state) if control.state else partial or {}
        result={'answer':str(partial.get('answer',''))[:200000],'reasoning':str(partial.get('reasoning',''))[:200000],'evidence':[],'retrieved':[],'trace':[],'citationWarning':False,'semantic':False,'mode':'chat' if turn.get('request',{}).get('depth')=='chat' else 'stopped'}
        finish_turn(turn_id,result=result,error='Response stopped.',status='stopped')
        if control.state:control.publish('stopped',{'message':'Response stopped.','result':result})
        return {'stopped':True}

def configure_logging():
    LOG.setLevel(logging.INFO)
    formatter=logging.Formatter('%(asctime)s [%(levelname)s] %(message)s',datefmt='%H:%M:%S')
    for handler in (logging.StreamHandler(),logging.handlers.RotatingFileHandler(DATA/'minnie.log',maxBytes=2_000_000,backupCount=3,encoding='utf-8')):
        handler.setFormatter(formatter);LOG.addHandler(handler)
    LOG.info('Minnie is starting. Diagnostic log: %s',DATA/'minnie.log')

def password_hash(password,salt):
    return hashlib.pbkdf2_hmac('sha256',password.encode('utf-8'),bytes.fromhex(salt),260000).hex()

def write_access(state):
    temporary=ACCESS.with_suffix('.tmp')
    temporary.write_text(json.dumps(state),encoding='utf-8');temporary.replace(ACCESS)

def load_access():
    with ACCESS_LOCK:
        if ACCESS.exists():return json.loads(ACCESS.read_text(encoding='utf-8'))
        alphabet='abcdefghjkmnpqrstuvwxyz23456789'
        code='-'.join(''.join(secrets.choice(alphabet) for _ in range(4)) for _ in range(3))
        salt=secrets.token_hex(16)
        state={'salt':salt,'passwordHash':password_hash(code,salt),'sessionToken':secrets.token_urlsafe(32),'generatedCode':code,'passwordSet':False}
        write_access(state);return state

def login_access(password):
    state=load_access()
    if not isinstance(password,str) or len(password)>128 or not secrets.compare_digest(password_hash(password,state['salt']),state['passwordHash']):raise ValueError('Access password does not match.')
    return state['sessionToken']

def change_access_password(password,confirmation):
    if not isinstance(password,str) or not 6<=len(password)<=128:raise ValueError('Use an access password between 6 and 128 characters.')
    if password!=confirmation:raise ValueError('The passwords do not match.')
    with ACCESS_LOCK:
        salt=secrets.token_hex(16)
        state={'salt':salt,'passwordHash':password_hash(password,salt),'sessionToken':secrets.token_urlsafe(32),'passwordSet':True}
        write_access(state)
    return state['sessionToken']

class ManagedConnection(sqlite3.Connection):
    def __exit__(self,*args):
        try:return super().__exit__(*args)
        finally:self.close()

def source():
    c = sqlite3.connect(SOURCE.as_uri() + '?mode=ro', uri=True,factory=ManagedConnection)
    c.row_factory = sqlite3.Row
    return c

def db():
    c = sqlite3.connect(INDEX, timeout=60,factory=ManagedConnection)
    c.row_factory = sqlite3.Row
    return c

def chat_db():
    c=sqlite3.connect(CHATS,timeout=30,factory=ManagedConnection);c.row_factory=sqlite3.Row
    c.execute('PRAGMA foreign_keys=ON')
    c.executescript('CREATE TABLE IF NOT EXISTS folders(id TEXT PRIMARY KEY,name TEXT NOT NULL,pinned INTEGER NOT NULL DEFAULT 0); CREATE TABLE IF NOT EXISTS chats(id TEXT PRIMARY KEY,title TEXT NOT NULL,folder_id TEXT REFERENCES folders(id) ON DELETE SET NULL,pinned INTEGER NOT NULL DEFAULT 0,created_at REAL NOT NULL,updated_at REAL NOT NULL); CREATE TABLE IF NOT EXISTS turns(id TEXT PRIMARY KEY,chat_id TEXT NOT NULL REFERENCES chats(id) ON DELETE CASCADE,question TEXT NOT NULL,result TEXT,status TEXT NOT NULL,error TEXT,created_at REAL NOT NULL); CREATE INDEX IF NOT EXISTS turns_chat ON turns(chat_id,created_at);')
    for name,definition in [('request','TEXT'),('variants','TEXT'),('variant_index','INTEGER NOT NULL DEFAULT -1'),('progress','TEXT')]:
        if name not in {r[1] for r in c.execute('PRAGMA table_info(turns)')}:
            try:c.execute(f'ALTER TABLE turns ADD COLUMN {name} {definition}')
            except sqlite3.OperationalError:
                if name not in {r[1] for r in c.execute('PRAGMA table_info(turns)')}:raise
    return c

def chat_list():
    with chat_db() as c:
        return {'chats':[dict(r) for r in c.execute('SELECT * FROM chats ORDER BY pinned DESC,updated_at DESC')],'folders':[dict(r) for r in c.execute('SELECT * FROM folders ORDER BY pinned DESC,name COLLATE NOCASE')]}

def get_chat(chat_id):
    with chat_db() as c:
        chat=c.execute('SELECT * FROM chats WHERE id=?',(chat_id,)).fetchone()
        if not chat:raise ValueError('Chat not found.')
        turns=[]
        for r in c.execute('SELECT * FROM turns WHERE chat_id=? ORDER BY created_at',(chat_id,)):
            turn=dict(r);turn['result']=json.loads(turn['result']) if turn['result'] else None;turn['request']=json.loads(turn['request']) if turn['request'] else {};turn['variants']=json.loads(turn['variants']) if turn['variants'] else [];turn['progress']=json.loads(turn['progress']) if turn['progress'] else None;turns.append(turn)
        return {**dict(chat),'turns':turns}

def manage_chats(action, **fields):
    ident=fields.get('id');name=str(fields.get('name','')).strip()[:120]
    with chat_db() as c:
        if action=='createFolder':
            if not name:raise ValueError('Enter a folder name.')
            ident=uuid.uuid4().hex;c.execute('INSERT INTO folders(id,name) VALUES(?,?)',(ident,name))
        elif action=='renameFolder':
            if not name:raise ValueError('Enter a folder name.')
            if not c.execute('UPDATE folders SET name=? WHERE id=?',(name,ident)).rowcount:raise ValueError('Folder not found.')
        elif action=='deleteFolder':c.execute('DELETE FROM folders WHERE id=?',(ident,))
        elif action=='pinFolder':c.execute('UPDATE folders SET pinned=? WHERE id=?',(int(bool(fields.get('pinned'))),ident))
        elif action=='renameChat':
            if not name:raise ValueError('Enter a chat name.')
            if not c.execute('UPDATE chats SET title=? WHERE id=?',(name,ident)).rowcount:raise ValueError('Chat not found.')
        elif action=='pinChat':c.execute('UPDATE chats SET pinned=? WHERE id=?',(int(bool(fields.get('pinned'))),ident))
        elif action=='moveChat':
            folder=fields.get('folderId') or None
            if folder and not c.execute('SELECT 1 FROM folders WHERE id=?',(folder,)).fetchone():raise ValueError('Folder not found.')
            if not c.execute('UPDATE chats SET folder_id=? WHERE id=?',(folder,ident)).rowcount:raise ValueError('Chat not found.')
        elif action=='deleteChat':
            if c.execute("SELECT 1 FROM turns WHERE chat_id=? AND status='pending'",(ident,)).fetchone():raise ValueError('Wait for this chat’s answer to finish before deleting it.')
            c.execute('DELETE FROM chats WHERE id=?',(ident,))
        else:raise ValueError('Unknown chat action.')
    return {'id':ident,'saved':True}

def begin_turn(payload):
    question=str(payload.get('query','')).strip()[:8000]
    if not question:raise ValueError('Enter a research question.')
    chat_id=payload.get('chatId') or uuid.uuid4().hex;turn_id=uuid.uuid4().hex;now=time.time()
    with chat_db() as c:
        c.execute('BEGIN IMMEDIATE')
        chat=c.execute('SELECT * FROM chats WHERE id=?',(chat_id,)).fetchone()
        if payload.get('chatId') and not chat:raise ValueError('Chat not found.')
        if not chat:
            folder=payload.get('folderId') or None
            if folder and not c.execute('SELECT 1 FROM folders WHERE id=?',(folder,)).fetchone():raise ValueError('Folder not found.')
            c.execute('INSERT INTO chats VALUES(?,?,?,?,?,?)',(chat_id,question[:72],folder,0,now,now))
        if c.execute("SELECT 1 FROM turns WHERE chat_id=? AND status='pending'",(chat_id,)).fetchone():raise ValueError('This chat already has a response in progress.')
        request=json.dumps({k:payload[k] for k in ('depth','verbosity','speaker','skill','presetId','promptSnapshot') if k in payload})
        if payload.get('retryTurnId'):
            old=c.execute('SELECT * FROM turns WHERE chat_id=? ORDER BY created_at DESC LIMIT 1',(chat_id,)).fetchone()
            if not old or old['id']!=payload['retryTurnId']:raise ValueError('Only the latest response can be retried.')
            if old['question']!=question:raise ValueError('Retry must use the original question.')
            turn_id=old['id']
            if not old['variants']:
                previous={'result':json.loads(old['result']) if old['result'] else None,'status':old['status'],'error':old['error'],'request':json.loads(old['request']) if old['request'] else {}}
                c.execute('UPDATE turns SET variants=? WHERE id=?',(json.dumps([previous],ensure_ascii=False),turn_id))
            c.execute("UPDATE turns SET result=NULL,status='pending',error=NULL,request=? WHERE id=?",(request,turn_id))
        else:c.execute('INSERT INTO turns(id,chat_id,question,result,status,error,created_at,request) VALUES(?,?,?,?,?,?,?,?)',(turn_id,chat_id,question,None,'pending',None,now,request))
        c.execute('UPDATE chats SET updated_at=? WHERE id=?',(now,chat_id))
    return chat_id,turn_id

def finish_turn(turn_id,result=None,error=None,status=None):
    with chat_db() as c:
        c.execute('BEGIN IMMEDIATE')
        turn=c.execute('SELECT * FROM turns WHERE id=?',(turn_id,)).fetchone()
        if not turn:return
        variants=json.loads(turn['variants']) if turn['variants'] else []
        state=status or ('complete' if result else 'error')
        variants.append({'result':result,'status':state,'error':error,'request':json.loads(turn['request']) if turn['request'] else {}})
        c.execute('UPDATE turns SET result=?,status=?,error=?,variants=?,variant_index=? WHERE id=?',(json.dumps(result,ensure_ascii=False) if result else None,state,error,json.dumps(variants,ensure_ascii=False),len(variants)-1,turn_id))
        c.execute('UPDATE chats SET updated_at=? WHERE id=(SELECT chat_id FROM turns WHERE id=?)',(time.time(),turn_id))

def select_variant(chat_id,turn_id,index):
    with chat_db() as c:
        c.execute('BEGIN IMMEDIATE')
        turn=c.execute('SELECT * FROM turns WHERE id=? AND chat_id=?',(turn_id,chat_id)).fetchone()
        if not turn:raise ValueError('Response not found in this chat.')
        if c.execute("SELECT 1 FROM turns WHERE chat_id=? AND status='pending'",(chat_id,)).fetchone():raise ValueError('Stop the current response before comparing alternatives.')
        variants=json.loads(turn['variants']) if turn['variants'] else []
        index=int(index)
        if index<0 or index>=len(variants):raise ValueError('Response alternative not found.')
        variant=variants[index]
        c.execute('UPDATE turns SET result=?,status=?,error=?,request=?,variant_index=? WHERE id=?',(json.dumps(variant['result'],ensure_ascii=False) if variant['result'] else None,variant['status'],variant['error'],json.dumps(variant['request']),index,turn_id))
    return get_chat(chat_id)

def chat_history(chat_id):
    if not chat_id:return []
    turns=[t for t in get_chat(chat_id)['turns'] if t['status']=='complete']
    selected=[];size=0
    for turn in reversed(turns[-12:]):
        amount=len(turn['question'])+len(turn['result'].get('answer',''))
        if size+amount>48000:break
        selected.append(turn);size+=amount
    return list(reversed(selected))

def settings():
    return json.loads(CONFIG.read_text()) if CONFIG.exists() else {'llm': {}, 'embedding': {}, 'customInstructions': ''}

def default_preset(conf=None):
    return {'id':'default','name':'Archive researcher','mainPrompt':MAIN_PROMPT,'chatPrompt':CHAT_PROMPT,'blocks':[{'id':'persona','title':'Assistant persona','content':(conf or {}).get('customInstructions',''),'enabled':True,'scope':'both'},{'id':'citations','title':'Citation formatting','content':'Use one source per square bracket: [28:353] [28:765]. Never combine multiple IDs in one bracket. Place citations next to the supported claim.','enabled':True,'scope':'research'}]}

def load_presets():
    with PRESET_LOCK:
        if PRESETS.exists():return json.loads(PRESETS.read_text(encoding='utf-8'))
        state={'activeId':'default','presets':[default_preset(settings())]}
        write_presets(state);return state

def write_presets(state):
    temporary=PRESETS.with_suffix('.tmp');temporary.write_text(json.dumps(state,ensure_ascii=False),encoding='utf-8');temporary.replace(PRESETS)

def clean_preset(value,ident):
    name=str(value.get('name','')).strip()[:80]
    if not name:raise ValueError('Give the preset a name.')
    blocks=value.get('blocks',[])
    if not isinstance(blocks,list) or len(blocks)>32:raise ValueError('Use up to 32 prompt blocks.')
    cleaned=[]
    for block in blocks:
        if not isinstance(block,dict):raise ValueError('Invalid prompt block.')
        scope=block.get('scope','both')
        if scope not in ('both','research','chat'):raise ValueError('Choose a valid block mode.')
        cleaned.append({'id':uuid.uuid4().hex,'title':str(block.get('title','Prompt block'))[:80],'content':str(block.get('content',''))[:12000],'enabled':bool(block.get('enabled',True)),'scope':scope})
    return {'id':ident,'name':name,'mainPrompt':str(value.get('mainPrompt',MAIN_PROMPT))[:24000],'chatPrompt':str(value.get('chatPrompt',CHAT_PROMPT))[:12000],'blocks':cleaned}

def manage_presets(payload):
    load_presets()
    with PRESET_LOCK:
        state=json.loads(PRESETS.read_text(encoding='utf-8'));action=payload.get('action');ident=payload.get('id')
        selected=next((p for p in state['presets'] if p['id']==ident),None)
        if action=='create':
            if len(state['presets'])>=24:raise ValueError('Use up to 24 presets.')
            ident=uuid.uuid4().hex;selected=clean_preset(payload.get('preset') or default_preset(settings()),ident)
            state['presets'].append(selected);state['activeId']=ident
        elif action=='save':
            if not selected:raise ValueError('Preset not found.')
            state['presets'][state['presets'].index(selected)]=clean_preset(payload['preset'],ident)
        elif action=='select':
            if not selected:raise ValueError('Preset not found.')
            state['activeId']=ident
        elif action=='delete':
            if not selected:raise ValueError('Preset not found.')
            if len(state['presets'])==1:raise ValueError('Keep at least one preset.')
            state['presets']=[p for p in state['presets'] if p['id']!=ident]
            if state['activeId']==ident:state['activeId']=state['presets'][0]['id']
        else:raise ValueError('Unknown preset action.')
        write_presets(state);return state

def preset_snapshot(ident=None):
    state=load_presets();ident=ident or state['activeId']
    selected=next((p for p in state['presets'] if p['id']==ident),None)
    if not selected:raise ValueError('Preset not found.')
    return selected

def preset_instructions(preset,mode):
    main=preset['chatPrompt'] if mode=='chat' else preset['mainPrompt']
    blocks=[b['content'] for b in preset['blocks'] if b['enabled'] and b['scope'] in ('both',mode)]
    return '\n\n'.join([main,*blocks])

def verify_citations(answer,evidence):
    ids=[];invalid=[]
    def replace(match):
        sources=re.findall(r'\d+:\d+',match[0]);ids.extend(sources)
        invalid.extend(i for i in sources if i not in evidence)
        return ' '.join('['+i+']' if i in evidence else '[unverified source]' for i in sources)
    answer=re.sub(r'\[\s*\d+:\d+(?:\s*[,;]\s*\d+:\d+)*\s*\]',replace,answer)
    return answer,ids,invalid

def initialize():
    digest = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    with db() as c:
        c.executescript('CREATE TABLE IF NOT EXISTS manifest(key TEXT PRIMARY KEY,value TEXT); CREATE TABLE IF NOT EXISTS vectors(id TEXT PRIMARY KEY,model TEXT,vector BLOB);')
        old = c.execute("SELECT value FROM manifest WHERE key='sourceHash'").fetchone()
        if old and old[0] == digest:
            c.execute("UPDATE nodes SET skill='Perception' WHERE speaker LIKE 'Perception (%' AND skill!='Perception'")
            initialize_edges(c)
            return
        print('Building dialogue index…', flush=True)
        c.executescript('DROP TABLE IF EXISTS nodes; DROP TABLE IF EXISTS search; DELETE FROM vectors; CREATE TABLE nodes(id TEXT PRIMARY KEY, conversation INTEGER,line INTEGER,speaker TEXT,skill TEXT,text TEXT,title TEXT,conditions TEXT,alternates TEXT); CREATE INDEX nodes_conversation ON nodes(conversation,line); CREATE VIRTUAL TABLE search USING fts5(id UNINDEXED,text,speaker,title,tokenize="unicode61");')
        with source() as s:
            alts = collections.defaultdict(list)
            for r in s.execute('SELECT * FROM alternates'):
                alts[(r['conversationid'],r['dialogueid'])].append({'condition':r['condition'],'text':r['alternateline']})
            rows=[]
            for r in s.execute('SELECT d.*,a.name speaker,c.title conversation_title FROM dentries d LEFT JOIN actors a ON a.id=d.actor LEFT JOIN dialogues c ON c.id=d.conversationid'):
                speaker=r['speaker'] or 'Unknown'
                text=r['dialoguetext'] or ''
                alternatives=alts[(r['conversationid'],r['id'])]
                if not text and not alternatives: continue
                skill='Perception' if speaker.startswith('Perception (') else speaker if speaker in SKILLS else ''
                rows.append((f"{r['conversationid']}:{r['id']}",r['conversationid'],r['id'],speaker,skill,text,r['conversation_title'] or '',r['conditionstring'] or '',json.dumps(alternatives)))
            c.executemany('INSERT INTO nodes VALUES(?,?,?,?,?,?,?,?,?)', rows)
            c.executemany('INSERT INTO search(id,text,speaker,title) VALUES(?,?,?,?)',[(r[0],r[5]+' '+ ' '.join(a['text'] or '' for a in json.loads(r[8])),r[3],r[6]) for r in rows])
        c.execute('INSERT OR REPLACE INTO manifest VALUES(?,?)',('sourceHash',digest))
        c.execute('INSERT OR REPLACE INTO manifest VALUES(?,?)',('chunkVersion','1'))
        c.execute('CREATE VIRTUAL TABLE IF NOT EXISTS vocabulary USING fts5vocab(search, row)')
        c.execute('DROP TABLE IF EXISTS edges')
        initialize_edges(c)
    print(f'Indexed {len(rows):,} dialogue nodes.', flush=True)

def initialize_edges(c):
    if c.execute("SELECT 1 FROM sqlite_master WHERE name='edges'").fetchone(): return
    c.executescript('CREATE TABLE edges(originconversationid INTEGER,origindialogueid INTEGER,destinationconversationid INTEGER,destinationdialogueid INTEGER,isConnector INTEGER,priority INTEGER); CREATE INDEX edges_origin ON edges(originconversationid,origindialogueid); CREATE INDEX edges_destination ON edges(destinationconversationid,destinationdialogueid);')
    with source() as s:c.executemany('INSERT INTO edges VALUES(?,?,?,?,?,?)',s.execute('SELECT * FROM dlinks'))

def node(node_id):
    with db() as c:
        r=c.execute('SELECT * FROM nodes WHERE id=?',(node_id,)).fetchone()
        return dict(r) if r else None

def meaningful_dialogue(n):
    text=(n['text'] or '')+' '+ ' '.join(a.get('text') or '' for a in json.loads(n['alternates'] or '[]'))
    return bool(re.search(r'[^\W\d_]',text,re.UNICODE)) and n['speaker']!='HUB'

def dialogue_branch(node_id, max_lines=100):
    """Follow deterministic links; expose forks without evaluating game state."""
    sequence=[]; seen=set(); choices=[]; stop='end'; choice_point=None
    with source() as s, db() as graph:
        def entry(ident):
            n=node(ident)
            if not n:return None
            conv,line=map(int,ident.split(':'))
            row=s.execute('SELECT isgroup,userscript,difficultypass FROM dentries WHERE conversationid=? AND id=?',(conv,line)).fetchone()
            n['structural']=bool(row['isgroup']) if row else n['speaker'].strip().upper()=='HUB'
            n['script']=row['userscript'] or '' if row else ''
            difficulty=row['difficultypass'] if row else 0
            n['passiveCheck']={'skill':n['speaker'],'estimatedSkill':(difficulty-7)*2-1 if difficulty>7 else difficulty*2} if difficulty else None
            n['checks']=[dict(r) for r in s.execute('SELECT * FROM checks WHERE conversationid=? AND dialogueid=?',(conv,line))]
            n['modifiers']=[dict(r) for r in s.execute('SELECT * FROM modifiers WHERE conversationid=? AND dialogueid=?',(conv,line))]
            return n
        current=node_id
        for _ in range(min(max(int(max_lines),1),100)):
            if current in seen:stop='cycle';break
            seen.add(current);n=entry(current)
            if not n:stop='missing';break
            if not n['structural']:sequence.append(n)
            conv,line=map(int,current.split(':'))
            links=graph.execute('SELECT * FROM edges WHERE originconversationid=? AND origindialogueid=? ORDER BY rowid',(conv,line)).fetchall()
            destinations=list(dict.fromkeys(f"{r['destinationconversationid']}:{r['destinationdialogueid']}" for r in links))
            if len(destinations)>1:
                choices=[item for dest in destinations if (item:=entry(dest))]
                choice_point=n;stop='choices' if n['structural'] else 'fork';break
            if not destinations:break
            current=destinations[0]
        else:stop='limit'
    return {'sequence':sequence,'choices':choices,'choicePoint':choice_point,'stop':stop,'continueAt':current if stop in ('cycle','limit') else None}

def context(node_id, depth=1, includeBranch=False):
    center=node(node_id)
    if not center: raise ValueError('Dialogue not found.')
    seen={node_id}; frontier=[node_id]; edges=[]
    with source() as s, db() as graph:
        for _ in range(min(max(int(depth),1),3)):
            nxt=[]
            for ident in frontier:
                conv,line=map(int,ident.split(':'))
                for r in graph.execute('SELECT * FROM edges WHERE (originconversationid=? AND origindialogueid=?) OR (destinationconversationid=? AND destinationdialogueid=?) LIMIT 60',(conv,line,conv,line)):
                    a=f"{r['originconversationid']}:{r['origindialogueid']}"; b=f"{r['destinationconversationid']}:{r['destinationdialogueid']}"
                    edges.append({'from':a,'to':b})
                    for key in (a,b):
                        if key not in seen and len(seen)<100: seen.add(key); nxt.append(key)
            frontier=nxt
        conv,line=map(int,node_id.split(':'))
        checks=[dict(r) for r in s.execute('SELECT * FROM checks WHERE conversationid=? AND dialogueid=?',(conv,line))]
        modifiers=[dict(r) for r in s.execute('SELECT * FROM modifiers WHERE conversationid=? AND dialogueid=?',(conv,line))]
    result={'center':center,'nodes':[n for key in sorted(seen) if (n:=node(key))], 'edges':edges,'checks':checks,'modifiers':modifiers}
    if includeBranch:result['branch']=dialogue_branch(node_id)
    return result

def provider_error(error):
    if isinstance(error,urllib.error.HTTPError):
        advice={401:'Check the API key.',403:'The provider denied access.',404:'Check the base URL and model ID.',429:'The provider rate-limited this request. Wait, then resume the build.'}.get(error.code,'The provider could not complete the request; retry later.' if error.code>=500 else 'Check the provider configuration.')
        return f'Provider returned HTTP {error.code}. {advice}'
    reason=error.reason if isinstance(error,urllib.error.URLError) else error
    if isinstance(reason,TimeoutError):return 'Provider request timed out. Saved batches remain available; retry or resume.'
    return f'Provider connection failed ({type(reason).__name__}). Check that the provider is running and the URL, model and key are correct.'

def provider(config, endpoint, payload=None):
    if not config.get('baseUrl'): raise ValueError('Set the provider URL in Settings first.')
    if payload is not None and not config.get('model'): raise ValueError('Set the provider model in Settings first.')
    url=config['baseUrl'].rstrip('/')+'/'+endpoint
    if not url.startswith(('https://','http://')): raise ValueError('Provider URL must use HTTP or HTTPS.')
    headers={'Accept':'application/json'}
    if config.get('apiKey'):headers['Authorization']='Bearer '+config['apiKey']
    if payload is not None:headers['Content-Type']='application/json'
    req=urllib.request.Request(url,json.dumps(payload).encode() if payload is not None else None,headers)
    try:
        with urllib.request.urlopen(req,timeout=180) as response: return json.load(response)
    except Exception as e: raise ValueError(provider_error(e)) from e

def list_models(kind, baseUrl=None, apiKey=None):
    if kind not in ('llm','embedding'):raise ValueError('Choose an answer or embedding provider.')
    config=dict(settings().get(kind,{}))
    if baseUrl is not None:
        url=str(baseUrl).strip().rstrip('/')
        # A saved credential belongs to its saved endpoint, not a newly typed URL.
        if url!=config.get('baseUrl','').rstrip('/'):config['apiKey']=''
        config['baseUrl']=url
    if apiKey:config['apiKey']=str(apiKey)
    response=provider(config,'models')
    data=response.get('data') if isinstance(response,dict) else None
    if not isinstance(data,list):raise ValueError('The provider returned an invalid model list; expected a data array.')
    models=sorted({item['id'] for item in data if isinstance(item,dict) and isinstance(item.get('id'),str) and item['id'].strip()},key=str.casefold)
    return {'models':models}

def provider_config(kind, baseUrl=None, apiKey=None, model=None):
    if kind not in ('llm','embedding'):raise ValueError('Choose an answer or embedding provider.')
    config=dict(settings().get(kind,{}))
    if baseUrl is not None:
        url=str(baseUrl).strip().rstrip('/')
        if url!=config.get('baseUrl','').rstrip('/'):config['apiKey']=''
        config['baseUrl']=url
    if apiKey:config['apiKey']=str(apiKey)
    if model is not None:config['model']=str(model).strip()
    return config

def save_settings(payload):
    with LOCK:
        old=settings()
        for kind in ('llm','embedding'):
            if kind not in payload:continue
            incoming=payload[kind]
            existing=old.get(kind,{})
            config={k:str(incoming.get(k,existing.get(k,''))).strip() if k!='apiKey' else str(incoming.get(k,existing.get(k,''))) for k in ('baseUrl','model','apiKey')}
            config['baseUrl']=config['baseUrl'].rstrip('/')
            if not incoming.get('apiKey'):
                config['apiKey']=existing.get('apiKey','') if config['baseUrl']==existing.get('baseUrl','').rstrip('/') else ''
            old[kind]=config
        if 'customInstructions' in payload:old['customInstructions']=str(payload['customInstructions'])[:12000]
        temp=CONFIG.with_suffix('.tmp');temp.write_text(json.dumps(old),encoding='utf-8');temp.replace(CONFIG)
    return {'saved':True}

def ping_provider(kind, **fields):
    config=provider_config(kind,**fields)
    if not config.get('model'):raise ValueError('Choose a model before testing the connection.')
    started=time.monotonic()
    if kind=='embedding':
        vector=embed(['Connection test.'],config)[0]
        details=f"Embedding model responded with {len(vector)} dimensions."
    else:
        result=provider(config,'chat/completions',{'model':config.get('model',''),'messages':[{'role':'user','content':'Reply with OK.'}],'max_tokens':32})
        if not isinstance(result.get('choices'),list) or not result['choices']:raise ValueError('The answer model returned no choices.')
        details='Answer model responded successfully.'
    return {'ok':True,'message':details,'latencyMs':round((time.monotonic()-started)*1000)}

REASON_TAGS=('think','thinking','reasoning','analysis')
def split_reasoning(content, final=False):
    """Parse cumulative text so tags split across network chunks never leak."""
    if not final:
        tags=[f'<{slash}{tag}>' for tag in (*REASON_TAGS,'final') for slash in ('','/')]
        for size in range(min(len(content),12),0,-1):
            suffix=content[-size:].lower()
            if any(tag.startswith(suffix) for tag in tags):content=content[:-size];break
    answer=[];reason=[];inside=False;start=0
    for m in re.finditer(r'</?(?:think|thinking|reasoning|analysis|final)>',content,re.I):
        (reason if inside else answer).append(content[start:m.start()])
        tag=m[0].lower()
        if 'final' not in tag:inside=not tag.startswith('</')
        start=m.end()
    (reason if inside else answer).append(content[start:])
    return ''.join(answer),''.join(reason)

def reasoning_text(delta):
    for key in ('reasoning_content','reasoning','reasoning_text'):
        if isinstance(delta.get(key),str) and delta[key]:return delta[key]
    details=delta.get('reasoning_details')
    if isinstance(details,list):return ''.join(d.get('text','') for d in details if isinstance(d,dict) and isinstance(d.get('text'),str))
    return ''

def sse_packets(response):
    lines=[]
    for raw in response:
        line=raw.decode('utf-8').rstrip('\r\n')
        if not line:
            if lines:yield '\n'.join(lines);lines=[]
        elif line.startswith('data:'):lines.append(line[5:].lstrip(' '))
    if lines:yield '\n'.join(lines)

def stream_completion(config,payload,emit,control=None):
    if not config.get('baseUrl') or not config.get('model'):raise ValueError('Set the answer provider URL and model first.')
    url=config['baseUrl'].rstrip('/')+'/chat/completions'
    if not url.startswith(('http://','https://')):raise ValueError('Provider URL must use HTTP or HTTPS.')
    headers={'Content-Type':'application/json','Accept':'text/event-stream'}
    if config.get('apiKey'):headers['Authorization']='Bearer '+config['apiKey']
    request=urllib.request.Request(url,json.dumps({**payload,'stream':True}).encode(),headers)
    content='';reasoning='';calls={};finished=False;field=None
    try:
        response=urllib.request.urlopen(request,timeout=180)
    except Exception as e:raise ValueError(provider_error(e)) from e
    if control:control.response=response
    with response:
        if control:control.check()
        if 'application/json' in response.headers.get('Content-Type',''):
            data=json.load(response)
            if not data.get('choices'):raise ValueError('Provider returned no completion.')
            message=data['choices'][0]['message']
            clean,tagged=split_reasoning(message.get('content') or '',final=True)
            emit('delta',{'answer':clean,'reasoning':reasoning_text(message)+tagged})
            return message
        for packet in sse_packets(response):
            if control:control.check()
            if packet=='[DONE]':finished=True;break
            data=json.loads(packet)
            if data.get('error'):raise ValueError('The provider reported a streaming error.')
            choices=data.get('choices') or []
            if not choices:continue
            choice=next((c for c in choices if c.get('index',0)==0),None)
            if choice is None:continue
            delta=choice.get('delta') or {}
            if delta.get('content'):content+=delta['content']
            chunk=reasoning_text(delta)
            if chunk:
                reasoning+=chunk
                field=next((k for k in ('reasoning_content','reasoning','reasoning_text') if delta.get(k)),None) or field
            for call in delta.get('tool_calls') or []:
                index=call.get('index',0)
                entry=calls.setdefault(index,{'id':'','type':'function','function':{'name':'','arguments':''}})
                if call.get('id'):entry['id']+=call['id']
                fn=call.get('function') or {}
                entry['function']['name']+=fn.get('name','')
                entry['function']['arguments']+=fn.get('arguments','')
            if choice.get('finish_reason') is not None:finished=True
            clean,tagged=split_reasoning(content)
            emit('delta',{'answer':clean,'reasoning':reasoning+tagged})
    if not finished:raise ValueError('The provider stream ended before completion. Please retry.')
    clean,tagged=split_reasoning(content,final=True)
    emit('delta',{'answer':clean,'reasoning':reasoning+tagged})
    message={'role':'assistant','content':content or None}
    if field:message[field]=reasoning
    if calls:message['tool_calls']=[calls[k] for k in sorted(calls)]
    return message

def embed(texts,config):
    out=provider(config,'embeddings',{'model':config['model'],'input':texts})
    vectors=[r['embedding'] for r in sorted(out['data'],key=lambda r:r['index'])]
    if len(vectors)!=len(texts) or not vectors or not vectors[0]: raise ValueError('Embedding provider returned an incomplete batch.')
    dim=len(vectors[0])
    if any(len(v)!=dim or any(not math.isfinite(x) for x in v) for v in vectors): raise ValueError('Invalid embedding vectors.')
    return vectors

def embedding_key(config): return config.get('baseUrl','')+'|'+config.get('model','')

def index_inventory(config):
    key=embedding_key(config)
    with db() as c:
        total=c.execute('SELECT count(*) FROM nodes').fetchone()[0]
        fingerprint=c.execute("SELECT value FROM manifest WHERE key='sourceHash'").fetchone()
        signature=(str(INDEX.resolve()),fingerprint[0] if fingerprint else '',total)
        with INVENTORY_LOCK:
            if signature not in ELIGIBLE_CACHE:
                ELIGIBLE_CACHE.clear()
                ELIGIBLE_CACHE[signature]=frozenset(r['id'] for r in c.execute('SELECT id,text,speaker,alternates FROM nodes') if meaningful_dialogue(r))
            eligible=ELIGIBLE_CACHE[signature]
        stored={r[0] for r in c.execute('SELECT id FROM vectors WHERE model=?',(key,))}
        failure=c.execute('SELECT value FROM manifest WHERE key=?',('indexError:'+key,)).fetchone()
    ready=len(eligible&stored)
    return {'eligible':len(eligible),'ready':ready,'remaining':len(eligible)-ready,'excluded':total-len(eligible),'stored':len(stored),'excludedStored':len(stored-eligible),'complete':len(eligible)==ready,'configured':bool(config.get('model') and config.get('baseUrl')),'lastError':failure[0] if failure else None}

def start_index(config):
    config=dict(config)
    with LOCK:
        if STATUS['running']:raise ValueError('Indexing is already running.')
        inventory=index_inventory(config)
        key=embedding_key(config)
        if inventory['complete']:
            STATUS.update(running=False,done=0,total=0,error=None,modelKey=key)
            with db() as c:c.execute('DELETE FROM manifest WHERE key=?',('indexError:'+key,))
            LOG.info('Semantic index already complete: %s / %s eligible dialogue vectors. No provider calls needed.',f"{inventory['ready']:,}",f"{inventory['eligible']:,}")
            return {'started':False,'alreadyComplete':True}
        STATUS.update(running=True,done=0,total=inventory['remaining'],error=None,modelKey=key)
        threading.Thread(target=index_vectors,args=(config,),daemon=True).start()
        return {'started':True,'alreadyComplete':False}

def index_vectors(config=None):
    conf=dict(config if config is not None else settings()['embedding']);key=embedding_key(conf)
    started=time.monotonic()
    try:
        inventory=index_inventory(conf)
        LOG.info('Semantic index: %s / %s ready; %s remaining; %s structural/empty records excluded. Model: %s',f"{inventory['ready']:,}",f"{inventory['eligible']:,}",f"{inventory['remaining']:,}",f"{inventory['excluded']:,}",conf.get('model','(unset)'))
        with db() as c:
            c.execute('DELETE FROM manifest WHERE key=?',('indexError:'+key,));c.commit()
            rows=[r for r in c.execute('SELECT * FROM nodes WHERE id NOT IN (SELECT id FROM vectors WHERE model=?) ORDER BY conversation,line',(key,)) if meaningful_dialogue(r)]
            STATUS.update(total=len(rows),done=0,error=None,modelKey=key)
            next_report=0
            for start in range(0,len(rows),32):
                batch=rows[start:start+32];texts=[]
                for r in batch:
                    ctx=context(r['id'])
                    nearby='\n'.join(n['speaker']+': '+n['text'] for n in ctx['nodes'] if n['id']!=r['id'])[:2400]
                    texts.append(f"Speaker: {r['speaker']}\nConversation: {r['title']}\n{r['text']}\nAlternate lines: {r['alternates']}\nBranch context:\n{nearby}")
                vectors=embed(texts,conf)
                c.executemany('INSERT OR REPLACE INTO vectors VALUES(?,?,?)',[(r['id'],key,array.array('f',v).tobytes()) for r,v in zip(batch,vectors)])
                c.commit();STATUS['done']=min(start+len(batch),len(rows))
                if time.monotonic()>=next_report or STATUS['done']==len(rows):
                    ready=inventory['ready']+STATUS['done']
                    LOG.info('Embedding progress: %s / %s (%.1f%%); %s remaining; %.0fs elapsed.',f'{ready:,}',f"{inventory['eligible']:,}",100*ready/max(1,inventory['eligible']),f"{inventory['eligible']-ready:,}",time.monotonic()-started)
                    next_report=time.monotonic()+10
            c.execute('INSERT OR REPLACE INTO manifest VALUES(?,?)',('embeddingModel',key))
        final=index_inventory(conf)
        LOG.info('Semantic index complete: %s / %s eligible vectors, %s excluded; %.0fs elapsed.',f"{final['ready']:,}",f"{final['eligible']:,}",f"{final['excluded']:,}",time.monotonic()-started)
    except Exception as e:
        STATUS['error']=str(e)
        LOG.error('Embedding build stopped after %s new vectors: %s. Saved batches are retained; select Resume semantic index to continue.',STATUS['done'],str(e))
        try:
            with db() as c:c.execute('INSERT OR REPLACE INTO manifest VALUES(?,?)',('indexError:'+key,str(e)))
        except Exception as persistence_error:
            LOG.error('Could not save the build error to the index: %s',persistence_error)
    finally:STATUS['running']=False

def search(query, mode='hybrid', speaker='', skill='', limit=30):
    limit=min(max(int(limit),1),150); query=query.strip()[:1000]
    if not query: return {'results':[], 'suggestion':None,'semantic':False}
    terms=re.findall(r"[\w'-]+",query)
    suggestion=None; scores={}; lexical={}; semantic={}; semantic_used=False
    with db() as c:
        if mode!='semantic' and terms:
            match=(' AND ' if mode=='exact' else ' OR ').join('"'+t.replace('"','')+'"' for t in terms)
            filt=''; args=[match]
            if speaker: filt+=' AND n.speaker=?'; args.append(speaker)
            if skill: filt+=' AND n.skill=?'; args.append(skill)
            hits=c.execute('SELECT n.*,bm25(search) rank FROM search JOIN nodes n ON n.id=search.id WHERE search MATCH ?'+filt+' ORDER BY rank LIMIT 300',args).fetchall()
            hits=[r for r in hits if meaningful_dialogue(r)]
            for rank,r in enumerate(hits): scores[r['id']]=1/(60+rank); lexical[r['id']]=float(r['rank'])
            if not hits and len(terms)<=3:
                vocab=[r[0] for r in c.execute('SELECT term FROM vocabulary WHERE length(term) BETWEEN ? AND ?',(max(3,len(terms[0])-2),len(terms[0])+2))]
                close=difflib.get_close_matches(terms[0].lower(),vocab,n=1,cutoff=.72)
                if close: suggestion=close[0]
        config=settings().get('embedding',{}); key=embedding_key(config)
        count=c.execute('SELECT count(*) FROM vectors WHERE model=?',(key,)).fetchone()[0]
        if mode=='semantic' and not count: raise ValueError('Build the semantic index in Settings before using semantic search.')
        if mode!='exact' and count:
            q=embed([query],config)[0]; norm=math.sqrt(sum(x*x for x in q)) or 1
            filt=''; args=[key]
            if speaker: filt+=' AND n.speaker=?';args.append(speaker)
            if skill: filt+=' AND n.skill=?';args.append(skill)
            best=[]
            import heapq
            for r in c.execute('SELECT v.id,v.vector,n.text,n.speaker,n.alternates FROM vectors v JOIN nodes n ON n.id=v.id WHERE v.model=?'+filt,args):
                if not meaningful_dialogue(r):continue
                v=array.array('f');v.frombytes(r['vector'])
                if len(v)!=len(q): raise ValueError('Embedding dimensions changed. Use a consistent provider/model and rebuild the index.')
                sim=sum(a*b for a,b in zip(q,v))/(norm*(math.sqrt(sum(x*x for x in v)) or 1))
                if len(best)<300:heapq.heappush(best,(sim,r['id']))
                elif sim>best[0][0]:heapq.heapreplace(best,(sim,r['id']))
            for rank,(sim,ident) in enumerate(sorted(best,reverse=True)):
                scores[ident]=scores.get(ident,0)+1/(60+rank);semantic[ident]=sim
            semantic_used=True
        results=[]
        for ident,score in sorted(scores.items(),key=lambda x:x[1],reverse=True):
            n=node(ident)
            if not meaningful_dialogue(n):continue
            n['retrieval']={'lexical':lexical.get(ident),'vector':semantic.get(ident),'combined':score};results.append(n)
            if len(results)>=limit:break
    return {'results':results,'suggestion':suggestion,'semantic':semantic_used,'indexedVectors':count}

def readonly_sql(sql):
    if not re.match(r'^\s*(SELECT|WITH)\b',sql,re.I): raise ValueError('Only SELECT queries and read-only CTEs are allowed.')
    allowed={sqlite3.SQLITE_SELECT,sqlite3.SQLITE_READ,sqlite3.SQLITE_FUNCTION,sqlite3.SQLITE_RECURSIVE}
    with source() as c:
        c.set_authorizer(lambda action,*args: sqlite3.SQLITE_OK if action in allowed and not(action==sqlite3.SQLITE_FUNCTION and str(args[1]).lower()=='load_extension') else sqlite3.SQLITE_DENY)
        deadline=time.monotonic()+3
        c.set_progress_handler(lambda: int(time.monotonic()>deadline),1000)
        cursor=c.execute(sql)
        rows=cursor.fetchmany(201)
        return {'columns':[d[0] for d in cursor.description], 'rows':[list(r) for r in rows[:200]],'truncated':len(rows)>200}

def research(payload, emit=None, control=None):
    conf=settings(); model=conf.get('llm',{})
    if not model.get('model'): raise ValueError('Configure your answer model in Settings. Dialogue search works without a model.')
    question=str(payload.get('query','')).strip()[:8000]
    if not question: raise ValueError('Enter a research question.')
    depth=payload.get('depth','research'); passes={'quick':2,'research':5,'exhaustive':9}.get(depth,5)
    history=chat_history(payload.get('chatId'))
    preset=payload.get('promptSnapshot') or default_preset(conf)
    if control:control.check()
    if depth=='chat':
        if emit:emit('round',{'round':1,'message':'Replying without searching…'})
        messages=[{'role':'system','content':preset_instructions(preset,'chat')+'\nAnswer length: '+payload.get('verbosity','balanced')}]
        for turn in history:messages.extend([{'role':'user','content':turn['question']},{'role':'assistant','content':turn['result'].get('answer','')}])
        messages.append({'role':'user','content':question})
        request={'model':model['model'],'messages':messages}
        response=stream_completion(model,request,emit,control) if emit else provider(model,'chat/completions',request)['choices'][0]['message']
        if control:control.check()
        answer,tagged=split_reasoning(response.get('content') or '',final=True)
        return {'answer':answer,'reasoning':reasoning_text(response)+tagged,'evidence':[],'retrieved':[],'trace':[],'citationWarning':False,'semantic':False,'mode':'chat'}
    evidence={n['id']:n for turn in history for n in turn['result'].get('evidence',[])};trace=[]
    def collect(result):
        for n in result.get('results',[]): evidence[n['id']]=n
        return result
    if emit:emit('status',{'message':'Searching dialogue and following branch context…'})
    first=collect(search(question,limit=20,speaker=payload.get('speaker',''),skill=payload.get('skill','')))
    if first.get('suggestion'):
        collect(search(first['suggestion'],limit=20))
        trace.append('Searched suggested spelling: '+first['suggestion'])
    for n in list(evidence.values())[:4]:
        for item in context(n['id'])['nodes']: evidence[item['id']]=item
    messages=[{'role':'system','content':preset_instructions(preset,'research')},{'role':'user','content':'Answer length: '+payload.get('verbosity','balanced')}]
    for turn in history:
        messages.extend([{'role':'user','content':turn['question']},{'role':'assistant','content':turn['result'].get('answer','')}])
    messages.extend([{'role':'user','content':question},{'role':'user','content':'Retrieved evidence (including cited sources from earlier turns):\n'+json.dumps(list(evidence.values()),ensure_ascii=False)}])
    definitions=[('search',{'query':{'type':'string'},'mode':{'type':'string','enum':['hybrid','exact','semantic']},'speaker':{'type':'string'},'skill':{'type':'string'}},['query']),('getContext',{'nodeId':{'type':'string'},'depth':{'type':'integer'}},['nodeId']),('getConversation',{'conversationId':{'type':'integer'}},['conversationId']),('findRelated',{'nodeIds':{'type':'array','items':{'type':'string'}}},['nodeIds']),('queryDatabase',{'sql':{'type':'string'}},['sql'])]
    tools=[{'type':'function','function':{'name':name,'description':name+' in the read-only FAYDE corpus','parameters':{'type':'object','properties':props,'required':req}}} for name,props,req in definitions]
    answer='';reasoning=[]
    for turn in range(passes+1):
        if control:control.check()
        request={'model':model['model'],'messages':messages,'tools':tools,'tool_choice':'none' if turn==passes else 'auto'}
        if emit:
            emit('round',{'round':turn+1,'message':'Reading the evidence…' if turn==0 else 'Following up on the evidence…'})
            response=stream_completion(model,request,emit,control)
        else:response=provider(model,'chat/completions',request)['choices'][0]['message']
        clean,tagged=split_reasoning(response.get('content') or '',final=True)
        reason=reasoning_text(response)+tagged
        if reason:reasoning.append(reason)
        calls=response.get('tool_calls',[])
        if not calls: answer=clean;break
        messages.append(response)
        for call in calls[:8]:
            if control:control.check()
            name=call['function']['name']
            try:
                args=json.loads(call['function']['arguments'])
                if name=='search': result=collect(search(**args,limit=30))
                elif name=='getContext':
                    result=context(args['nodeId'],args.get('depth',1))
                    for n in result['nodes']: evidence[n['id']]=n
                elif name=='getConversation':
                    with db() as c: result={'results':[dict(r) for r in c.execute('SELECT * FROM nodes WHERE conversation=? ORDER BY line LIMIT 200',(args['conversationId'],))]}
                    collect(result)
                elif name=='findRelated':
                    nodes=[node(i) for i in args['nodeIds'][:8]]
                    query=' '.join(n['text'] for n in nodes if n)[:1000]
                    result=collect(search(query,limit=20))
                elif name=='queryDatabase': result=readonly_sql(args['sql'])
                else: raise ValueError('Unknown tool')
                trace.append(name+': '+str(args)[:200])
                if emit:emit('status',{'message':'Following evidence: '+name})
            except Exception as e: result={'error':str(e)}
            messages.append({'role':'tool','tool_call_id':call['id'],'content':json.dumps(result,ensure_ascii=False)[:65000]})
        # Answer every tool call, including any beyond the per-turn cap.
        for call in calls[8:]: messages.append({'role':'tool','tool_call_id':call['id'],'content':'Tool budget reached.'})
    answer,ids,invalid=verify_citations(answer,evidence)
    return {'answer':answer,'reasoning':'\n\n'.join(reasoning),'evidence':[evidence[i] for i in dict.fromkeys(ids) if i in evidence], 'retrieved':list(evidence.values())[:100],'trace':trace,'citationWarning':bool(invalid) or bool(answer and not ids),'semantic':first['semantic']}

def create_run(payload):
    payload=dict(payload);snapshot=None
    if payload.get('retryTurnId') and payload.get('chatId'):
        previous=next((t for t in get_chat(payload['chatId'])['turns'] if t['id']==payload['retryTurnId']),None)
        if previous:snapshot=previous['request'].get('promptSnapshot')
    payload['promptSnapshot']=snapshot or preset_snapshot(payload.get('presetId'))
    payload['presetId']=payload['promptSnapshot']['id']
    with RUN_LOCK:
        chat_id,turn_id=begin_turn(payload);control=RunControl();run_id=uuid.uuid4().hex
        control.state={'chatId':chat_id,'turnId':turn_id,'runId':run_id,'status':'pending','sequence':0,'answer':'','reasoning':'','message':'Starting research…','error':None}
        RUNS[turn_id]=control;JOBS[run_id]=control
        for ident,old in list(JOBS.items()):
            if len(JOBS)<=128:break
            if old.state['status']!='pending':JOBS.pop(ident,None)
        control.publish('status',{'message':'Starting research…'})
    return {**payload,'chatId':chat_id},control


def execute_run(payload,control,emit=None,stream=True):
    chat_id=control.state['chatId'];turn_id=control.state['turnId']
    def checked_emit(event,data):
        nonlocal emit
        control.check();control.publish(event,data)
        if emit:
            try:emit(event,data)
            except OSError:emit=None
    try:
        checked_emit('chat',{'chatId':chat_id,'turnId':turn_id,'runId':control.state['runId']})
        result=research(payload,checked_emit if stream else None,control);result.update(chatId=chat_id,turnId=turn_id)
        with RUN_LOCK:
            control.check();finish_turn(turn_id,result)
            control.publish('complete',{'result':result})
        return result
    except Exception as e:
        with RUN_LOCK:
            if RUNS.get(turn_id) is control and not control.cancelled.is_set():
                finish_turn(turn_id,error=str(e));control.publish('error',{'error':str(e),'message':'Research failed.'})
        if control.cancelled.is_set():raise GenerationStopped('Response stopped.') from e
        raise
    finally:
        with RUN_LOCK:
            if RUNS.get(turn_id) is control:RUNS.pop(turn_id,None)


def start_research(payload):
    payload,control=create_run(payload)
    def work():
        try:execute_run(payload,control)
        except GenerationStopped:pass
        except Exception as e:LOG.error('Research job failed: %s',e)
    threading.Thread(target=work,daemon=True).start()
    return {k:control.state[k] for k in ('chatId','turnId','runId')}


def research_state(chatId,turnId,runId=None):
    with RUN_LOCK:
        control=JOBS.get(runId) if runId else RUNS.get(turnId)
        if control:
            if control.state['chatId']!=chatId or control.state['turnId']!=turnId:raise ValueError('Research job not found in this chat.')
            with control.condition:return {**control.state,'result':control.result}
    with chat_db() as c:turn=c.execute('SELECT * FROM turns WHERE id=? AND chat_id=?',(turnId,chatId)).fetchone()
    if not turn:raise ValueError('Research response not found.')
    state=json.loads(turn['progress']) if turn['progress'] else {'chatId':chatId,'turnId':turnId,'runId':runId,'sequence':0,'answer':'','reasoning':''}
    if runId and state.get('runId')!=runId:raise ValueError('This response has a newer alternative.')
    state.update(status=turn['status'],error=turn['error'],result=json.loads(turn['result']) if turn['result'] else None)
    if turn['status']!='pending':state['sequence']+=1
    return state


class Handler(BaseHTTPRequestHandler):
    def log_message(self,format,*args):
        # Routine polling and asset requests stay quiet. Never log request bodies or credentials.
        if len(args)>1 and str(args[1]).isdigit() and int(args[1])>=400:
            LOG.warning('HTTP %s %s',args[1],self.path.split('?')[0])

    def persistent_research(self,payload,emit=None):
        return execute_run(*create_run(payload),emit=emit,stream=emit is not None)
    def stream_research(self,payload):
        self.watch_research(start_research(payload))
    def watch_research(self,identity):
        initial=research_state(**identity)
        self.connection.settimeout(20)
        self.send_response(200);self.send_header('Content-Type','text/event-stream; charset=utf-8');self.send_header('Cache-Control','no-cache');self.send_header('X-Accel-Buffering','no');self.send_header('X-Content-Type-Options','nosniff');self.end_headers()
        def emit(event,data):
            self.wfile.write(('event: '+event+'\ndata: '+json.dumps(data,ensure_ascii=False)+'\n\n').encode());self.wfile.flush()
        try:
            emit('chat',{k:initial[k] for k in ('chatId','turnId','runId')})
            sequence=-1
            while True:
                state=research_state(**identity)
                if state['sequence']!=sequence:
                    emit('snapshot',state);sequence=state['sequence']
                if state['status']!='pending':
                    emit('done' if state['status']=='complete' else 'stopped' if state['status']=='stopped' else 'error',state.get('result') or {'error':state.get('error'),'message':state.get('message')});return
                with RUN_LOCK:control=JOBS.get(state['runId'])
                if not control:return
                with control.condition:
                    if control.state['sequence']==sequence:control.condition.wait(10)
                self.wfile.write(b': keep-alive\n\n');self.wfile.flush()
        except OSError:
            pass  # A subscriber disconnect never cancels the server's research job.
    def respond(self,value,status=200,kind='application/json',headers=None):
        body=(json.dumps(value,ensure_ascii=False).encode() if kind=='application/json' else value)
        self.send_response(status);self.send_header('Content-Type',kind);self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff')
        for key,value in (headers or {}).items():self.send_header(key,value)
        self.end_headers();self.wfile.write(body)
    def access_cookie(self,token):
        secure='; Secure' if self.headers.get('Origin')=='https://'+self.headers.get('Host','') else ''
        return f'minnie={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=15552000{secure}'
    def authorized(self):
        if self.client_address[0] in ('127.0.0.1','::1'): return True
        cookie=http.cookies.SimpleCookie(self.headers.get('Cookie',''))
        return 'minnie' in cookie and secrets.compare_digest(cookie['minnie'].value.encode('utf-8'),load_access()['sessionToken'].encode('utf-8'))
    def do_GET(self):
        path=self.path.split('?')[0]
        if path=='/api/status':
            if not self.authorized():return self.respond({'error':'Enter the access code shown on the desktop.'},401)
            with db() as c:
                counts=c.execute('SELECT count(*) nodes,count(DISTINCT conversation) conversations FROM nodes').fetchone()
                config=settings().get('embedding',{})
                speakers=[r[0] for r in c.execute('SELECT DISTINCT speaker FROM nodes ORDER BY speaker')]
            inventory=index_inventory(config)
            progress={**STATUS,**inventory}
            progress['running']=STATUS['running'] and STATUS.get('modelKey')==embedding_key(config)
            progress['error']=STATUS['error'] if STATUS.get('modelKey')==embedding_key(config) else None
            progress['error']=progress['error'] or inventory['lastError']
            mobile={**MOBILE,'code':load_access().get('generatedCode'),'passwordSet':load_access()['passwordSet']} if MOBILE and self.client_address[0] in ('127.0.0.1','::1') else None
            return self.respond({'nodes':counts[0],'conversations':counts[1],'vectors':inventory['ready'],'index':progress,'speakers':speakers,'skills':sorted(SKILLS),'mobile':mobile})
        if path=='/api/settings':
            if not self.authorized():return self.respond({'error':'Access code required.'},401)
            conf=settings()
            for key in ('llm','embedding'):
                conf[key]['hasKey']=bool(conf[key].get('apiKey'));conf[key].pop('apiKey',None)
            state=load_access();conf['access']={'passwordSet':state['passwordSet']}
            if self.client_address[0] in ('127.0.0.1','::1') and state.get('generatedCode'):conf['access']['generatedCode']=state['generatedCode']
            return self.respond(conf)
        if path=='/api/research/active':
            if not self.authorized():return self.respond({'error':'Access code required.'},401)
            with chat_db() as c:active=[{'chatId':r['chat_id'],'turnId':r['id']} for r in c.execute("SELECT id,chat_id FROM turns WHERE status='pending' ORDER BY created_at DESC")]
            return self.respond(active)
        if path=='/api/presets':
            if not self.authorized():return self.respond({'error':'Access code required.'},401)
            return self.respond(load_presets())
        if path=='/api/chats':
            if not self.authorized():return self.respond({'error':'Access code required.'},401)
            return self.respond(chat_list())
        files={'/research.js':('research.js','text/javascript; charset=utf-8'),'/presets.js':('presets.js','text/javascript; charset=utf-8'),'/icons.js':('icons.js','text/javascript; charset=utf-8'),'/vendor/lucide.svg':('vendor/lucide.svg','image/svg+xml'),'/':('index.html','text/html; charset=utf-8'),'/app.js':('app.js','text/javascript; charset=utf-8'),'/markdown.js':('markdown.js','text/javascript; charset=utf-8'),'/vendor/marked.esm.js':('vendor/marked.esm.js','text/javascript; charset=utf-8'),'/vendor/purify.es.mjs':('vendor/purify.es.mjs','text/javascript; charset=utf-8'),'/style.css':('style.css','text/css; charset=utf-8'),'/favicon.svg':('favicon.svg','image/svg+xml')}
        if path in files:
            name,kind=files[path];return self.respond((ROOT/'web'/name).read_bytes(),kind=kind)
        self.respond({'error':'Not found'},404)
    def do_POST(self):
        origin=self.headers.get('Origin')
        if origin and origin not in ('http://'+self.headers.get('Host',''),'https://'+self.headers.get('Host','')):return self.respond({'error':'Cross-origin request refused.'},403)
        try:
            size=int(self.headers.get('Content-Length',0))
            if size>(2000000 if self.path in ('/api/research/stop','/api/presets/manage') else 100000):raise ValueError('Request too large.')
            payload=json.loads(self.rfile.read(size) or '{}')
            if self.path=='/api/login':
                try:token=login_access(payload.get('password',payload.get('token','')))
                except ValueError as e:return self.respond({'error':str(e)},401)
                return self.respond({'connected':True},headers={'Set-Cookie':self.access_cookie(token)})
            if not self.authorized():return self.respond({'error':'Access code required.'},401)
            if self.path=='/api/access/password':
                token=change_access_password(payload.get('password'),payload.get('confirmation'))
                return self.respond({'saved':True},headers={'Set-Cookie':self.access_cookie(token)})
            if self.path=='/api/presets/manage':return self.respond(manage_presets(payload))
            if self.path=='/api/search': return self.respond(search(**payload))
            if self.path=='/api/context': return self.respond(context(payload['nodeId'],payload.get('depth',1),bool(payload.get('includeBranch',False))))
            if self.path=='/api/research': return self.respond(self.persistent_research(payload))
            if self.path=='/api/research/stop':return self.respond(stop_turn(payload['chatId'],payload['turnId'],payload.get('partial')))
            if self.path=='/api/research/stream':return self.stream_research(payload)
            if self.path=='/api/research/start':return self.respond(start_research(payload))
            if self.path=='/api/research/events':return self.watch_research(payload)
            if self.path=='/api/research/state':return self.respond(research_state(**payload))
            if self.path=='/api/sql': return self.respond(readonly_sql(payload['sql']))
            if self.path=='/api/models': return self.respond(list_models(**payload))
            if self.path=='/api/ping':return self.respond(ping_provider(**payload))
            if self.path=='/api/chat':return self.respond(get_chat(payload['id']))
            if self.path=='/api/chat/variant':return self.respond(select_variant(payload['chatId'],payload['turnId'],payload['index']))
            if self.path=='/api/chats/manage':return self.respond(manage_chats(**payload))
            if self.path=='/api/settings':
                return self.respond(save_settings(payload))
            if self.path=='/api/index':
                conf=settings()['embedding']
                if not conf.get('model') or not conf.get('baseUrl'):raise ValueError('Save an embedding provider first.')
                return self.respond(start_index(conf))
            self.respond({'error':'Not found'},404)
        except Exception as e:
            LOG.error('Request %s failed: %s',self.path.split('?')[0],str(e))
            self.respond({'error':str(e)},400)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--host',default='127.0.0.1');parser.add_argument('--port',type=int,default=8765);args=parser.parse_args()
    configure_logging()
    access=load_access()
    initialize()
    initial=index_inventory(settings().get('embedding',{}))
    LOG.info('Corpus: %s indexed records; %s eligible dialogue records; %s excluded.',f"{initial['eligible']+initial['excluded']:,}",f"{initial['eligible']:,}",f"{initial['excluded']:,}")
    if initial['configured']:
        LOG.info('Semantic index %s: %s / %s eligible vectors; %s remaining.', 'complete' if initial['complete'] else 'incomplete',f"{initial['ready']:,}",f"{initial['eligible']:,}",f"{initial['remaining']:,}")
        if initial['lastError']:LOG.error('Previous embedding build failed: %s',initial['lastError'])
    with chat_db() as c:c.execute("UPDATE turns SET status='error',error='Server restarted before this answer finished. Ask again to retry.' WHERE status='pending'")
    print(f'Open http://localhost:{args.port}',flush=True)
    if args.host=='0.0.0.0':
        MOBILE={'url':f'http://{socket.gethostbyname(socket.gethostname())}:{args.port}'}
        print(f"Phone: {MOBILE['url']}\n"+('Access password: use your saved password.' if access['passwordSet'] else 'Access code: '+access['generatedCode']),flush=True)
    server=ThreadingHTTPServer((args.host,args.port),Handler)
    server.daemon_threads=True
    try:server.serve_forever()
    except KeyboardInterrupt:LOG.info('Minnie stopped. Committed embedding batches are saved for the next run.')
    finally:server.server_close()
