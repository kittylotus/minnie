import json
import uuid
import unittest
from unittest.mock import patch

import app

class ChatTests(unittest.TestCase):
    def setUp(self):
        self.path=app.DATA/('test-chats-'+uuid.uuid4().hex+'.sqlite')
        self.patch=patch.object(app,'CHATS',self.path);self.patch.start()
        self.addCleanup(self.patch.stop)
        self.addCleanup(lambda:self.path.unlink(missing_ok=True))

    def turn(self,question,chat_id=None):
        payload={'query':question}
        if chat_id:payload['chatId']=chat_id
        ident,turn=app.begin_turn(payload)
        n=app.node('381:13')
        result={'answer':'An answer [381:13]','reasoning':'Private presentation text','evidence':[n],'retrieved':[n],'trace':[],'citationWarning':False,'semantic':False}
        app.finish_turn(turn,result)
        return ident,turn

    def test_persistence_and_followup_chain(self):
        chat,turn=self.turn('Areopagites')
        self.turn('Where did they come from?',chat)
        self.assertEqual(len(app.get_chat(chat)['turns']),2)
        self.assertEqual(app.get_chat(chat)['turns'][0]['result']['answer'],'An answer [381:13]')
        self.assertEqual(len(app.chat_history(chat)),2)
        self.assertEqual(len(app.chat_list()['chats']),1)

    def test_folder_moves_renames_and_pins(self):
        chat,_=self.turn('Question')
        folder=app.manage_chats('createFolder',name='Lore')['id']
        app.manage_chats('moveChat',id=chat,folderId=folder)
        app.manage_chats('renameChat',id=chat,name='Pale research')
        app.manage_chats('pinChat',id=chat,pinned=True)
        app.manage_chats('renameFolder',id=folder,name='World')
        app.manage_chats('pinFolder',id=folder,pinned=True)
        listed=app.chat_list()
        self.assertEqual(listed['chats'][0]['title'],'Pale research')
        self.assertEqual(listed['chats'][0]['folder_id'],folder)
        self.assertEqual(listed['chats'][0]['pinned'],1)
        self.assertEqual(listed['folders'][0]['name'],'World')
        self.assertEqual(listed['folders'][0]['pinned'],1)
        app.manage_chats('deleteFolder',id=folder)
        self.assertIsNone(app.get_chat(chat)['folder_id'])
        app.manage_chats('deleteChat',id=chat)
        self.assertEqual(app.chat_list()['chats'],[])
        with app.chat_db() as c:self.assertEqual(c.execute('SELECT count(*) FROM turns').fetchone()[0],0)

    def test_concurrent_turns_and_failed_response(self):
        chat,turn=app.begin_turn({'query':'Question'})
        with self.assertRaisesRegex(ValueError,'in progress'):app.begin_turn({'query':'Another','chatId':chat})
        with self.assertRaisesRegex(ValueError,'finish'):app.manage_chats('deleteChat',id=chat)
        app.finish_turn(turn,error='Provider offline')
        self.assertEqual(app.get_chat(chat)['turns'][0]['status'],'error')
        self.assertEqual(app.chat_history(chat),[])
        app.begin_turn({'query':'Try again','chatId':chat})

    def test_followup_prompt_contains_history_and_cited_evidence(self):
        chat,_=self.turn('What are the Areopagites?')
        conf={'llm':{'model':'test'},'embedding':{},'customInstructions':''}
        reply={'choices':[{'message':{'role':'assistant','content':'A follow-up [381:13]'}}]}
        with patch.object(app,'settings',return_value=conf),patch.object(app,'provider',return_value=reply) as provider:
            result=app.research({'query':'Where did they come from?','chatId':chat})
        messages=provider.call_args[0][2]['messages']
        self.assertTrue(any(m['role']=='user' and m['content']=='What are the Areopagites?' for m in messages))
        self.assertTrue(any(m['role']=='assistant' and m['content']=='An answer [381:13]' for m in messages))
        self.assertFalse(any(m['content']=='Private presentation text' for m in messages))
        self.assertEqual(result['evidence'][0]['id'],'381:13')

    def test_missing_chat_and_unknown_folder_fail(self):
        with self.assertRaises(ValueError):app.begin_turn({'query':'Q','chatId':'missing'})
        with self.assertRaises(ValueError):app.begin_turn({'query':'Q','folderId':'missing'})

class RetrievalNoiseTests(unittest.TestCase):
    def test_numeric_entries_are_not_dialogue(self):
        self.assertFalse(app.meaningful_dialogue(app.node('630:83')))
        self.assertTrue(app.meaningful_dialogue(app.node('381:13')))

    def test_semantic_only_useful_dialogue_is_kept(self):
        import array
        config={'baseUrl':'http://test.invalid','model':'noise-filter-test'};key=app.embedding_key(config)
        with app.db() as c:previous=[tuple(r) for r in c.execute("SELECT * FROM vectors WHERE id IN ('630:83','381:13')")]
        try:
            with app.db() as c:c.executemany('INSERT OR REPLACE INTO vectors VALUES(?,?,?)',[(i,key,array.array('f',[1,0]).tobytes()) for i in ('630:83','381:13')])
            with patch.object(app,'settings',return_value={'embedding':config}),patch.object(app,'embed',return_value=[[1,0]]):result=app.search('unique-concept-not-in-corpus','hybrid')
            self.assertEqual([n['id'] for n in result['results']],['381:13'])
            self.assertIsNone(result['results'][0]['retrieval']['lexical'])
        finally:
            with app.db() as c:
                c.execute('DELETE FROM vectors WHERE model=?',(key,))
                c.executemany('INSERT OR REPLACE INTO vectors VALUES(?,?,?)',previous)
