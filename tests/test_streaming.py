import io
import json
import pathlib
import uuid
import unittest
from unittest.mock import patch

import app

class Response(io.BytesIO):
    def __init__(self,data,kind='text/event-stream'):
        super().__init__(data.encode());self.headers={'Content-Type':kind}

def packet(delta=None,finish=None):
    return 'data: '+json.dumps({'choices':[{'index':0,'delta':delta or {},'finish_reason':finish}]})+'\n\n'

class StreamingTests(unittest.TestCase):
    config={'baseUrl':'http://provider.invalid/v1','model':'test','apiKey':'test-key'}

    def stream(self,body,kind='text/event-stream'):
        events=[]
        with patch.object(app.urllib.request,'urlopen',return_value=Response(body,kind)) as request:
            result=app.stream_completion(self.config,{'model':'test','messages':[]},lambda event,data:events.append((event,data)))
        self.assertTrue(json.loads(request.call_args[0][0].data)['stream'])
        return result,events

    def test_tagged_reasoning_split_across_chunks(self):
        body=packet({'content':'<thi'})+packet({'content':'nk>Reason '})+packet({'content':'carefully.</th'})+packet({'content':'ink>Answer [381:13]'},'stop')+'data: [DONE]\n\n'
        message,events=self.stream(body)
        self.assertEqual(events[0][1],{'answer':'','reasoning':''})
        self.assertEqual(events[-1][1],{'answer':'Answer [381:13]','reasoning':'Reason carefully.'})
        self.assertNotIn('<thi', ''.join(e[1]['answer'] for e in events))
        self.assertIn('<think>',message['content'])

    def test_structured_reasoning_and_fragmented_tools(self):
        body=packet({'reasoning_content':'Need context.','tool_calls':[{'index':0,'id':'call-1','function':{'name':'getCon','arguments':'{"node'}}]})
        body+=packet({'tool_calls':[{'index':0,'function':{'name':'text','arguments':'Id":"381:13"}'}}]},'tool_calls')+'data: [DONE]\n\n'
        message,events=self.stream(body)
        self.assertEqual(message['reasoning_content'],'Need context.')
        self.assertEqual(message['tool_calls'][0]['function'],{'name':'getContext','arguments':'{"nodeId":"381:13"}'})
        self.assertEqual(events[-1][1]['reasoning'],'Need context.')

    def test_json_fallback_separates_reasoning(self):
        body=json.dumps({'choices':[{'message':{'role':'assistant','content':'<think>Hidden</think>Answer','reasoning':'Structured. '}}]})
        message,events=self.stream(body,'application/json')
        self.assertEqual(events[-1][1],{'answer':'Answer','reasoning':'Structured. Hidden'})

    def test_incomplete_stream_is_an_error(self):
        with self.assertRaisesRegex(ValueError,'before completion'):self.stream(packet({'content':'partial'}))

    def test_multiple_sse_data_lines_and_comments(self):
        raw=': heartbeat\n\nevent: message\ndata: {"choices":\ndata: []}\n\ndata: [DONE]\n\n'
        self.assertEqual(list(app.sse_packets(Response(raw))),['{"choices":\n[]}','[DONE]'])

    def test_unclosed_reasoning_and_final_wrappers(self):
        self.assertEqual(app.split_reasoning('<analysis>Only reasoning',True),('','Only reasoning'))
        self.assertEqual(app.split_reasoning('<think>R</think><final>A</final>',True),('A','R'))
        self.assertEqual(app.reasoning_text({'reasoning_details':[{'type':'reasoning.text','text':'Exposed reasoning'},{'type':'reasoning.encrypted','data':'private'}]}),'Exposed reasoning')

    def test_research_stream_verifies_final_citations(self):
        conf={'llm':self.config,'embedding':{},'customInstructions':''}
        def completion(config,payload,emit):
            emit('delta',{'answer':'A [381:13]','reasoning':'R'})
            return {'role':'assistant','content':'<think>R</think>A [381:13]'}
        events=[]
        with patch.object(app,'settings',return_value=conf),patch.object(app,'stream_completion',side_effect=completion):
            result=app.research({'query':'Areopagites'},lambda event,data:events.append((event,data)))
        self.assertEqual(result['answer'],'A [381:13]')
        self.assertEqual(result['reasoning'],'R')
        self.assertFalse(result['citationWarning'])
        self.assertEqual(result['evidence'][0]['id'],'381:13')
        self.assertIn('round',[e[0] for e in events])

class ProviderSettingsTests(unittest.TestCase):
    def test_independent_saves_and_endpoint_key_scope(self):
        original={'llm':{'baseUrl':'http://a/v1','model':'text','apiKey':'text-key'},'embedding':{'baseUrl':'http://b/v1','model':'embed','apiKey':'embed-key'},'customInstructions':'Keep me'}
        config_path=app.DATA/('test-settings-'+uuid.uuid4().hex+'.json')
        self.addCleanup(lambda:config_path.unlink(missing_ok=True))
        self.addCleanup(lambda:config_path.with_suffix('.tmp').unlink(missing_ok=True))
        with patch.object(app,'CONFIG',config_path):
            app.CONFIG.write_text(json.dumps(original))
            app.save_settings({'llm':{'baseUrl':'http://a/v1','model':'new-text','apiKey':''}})
            value=app.settings()
            self.assertEqual(value['embedding'],original['embedding'])
            self.assertEqual(value['llm']['apiKey'],'text-key')
            self.assertEqual(value['customInstructions'],'Keep me')
            app.save_settings({'embedding':{'baseUrl':'http://new/v1','model':'new-embed','apiKey':''}})
            self.assertEqual(app.settings()['llm'],value['llm'])
            self.assertEqual(app.settings()['embedding']['apiKey'],'')
            app.save_settings({'customInstructions':'Changed'})
            self.assertEqual(app.settings()['llm'],value['llm'])

    def test_pings_use_selected_models(self):
        with patch.object(app,'settings',return_value={}),patch.object(app,'provider',return_value={'choices':[{'message':{'content':'OK'}}]}) as request:
            result=app.ping_provider('llm',baseUrl='http://a/v1',model='chosen-text',apiKey='key')
            self.assertTrue(result['ok'])
            self.assertEqual(request.call_args[0][1],'chat/completions')
            self.assertEqual(request.call_args[0][2]['model'],'chosen-text')
        with patch.object(app,'settings',return_value={}),patch.object(app,'embed',return_value=[[1,0,0]]) as request:
            result=app.ping_provider('embedding',baseUrl='http://a/v1',model='chosen-embed')
            self.assertIn('3 dimensions',result['message'])
            self.assertEqual(request.call_args[0][1]['model'],'chosen-embed')

    def test_ping_requires_selected_model(self):
        with patch.object(app,'settings',return_value={}):
            with self.assertRaisesRegex(ValueError,'Choose a model'):app.ping_provider('embedding',baseUrl='http://a/v1')
