import hashlib
import array
import sqlite3
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import app

class CorpusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.initialize()
        cls.before=hashlib.sha256(app.SOURCE.read_bytes()).hexdigest()

    def test_obscure_exact_term_has_real_composite_ids(self):
        result=app.search('Areopagites','exact')
        self.assertGreater(len(result['results']),0)
        self.assertIn('381:13',[n['id'] for n in result['results']])
        self.assertTrue(all('areopagites' in n['text'].lower() or 'areopagites' in n['alternates'].lower() for n in result['results']))

    def test_spelling_suggestion(self):
        self.assertEqual(app.search('aeropagites','exact')['suggestion'],'areopagites')

    def test_speaker_filter(self):
        rows=app.search('eyes','hybrid',speaker='Kim Kitsuragi')['results']
        self.assertTrue(rows)
        self.assertTrue(all(n['speaker']=='Kim Kitsuragi' for n in rows))

    def test_graph_uses_actual_links(self):
        ctx=app.context('381:13')
        self.assertEqual(ctx['center']['id'],'381:13')
        self.assertTrue(ctx['edges'])
        self.assertTrue(any(e['from']=='381:13' or e['to']=='381:13' for e in ctx['edges']))

    def test_garte_branch_runs_to_choices_in_database_order(self):
        result=app.dialogue_branch('28:353')
        self.assertEqual([n['id'] for n in result['sequence']],['28:353','28:765','28:989','28:287','28:430','28:683'])
        self.assertEqual(result['choicePoint']['id'],'28:759')
        self.assertEqual([n['id'] for n in result['choices']],['28:1126','28:288','28:70'])
        self.assertEqual(result['stop'],'choices')
        self.assertEqual(result['sequence'][2]['passiveCheck'],{'skill':'Composure','estimatedSkill':4})
        self.assertIn('SetVariableValue',result['choices'][1]['script'])

    def test_hub_opens_choices_without_displaying_zero(self):
        result=app.dialogue_branch('28:759')
        self.assertEqual(result['sequence'],[])
        self.assertEqual(len(result['choices']),3)
        self.assertTrue(result['choicePoint']['structural'])
        self.assertTrue(all(app.meaningful_dialogue(n) for n in result['choices']))

    def test_choice_continues_and_branch_limit_is_resumable(self):
        result=app.dialogue_branch('28:353',max_lines=2)
        self.assertEqual(result['stop'],'limit')
        self.assertEqual(result['continueAt'],'28:989')
        result=app.dialogue_branch('28:288')
        self.assertEqual(result['sequence'][0]['id'],'28:288')
        self.assertGreater(len(result['sequence']),1)

    def test_exact_search_excludes_hub_zero_records(self):
        rows=app.search('0','exact')['results']
        self.assertTrue(all(n['speaker']!='HUB' and app.meaningful_dialogue(n) for n in rows))

    def test_branch_handles_cross_conversation_links_and_cycles(self):
        graph=sqlite3.connect(':memory:');src=sqlite3.connect(':memory:')
        graph.row_factory=src.row_factory=sqlite3.Row
        try:
            graph.executescript('CREATE TABLE edges(originconversationid,origindialogueid,destinationconversationid,destinationdialogueid); INSERT INTO edges VALUES(1,1,2,1),(2,1,2,2),(2,2,1,1);')
            src.executescript('CREATE TABLE dentries(conversationid,id,isgroup,userscript,difficultypass); INSERT INTO dentries VALUES(1,1,0,"",0),(2,1,1,"",0),(2,2,0,"",0); CREATE TABLE checks(conversationid,dialogueid); CREATE TABLE modifiers(conversationid,dialogueid);')
            def fake_node(ident):
                return {'id':ident,'speaker':'HUB' if ident=='2:1' else 'You','text':'0' if ident=='2:1' else 'Spoken line','alternates':'[]','conditions':''}
            with patch.object(app,'db',return_value=graph),patch.object(app,'source',return_value=src),patch.object(app,'node',side_effect=fake_node):
                result=app.dialogue_branch('1:1')
            self.assertEqual([n['id'] for n in result['sequence']],['1:1','2:2'])
            self.assertEqual(result['stop'],'cycle')
            self.assertEqual(result['continueAt'],'1:1')
        finally:graph.close();src.close()

    def test_source_select_and_cte(self):
        self.assertEqual(app.readonly_sql('WITH x AS (SELECT 42 AS answer) SELECT * FROM x')['rows'],[[42]])
        self.assertTrue(app.readonly_sql('SELECT * FROM dentries')['truncated'])

    def test_sql_blocks_modification_and_escape(self):
        for sql in ['DELETE FROM actors','PRAGMA writable_schema=1',"ATTACH DATABASE ':memory:' AS evil",'SELECT 1; DELETE FROM actors',"SELECT load_extension('bad')",'WITH x AS (SELECT 1) DELETE FROM actors']:
            with self.subTest(sql=sql),self.assertRaises(Exception):app.readonly_sql(sql)

    def test_semantic_requires_real_index(self):
        with patch.object(app,'settings',return_value={'embedding':{'model':'unconfigured-test'}}):
            with self.assertRaisesRegex(ValueError,'Build the semantic index'): app.search('memory','semantic')

    def test_missing_answer_provider_is_clear(self):
        with patch.object(app,'settings',return_value={'llm':{}}):
            with self.assertRaisesRegex(ValueError,'Configure your answer model'):app.research({'query':'Pale'})

    def test_semantic_cosine_and_hybrid_provenance(self):
        config={'baseUrl':'http://test.invalid','model':'test-only'}
        key=app.embedding_key(config)
        try:
            with app.db() as c:
                c.executemany('INSERT OR REPLACE INTO vectors VALUES(?,?,?)',[
                    ('381:13',key,array.array('f',[1,0]).tobytes()),
                    ('381:28',key,array.array('f',[0,1]).tobytes())])
            with patch.object(app,'settings',return_value={'embedding':config}),patch.object(app,'embed',return_value=[[1,0]]):
                result=app.search('Areopagites','semantic')
                self.assertEqual(result['results'][0]['id'],'381:13')
                self.assertTrue(result['semantic'])
                result=app.search('Areopagites','hybrid')
                item=next(n for n in result['results'] if n['id']=='381:13')
                self.assertIsNotNone(item['retrieval']['lexical'])
                self.assertEqual(item['retrieval']['vector'],1)
        finally:
            with app.db() as c:c.execute('DELETE FROM vectors WHERE model=?',(key,))

    def test_research_tools_and_citations(self):
        responses=[{'choices':[{'message':{'role':'assistant','content':None,'tool_calls':[{'id':'test-call','type':'function','function':{'name':'getContext','arguments':'{"nodeId":"381:13"}'}}]}}]},
                   {'choices':[{'message':{'role':'assistant','content':'Measurehead claims ancestry from the Areopagites. [381:13] An invented source [99999:99999]'}}]}]
        conf={'llm':{'model':'test-only'},'embedding':{},'customInstructions':''}
        with patch.object(app,'settings',return_value=conf),patch.object(app,'provider',side_effect=responses):
            answer=app.research({'query':'Areopagites','depth':'quick'})
        self.assertEqual(answer['evidence'][0]['id'],'381:13')
        self.assertTrue(answer['citationWarning'])
        self.assertIn('[unverified source]',answer['answer'])
        self.assertEqual(len(answer['trace']),1)

    @classmethod
    def tearDownClass(cls):
        assert hashlib.sha256(app.SOURCE.read_bytes()).hexdigest()==cls.before,'Original DB changed'

if __name__=='__main__':unittest.main()
