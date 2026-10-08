import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location('provider_fork', os.environ.get('PROVIDER_FORK_TEST_SCRIPT', str(ROOT/'skills/provider-fork/scripts/provider_fork.py')))
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)


class ProviderForkTests(unittest.TestCase):
    def test_third_party_credential_guards(self):
        cases = [
            ('https://example.invalid/v1', True, 'dedicated-test-token'),
            ('http://example.invalid/v1', False, 'dedicated-test-token'),
            ('https://example.invalid/v1', False, ''),
        ]
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            with patch.object(mod, 'HOME', home):
                for url, official_auth, credential in cases:
                    text = ('[model_providers.beeapi]\nname="BeeAPI"\n'
                            f'base_url={json.dumps(url)}\n'
                            f'requires_openai_auth={str(official_auth).lower()}\n')
                    if credential:
                        text += f'experimental_bearer_token={json.dumps(credential)}\n'
                    config = home / 'config.toml'
                    config.write_text(text, encoding='utf-8')
                    before = config.read_bytes()
                    with self.assertRaises(RuntimeError):
                        mod.validate_provider('beeapi')
                    self.assertEqual(config.read_bytes(), before)

    def test_error_redaction_hides_configured_provider_token(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            token = 'TEST_ONLY_DEDICATED_PROVIDER_TOKEN'
            (home / 'config.toml').write_text(
                '[model_providers.beeapi]\nexperimental_bearer_token="' + token + '"\n',
                encoding='utf-8')
            with patch.object(mod, 'HOME', home):
                self.assertNotIn(token, mod.redact('Rejected credential: ' + token))

    def test_prefix_replacement(self):
        self.assertEqual(mod.title_for('krill-code', 'BeeAPI | A | B'), 'Krill Code | A | B')
        self.assertEqual(mod.title_for('openai', 'Official | BeeAPI | A'), 'Official | A')

    def test_opaque_or_uninspectable_history_does_not_force_handoff(self):
        class ForkRpc:
            transport = 'stdio'
            def __init__(self, history_mode): self.history_mode = history_mode; self.methods = []
            def request(self, method, params):
                self.methods.append(method)
                if method == 'thread/read' and params['threadId'] == 'source':
                    return {'thread': {'modelProvider': 'openai', 'historyMode': self.history_mode,
                        'turns': [{'id': 'completed-turn', 'status': 'completed',
                                   'items': [{'encrypted_content': 'fake-opaque-state'}]}]}}
                if method == 'thread/fork':
                    self.asserted_provider = params['modelProvider']
                    return {'modelProvider': 'beeapi', 'thread': {'id': 'new-fork'}}
                if method == 'thread/name/set': return {}
                if method == 'thread/read': return {'thread': {'modelProvider': 'beeapi'}}
                raise AssertionError('Unexpected API call: '+method)
        for mode in ('legacy', 'paginated'):
            rpc = ForkRpc(mode)
            with patch.object(mod, 'validate_provider', return_value={'model': 'gpt-6.1-sol'}):
                result = mod.fork(rpc, 'source', 'beeapi')
            self.assertTrue(result['verified']); self.assertTrue(result['opaqueHistoryDetected'])
            self.assertEqual(rpc.asserted_provider, 'beeapi')
            self.assertEqual(rpc.methods, ['thread/read', 'thread/fork', 'thread/name/set', 'thread/read'])

    def test_native_fork_failure_does_not_start_handoff(self):
        class FailedForkRpc:
            def __init__(self): self.methods = []
            def request(self, method, params):
                self.methods.append(method)
                if method == 'thread/read':
                    return {'thread': {'modelProvider': 'openai', 'turns': [{'id': 't1', 'status': 'completed'}]}}
                if method == 'thread/fork': raise RuntimeError('Native fork rejected the operation')
                raise AssertionError('No automatic handoff or inference')
        rpc = FailedForkRpc()
        with patch.object(mod, 'validate_provider', return_value={}):
            with self.assertRaisesRegex(RuntimeError, 'Native fork rejected'):
                mod.fork(rpc, 'source', 'beeapi')
        self.assertEqual(rpc.methods, ['thread/read', 'thread/fork'])

    @unittest.skipUnless(os.environ.get("PROVIDER_FORK_NATIVE_TESTS") == "1",
                         "Set PROVIDER_FORK_NATIVE_TESTS=1 to run isolated Codex integration tests")
    def test_wire_credentials_and_persistence(self):
        captured = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_POST(self):
                captured.append({'path': self.path, 'headers': dict(self.headers),
                                 'body': json.loads(self.rfile.read(int(self.headers['Content-Length'])))})
                message = {'type': 'message', 'id': 'msg_mock', 'role': 'assistant', 'status': 'completed',
                           'content': [{'type': 'output_text', 'text': '323'}]}
                events = [
                    {'type': 'response.created', 'response': {'id': 'resp_mock', 'status': 'in_progress', 'output': []}},
                    {'type': 'response.output_item.added', 'output_index': 0, 'item': {**message, 'status': 'in_progress'}},
                    {'type': 'response.output_text.delta', 'output_index': 0, 'content_index': 0, 'delta': '323'},
                    {'type': 'response.output_item.done', 'output_index': 0, 'item': message},
                    {'type': 'response.completed', 'response': {'id': 'resp_mock', 'status': 'completed', 'output': [message],
                     'usage': {'input_tokens': 10, 'output_tokens': 1, 'total_tokens': 11}}},
                ]
                body = ''.join('event: '+e['type']+'\ndata: '+json.dumps(e)+'\n\n' for e in events).encode()
                self.send_response(200); self.send_header('Content-Type', 'text/event-stream'); self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body)
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        original_home = mod.HOME
        original_env = os.environ.get('CODEX_HOME')
        try:
            with tempfile.TemporaryDirectory() as temp:
                home = Path(temp).resolve(); mod.HOME = home; os.environ['CODEX_HOME'] = str(home)
                text = 'model="gpt-6.1-sol"\nmodel_provider="openai"\nmodel_reasoning_effort="low"\n'
                for provider in ('beeapi', 'krill-code'):
                    text += f'\n[model_providers.{provider}]\nname="{provider}"\nbase_url="http://127.0.0.1:{server.server_port}/{provider}/v1"\nwire_api="responses"\nrequires_openai_auth=false\nsupports_websockets=false\nexperimental_bearer_token="test-only-{provider}"\n'
                (home/'config.toml').write_text(text)
                auth = {'auth_mode': 'chatgpt', 'OPENAI_API_KEY': None, 'tokens': {'access_token': 'OFFICIAL_SENTINEL_NOT_A_REAL_TOKEN', 'refresh_token': 'FAKE_REFRESH', 'id_token': 'FAKE_ID', 'account_id': 'OFFICIAL_SENTINEL_ACCOUNT'}, 'last_refresh': '2026-10-08T00:00:00Z'}
                (home/'auth.json').write_text(json.dumps(auth))
                hashes = {p: hashlib.sha256((home/p).read_bytes()).hexdigest() for p in ('config.toml', 'auth.json')}
                with mod.Rpc('stdio') as rpc:
                    started = rpc.request('thread/start', {'modelProvider': 'beeapi', 'cwd': str(home), 'sandbox': 'read-only', 'approvalPolicy': 'never'})
                    parent = mod.verify(started, 'beeapi')
                    turn = mod.run_turn(rpc, parent, '17*19. No tools.', timeout=30)
                    self.assertEqual(turn['status'], 'completed')
                    # Exercise the public fork helper on native paginated history.
                    # HTTP is allowed only for this isolated mock credential test.
                    with patch.object(mod, 'validate_provider', return_value=mod.settings()):
                        child = mod.fork(rpc, parent, 'krill-code', last_turn=turn['turnId'])
                    child_id = child['threadId']
                    self.assertTrue(child['verified'])
                    turn2 = mod.run_turn(rpc, child_id, 'Repeat the previous result. No tools.', timeout=30)
                    self.assertEqual(turn2['status'], 'completed')
                    self.assertEqual(rpc.request('thread/read', {'threadId': parent, 'includeTurns': False})['thread']['modelProvider'], 'beeapi')
                # New process must recover child provider without an explicit provider override.
                with mod.Rpc('stdio') as rpc:
                    reopened = rpc.request('thread/resume', {'threadId': child_id, 'excludeTurns': True})
                    self.assertEqual(reopened['modelProvider'], 'krill-code')
                    rpc.request('thread/inject_items', {'threadId': child_id, 'items': [{'type': 'message', 'role': 'user',
                        'content': [{'type': 'input_text', 'text': 'HANDOFF_PERSISTENCE_SENTINEL_742'}]}]})
                with mod.Rpc('stdio') as rpc:
                    rpc.request('thread/resume', {'threadId': child_id, 'modelProvider': 'krill-code', 'excludeTurns': True})
                    resumed_turn = mod.run_turn(rpc, child_id, 'Repeat result. No tools.', timeout=30)
                    self.assertEqual(resumed_turn['status'], 'completed')
                self.assertIn('HANDOFF_PERSISTENCE_SENTINEL_742', json.dumps(captured[-1]['body']))
                self.assertTrue(captured)
                for entry in captured:
                    headers = {k.lower(): v for k, v in entry['headers'].items()}
                    provider = 'beeapi' if '/beeapi/' in entry['path'] else 'krill-code'
                    self.assertEqual(headers.get('authorization'), 'Bearer test-only-'+provider)
                    self.assertNotIn('chatgpt-account-id', headers)
                    self.assertNotIn('OFFICIAL_SENTINEL', json.dumps(entry))
                for p, digest in hashes.items():
                    self.assertEqual(hashlib.sha256((home/p).read_bytes()).hexdigest(), digest)
        finally:
            mod.HOME = original_home
            if original_env is None: os.environ.pop('CODEX_HOME', None)
            else: os.environ['CODEX_HOME'] = original_env
            server.shutdown(); server.server_close()


if __name__ == '__main__':
    unittest.main()
