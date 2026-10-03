import unittest
import uuid
from unittest.mock import patch
import app


class PresetTests(unittest.TestCase):
    def setUp(self):
        self.path=app.DATA/('presets-test-'+uuid.uuid4().hex+'.json')
        self.chat_path=self.path.with_suffix('.sqlite')
        for path in (self.path,self.path.with_suffix('.tmp'),self.chat_path):self.addCleanup(lambda p=path:p.unlink(missing_ok=True))
        for name,value in [('PRESETS',self.path),('CHATS',self.chat_path)]:
            patcher=patch.object(app,name,value);patcher.start();self.addCleanup(patcher.stop)
        patcher=patch.object(app,'settings',return_value={'llm':{'model':'fixture'},'customInstructions':'Existing persona'});patcher.start();self.addCleanup(patcher.stop)

    def test_initial_persona_migrates_once(self):
        state=app.load_presets();self.assertEqual(state['presets'][0]['blocks'][0]['content'],'Existing persona')
        with patch.object(app,'settings',return_value={'customInstructions':'Changed old field'}):self.assertEqual(app.load_presets(),state)

    def test_save_blocks_scope_order_and_preset_lifecycle(self):
        original=app.load_presets()['presets'][0]
        custom={**original,'name':'Formatting','mainPrompt':'Main','chatPrompt':'Chat','blocks':[{'title':'Both','content':'A','enabled':True,'scope':'both'},{'title':'Research','content':'B','enabled':True,'scope':'research'},{'title':'Disabled','content':'C','enabled':False,'scope':'both'}]}
        state=app.manage_presets({'action':'create','preset':custom});ident=state['activeId'];saved=app.preset_snapshot()
        self.assertEqual(app.preset_instructions(saved,'research'),'Main\n\nA\n\nB')
        self.assertEqual(app.preset_instructions(saved,'chat'),'Chat\n\nA')
        app.manage_presets({'action':'save','id':ident,'preset':{**saved,'name':'Renamed','blocks':[]}})
        self.assertEqual(app.preset_snapshot()['name'],'Renamed');self.assertEqual(app.preset_snapshot()['blocks'],[])
        app.manage_presets({'action':'select','id':original['id']});self.assertEqual(app.preset_snapshot()['id'],original['id'])
        app.manage_presets({'action':'delete','id':ident})
        with self.assertRaisesRegex(ValueError,'at least one'):app.manage_presets({'action':'delete','id':original['id']})
        with self.assertRaisesRegex(ValueError,'not found'):app.preset_snapshot(ident)

    def test_retry_uses_original_prompt_snapshot_after_preset_edit(self):
        handler=object.__new__(app.Handler);original=app.preset_snapshot()
        def generate(payload,emit,control):return {'answer':payload['promptSnapshot']['mainPrompt'],'reasoning':'','evidence':[],'retrieved':[],'trace':[],'citationWarning':False,'semantic':False}
        with patch.object(app,'research',side_effect=generate):
            first=handler.persistent_research({'query':'Q'})
            app.manage_presets({'action':'save','id':original['id'],'preset':{**original,'mainPrompt':'Edited prompt'}})
            retry=handler.persistent_research({'query':'Q','chatId':first['chatId'],'retryTurnId':first['turnId']})
            self.assertEqual(first['answer'],retry['answer'])
            following=handler.persistent_research({'query':'Follow-up','chatId':first['chatId']})
            self.assertEqual(following['answer'],'Edited prompt')
        turn=app.get_chat(first['chatId'])['turns'][0]
        self.assertEqual(len(turn['variants']),2)
        self.assertEqual(turn['request']['promptSnapshot']['mainPrompt'],original['mainPrompt'])

    def test_grouped_citations_are_verified_individually(self):
        answer,ids,invalid=app.verify_citations('Fact [28:353, 28:765; 99:99].',{'28:353':{},'28:765':{}})
        self.assertEqual(answer,'Fact [28:353] [28:765] [unverified source].')
        self.assertEqual(ids,['28:353','28:765','99:99']);self.assertEqual(invalid,['99:99'])
        reply={'choices':[{'message':{'content':'Fact [28:353, 28:765].'}}]}
        nodes=[{'id':'28:353','speaker':'You','text':'A'},{'id':'28:765','speaker':'Garte','text':'B'}]
        with patch.object(app,'search',return_value={'results':nodes,'semantic':False}),patch.object(app,'context',return_value={'nodes':[]}),patch.object(app,'provider',return_value=reply):result=app.research({'query':'Q'})
        self.assertEqual([n['id'] for n in result['evidence']],['28:353','28:765'])
        self.assertFalse(result['citationWarning'])


if __name__=='__main__':unittest.main()
