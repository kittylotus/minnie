import hashlib
import array
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
