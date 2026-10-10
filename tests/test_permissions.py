import importlib.util
from pathlib import Path
import unittest

SCRIPT = Path(__file__).resolve().parent.parent / 'skills/provider-fork/scripts/provider_fork.py'
spec = importlib.util.spec_from_file_location('provider_permissions', SCRIPT)
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)


class PermissionTests(unittest.TestCase):
    def test_config_resolution_preserves_full_access_without_a_turn(self):
        class Rpc:
            def __init__(self): self.calls = []
            def request(self, method, params):
                self.calls.append((method, params))
                if method == 'thread/start':
                    return {'thread': {'id': 'ephemeral-probe'}, 'approvalPolicy': 'never',
                            'approvalsReviewer': 'user', 'sandbox': {'type': 'dangerFullAccess'},
                            'activePermissionProfile': None}
                if method == 'thread/unsubscribe': return {}
                raise AssertionError('Unexpected mutation or inference: ' + method)
        rpc = Rpc()
        requested, expected = mod.permission_request(rpc, '/workspace', 'model', 'beeapi', 'config', None, None, None)
        self.assertEqual(requested, {'approvalPolicy': 'never', 'approvalsReviewer': 'user', 'sandbox': 'danger-full-access'})
        self.assertEqual(expected['sandbox'], {'type': 'dangerFullAccess'})
        self.assertTrue(rpc.calls[0][1]['ephemeral'])
        self.assertNotIn('sandbox', rpc.calls[0][1])
        self.assertNotIn('approvalPolicy', rpc.calls[0][1])
        self.assertEqual([call[0] for call in rpc.calls], ['thread/start', 'thread/unsubscribe'])

    def test_named_profiles_and_granular_approvals_are_not_flattened(self):
        granular = {'granular': {'sandbox_approval': True, 'rules': False}}
        class Rpc:
            def request(self, method, params):
                if method == 'thread/unsubscribe': return {}
                return {'thread': {'id': 'ephemeral'}, 'approvalPolicy': granular,
                        'approvalsReviewer': 'auto_review', 'sandbox': {'type': 'workspaceWrite'},
                        'activePermissionProfile': {'id': 'project-edit', 'extends': ':workspace'}}
        request, _ = mod.permission_request(Rpc(), '/workspace', 'model', 'beeapi', 'config', None, None, None)
        self.assertEqual(request['permissions'], 'project-edit')
        self.assertEqual(request['approvalPolicy'], granular)
        self.assertEqual(request['approvalsReviewer'], 'auto_review')
        self.assertNotIn('sandbox', request)

    def test_native_inheritance_sends_no_unrequested_permissions(self):
        class Rpc:
            def request(self, *args): raise AssertionError('Inheritance should not resolve a fresh thread')
        self.assertEqual(mod.permission_request(Rpc(), None, 'model', 'beeapi', 'inherit', None, None, None), ({}, None))
        request, _ = mod.permission_request(Rpc(), None, 'model', 'beeapi', 'inherit', 'read-only', 'never', None)
        self.assertEqual(request, {'sandbox': 'read-only', 'approvalPolicy': 'never'})

    def test_permission_mismatch_is_not_a_verified_success(self):
        result = {'thread': {'id': 'created-branch'}, 'approvalPolicy': 'on-request',
                  'sandbox': {'type': 'dangerFullAccess'}}
        with self.assertRaisesRegex(RuntimeError, 'created-branch'):
            mod.permission_receipt(result, 'inherit', {'approvalPolicy': 'never'}, None)
        with self.assertRaisesRegex(RuntimeError, 'effective approval/sandbox'):
            mod.permission_state({'thread': {'id': 'incomplete-response'}})

    def test_conflicting_permission_selectors_are_rejected_before_mutation(self):
        class Rpc:
            def request(self, *args): raise AssertionError('No request should be sent')
        with self.assertRaisesRegex(RuntimeError, 'mutually exclusive'):
            mod.permission_request(Rpc(), None, 'model', 'beeapi', 'config', 'read-only', None, ':workspace')


if __name__ == '__main__':
    unittest.main()
