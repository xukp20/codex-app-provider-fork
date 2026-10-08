import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / 'skills/provider-fork/scripts/provider_fork.py'
if os.environ.get('PROVIDER_FORK_TEST_SCRIPT'):
    SCRIPT = Path(os.environ['PROVIDER_FORK_TEST_SCRIPT'])
spec = importlib.util.spec_from_file_location('provider_fork', SCRIPT)
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)

PROVIDERS = '''
[model_providers.beeapi]
name="BeeAPI"
base_url="https://example.invalid/bee/v1"
wire_api="responses"
requires_openai_auth=false
experimental_bearer_token="test-only-bee"
[model_providers.krill-code]
name="Krill Code"
base_url="https://example.invalid/krill/v1"
wire_api="responses"
requires_openai_auth=false
experimental_bearer_token="test-only-krill"
'''


class PersistentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name).resolve()
        self.original_home = mod.HOME
        mod.HOME = self.home
        self.env = patch.dict(os.environ, {'CODEX_HOME': str(self.home)})
        self.env.start()
        self.auth = b'{"auth_mode":"apikey","OPENAI_API_KEY":"TEST_ONLY_NO_REAL_CREDENTIAL"}'
        (self.home / 'auth.json').write_bytes(self.auth)

    def tearDown(self):
        self.env.stop(); mod.HOME = self.original_home
        self.tmp.cleanup()

    def write(self, root=''):
        content = (root + 'model="gpt-6.1-sol"\nmodel_reasoning_effort="low"\n' + PROVIDERS).encode()
        (self.home / 'config.toml').write_bytes(content)
        return content

    def test_default_cycle_preserves_auth_and_every_other_setting(self):
        self.write()
        original = mod.settings()
        for provider in ('beeapi', 'krill-code', 'openai'):
            changed = mod.set_default(provider)
            self.assertTrue(changed['configChanged'])
            self.assertEqual(mod.settings(), dict(original, model_provider=provider))
            self.assertEqual((self.home / 'auth.json').read_bytes(), self.auth)
            self.assertFalse(changed['existingThreadsChanged'])
            if os.name != 'nt':
                self.assertEqual(Path(changed['backup']).stat().st_mode & 0o777, 0o600)
        self.assertFalse(mod.set_default('openai')['configChanged'])

    def test_bom_crlf_inline_comment_and_backup(self):
        raw = b'\xef\xbb\xbf' + ('# comment\nmodel_provider = "openai" # keep this\n' + PROVIDERS).replace('\n', '\r\n').encode()
        (self.home / 'config.toml').write_bytes(raw)
        result = mod.set_default('beeapi')
        saved = (self.home / 'config.toml').read_bytes()
        self.assertEqual(saved, raw.replace(b'"openai" # keep this', b'"beeapi" # keep this'))
        self.assertEqual(Path(result['backup']).read_bytes(), raw)

    def test_concurrent_edit_does_not_overwrite_or_lose_branch(self):
        self.write(); snapshot = mod.config_snapshot()
        config = self.home / 'config.toml'
        config.write_bytes(config.read_bytes() + b'\n# edited elsewhere\n')
        edited = config.read_bytes()
        receipt = mod.persist_branch({'threadId': 'already-created', 'verified': True}, 'beeapi', snapshot)
        self.assertFalse(receipt['persistentApplied'])
        self.assertEqual(receipt['threadId'], 'already-created')
        self.assertEqual(config.read_bytes(), edited)
        self.assertEqual((self.home / 'auth.json').read_bytes(), self.auth)

    def test_complex_toml_refused_instead_of_rewriting_other_values(self):
        self.write('notes="""\n[not_a_table]\n"""\nmodel_provider="openai"\n')
        original = (self.home / 'config.toml').read_bytes()
        with self.assertRaises((RuntimeError, mod.tomllib.TOMLDecodeError)):
            mod.set_default('beeapi')
        self.assertEqual((self.home / 'config.toml').read_bytes(), original)

    def test_official_url_override_refused(self):
        self.write('openai_base_url="https://example.invalid/v1"\n')
        original = (self.home / 'config.toml').read_bytes()
        with self.assertRaisesRegex(RuntimeError, 'Official direct'):
            mod.set_default('openai')
        self.assertEqual((self.home / 'config.toml').read_bytes(), original)

    @unittest.skipUnless(os.environ.get("PROVIDER_FORK_NATIVE_TESTS") == "1",
                         "Set PROVIDER_FORK_NATIVE_TESTS=1 to run isolated Codex integration tests")
    def test_native_new_defaults_existing_session_and_restart(self):
        self.write('model_provider="beeapi"\n')
        args = {'cwd': str(self.home), 'sandbox': 'read-only', 'approvalPolicy': 'never'}
        # No turn is started. Third-party endpoints are deliberately unreachable.
        with mod.Rpc('stdio') as rpc:
            first = rpc.request('thread/start', args)
            parent = mod.verify(first, 'beeapi')
            rpc.request('thread/inject_items', {'threadId': parent, 'items': [{'type': 'message', 'role': 'user',
                'content': [{'type': 'input_text', 'text': 'Persistence test only. No inference requested.'}]}]})
            mod.set_default('krill-code')
            second = rpc.request('thread/start', args)
            child = mod.verify(second, 'krill-code')
            self.assertEqual(rpc.request('thread/read', {'threadId': parent, 'includeTurns': False})['thread']['modelProvider'], 'beeapi')
        with mod.Rpc('stdio') as rpc:
            fresh = rpc.request('thread/start', args)
            mod.verify(fresh, 'krill-code')
            restored = rpc.request('thread/resume', {'threadId': parent, 'excludeTurns': True})
            self.assertEqual(restored['modelProvider'], 'beeapi')
        self.assertEqual(mod.settings()['model_provider'], 'krill-code')
        self.assertEqual((self.home / 'auth.json').read_bytes(), self.auth)

    @unittest.skipUnless(os.environ.get("PROVIDER_FORK_NATIVE_TESTS") == "1",
                         "Set PROVIDER_FORK_NATIVE_TESTS=1 to run isolated Codex integration tests")
    def test_cli_persistent_handoff_and_idempotent_retry(self):
        self.write('model_provider="beeapi"\n')
        with mod.Rpc('stdio') as rpc:
            source = rpc.request('thread/start', {'cwd': str(self.home), 'sandbox': 'read-only', 'approvalPolicy': 'never'})
            ident = mod.verify(source, 'beeapi')
            rpc.request('thread/inject_items', {'threadId': ident, 'items': [{'type': 'message', 'role': 'user',
                'content': [{'type': 'input_text', 'text': 'Test source context.'}]}]})
        summary = self.home / 'summary.txt'; summary.write_text('Test task summary. No inference.', encoding='utf-8')
        argv = [sys.executable, str(SCRIPT), '--transport', 'stdio', 'handoff', '--thread', ident,
                '--provider', 'krill', '--summary-file', str(summary), '--mode', 'persistent', '--request-id', 'cli-test']
        result = subprocess.run(argv, capture_output=True, text=True, encoding='utf-8', timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        receipt = json.loads(result.stdout)
        self.assertTrue(receipt['verified']); self.assertTrue(receipt['persistentApplied'])
        self.assertFalse(receipt['inferenceStarted'])
        self.assertEqual(mod.settings()['model_provider'], 'krill-code')
        mod.set_default('openai')
        # Replaying a receipt must not silently undo a later intentional choice.
        replay = subprocess.run(argv, capture_output=True, text=True, encoding='utf-8', timeout=30)
        self.assertEqual(replay.returncode, 0, replay.stderr)
        self.assertEqual(json.loads(replay.stdout)['threadId'], receipt['threadId'])
        self.assertEqual(mod.settings()['model_provider'], 'openai')
        self.assertEqual((self.home / 'auth.json').read_bytes(), self.auth)

    @unittest.skipUnless(os.environ.get("PROVIDER_FORK_NATIVE_TESTS") == "1",
                         "Set PROVIDER_FORK_NATIVE_TESTS=1 to run isolated Codex integration tests")
    def test_resume_model_override_can_select_config_default(self):
        self.write('model_provider="beeapi"\n')
        with mod.Rpc('stdio') as rpc:
            started = rpc.request('thread/start', {'cwd': str(self.home), 'sandbox': 'read-only', 'approvalPolicy': 'never'})
            ident = mod.verify(started, 'beeapi')
            rpc.request('thread/inject_items', {'threadId': ident, 'items': [{'type': 'message', 'role': 'user',
                'content': [{'type': 'input_text', 'text': 'Resume precedence test. No inference.'}]}]})
        mod.set_default('krill-code')
        with mod.Rpc('stdio') as rpc:
            # Explicit model alone disables restoration of the saved model/provider pair.
            changed = rpc.request('thread/resume', {'threadId': ident, 'model': 'gpt-6.1-sol', 'excludeTurns': True})
            self.assertEqual(changed['modelProvider'], 'krill-code')
        with mod.Rpc('stdio') as rpc:
            explicit = rpc.request('thread/resume', {'threadId': ident, 'model': 'gpt-6.1-sol',
                'modelProvider': 'beeapi', 'excludeTurns': True})
            self.assertEqual(explicit['modelProvider'], 'beeapi')
        self.assertEqual((self.home / 'auth.json').read_bytes(), self.auth)


if __name__ == '__main__':
    unittest.main(verbosity=2)
