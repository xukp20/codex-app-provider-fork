#!/usr/bin/env python3
"""Create provider-specific branches; optionally change the default, never auth or Desktop."""
import argparse
import asyncio
import contextlib
import hashlib
import json
import os
from pathlib import Path
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import tomllib
import uuid

HOME = Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex')))
LABELS = {'openai': 'Official', 'beeapi': 'BeeAPI', 'krill-code': 'Krill Code'}
ALIASES = {'official': 'openai', 'openai': 'openai', 'beeapi': 'beeapi', 'krill': 'krill-code', 'krill-code': 'krill-code'}


def settings():
    return tomllib.loads((HOME / 'config.toml').read_text(encoding='utf-8-sig'))


def redact(message):
    message = str(message)
    try:
        for definition in settings().get('model_providers', {}).values():
            token = definition.get('experimental_bearer_token')
            if token:
                message = message.replace(token, '[REDACTED]')
    except Exception:
        pass
    message = re.sub(r'(?i)bearer\s+[^\s"\']+', 'Bearer [REDACTED]', message)
    message = re.sub(r'\b(?:sk-[A-Za-z0-9_-]{8,}|eyJ[A-Za-z0-9_.-]{20,})', '[REDACTED]', message)
    return message[:1600]


def validate_provider(provider):
    data = settings()
    if provider == 'openai':
        if data.get('openai_base_url') or os.environ.get('OPENAI_BASE_URL'):
            raise RuntimeError('Official direct route refused: an OpenAI base URL override exists')
    else:
        definition = data.get('model_providers', {}).get(provider)
        if not definition or definition.get('requires_openai_auth', False):
            raise RuntimeError('Third-party provider is missing or requests official authentication')
        if not definition.get('base_url', '').startswith('https://'):
            raise RuntimeError('Third-party endpoint must use HTTPS')
        if not (definition.get('experimental_bearer_token') or definition.get('env_key')):
            raise RuntimeError('Provider-specific credential is missing')
    return data


def title_for(provider, original):
    original = original or 'Untitled'
    original = re.sub(r'^(?:(?:Official|BeeAPI|Krill Code)\s*\|\s*)+', '', original, flags=re.I)
    return f'{LABELS[provider]} | {original}'


def config_snapshot():
    return hashlib.sha256((HOME / 'config.toml').read_bytes()).hexdigest()


def render_default(raw, provider):
    """Surgical edit, then prove that TOML semantics changed in exactly one place."""
    bom = b'\xef\xbb\xbf' if raw.startswith(b'\xef\xbb\xbf') else b''
    text = raw[len(bom):].decode('utf-8')
    before = tomllib.loads(text)
    lines = text.splitlines(keepends=True)
    newline = '\r\n' if '\r\n' in text else '\n'
    changed = False
    for i, line in enumerate(lines):
        # Complex multiline/quoted-key syntax is allowed only if semantic proof passes.
        if re.match(r'^\s*\[', line):
            break
        match = re.fullmatch(r'(\s*(?:model_provider|"model_provider"|\'model_provider\')\s*=\s*)(?:"[^"\r\n]*"|\'[^\'\r\n]*\')(\s*(?:#[^\r\n]*)?)(\r?\n)?', line)
        if match:
            lines[i] = match[1] + json.dumps(provider) + match[2] + (match[3] or '')
            changed = True
            break
    candidate = ''.join(lines) if changed else 'model_provider = ' + json.dumps(provider) + newline + text
    expected = dict(before, model_provider=provider)
    if tomllib.loads(candidate) != expected:
        raise RuntimeError('Config layout cannot be edited safely; no changes written')
    return bom + candidate.encode('utf-8')


def preserve_permissions(source, target):
    if os.name != 'nt':
        os.chmod(target, source.stat().st_mode & 0o777)
        return
    # Atomic replacement must retain an existing custom Windows DACL.
    import ctypes
    from ctypes import wintypes
    api = ctypes.WinDLL('advapi32', use_last_error=True)
    get = api.GetFileSecurityW
    get.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    get.restype = wintypes.BOOL
    put = api.SetFileSecurityW
    put.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_void_p]
    put.restype = wintypes.BOOL
    size = wintypes.DWORD()
    get(str(source), 4, None, 0, ctypes.byref(size))
    if not size.value:
        raise ctypes.WinError(ctypes.get_last_error())
    buffer = ctypes.create_string_buffer(size.value)
    if not get(str(source), 4, buffer, size.value, ctypes.byref(size)) or not put(str(target), 4, buffer):
        raise ctypes.WinError(ctypes.get_last_error())


def set_default(provider, expected_sha=None):
    """Change this host's root default only; never reload another user's thread."""
    validate_provider(provider)
    config = HOME / 'config.toml'
    folder = HOME / 'provider-fork/backups'
    folder.mkdir(parents=True, exist_ok=True)
    if os.name != 'nt':
        os.chmod(folder, 0o700)
    lock = folder / 'default-change.lock'
    try:
        handle = lock.open('x')
    except FileExistsError:
        raise RuntimeError('Another default change is running, or its outcome needs inspection')
    temporary = None
    try:
        with handle:
            handle.write(str(os.getpid()))
        raw = config.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if expected_sha is not None and expected_sha != digest:
            raise RuntimeError('Config changed during branch creation; new branch retained, default not changed')
        previous = tomllib.loads(raw.decode('utf-8-sig')).get('model_provider', 'openai')
        if previous == provider:
            return {'defaultProvider': provider, 'previousDefaultProvider': previous, 'configChanged': False,
                    'configSha256': digest, 'scope': 'this-host', 'existingThreadsChanged': False, 'authWritten': False}
        candidate = render_default(raw, provider)
        stamp = time.strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:12]
        backup = folder / ('config-' + stamp + '.toml')
        temporary = config.with_name('.provider-default-' + stamp + '.tmp')
        for path, content in ((backup, raw), (temporary, candidate)):
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'wb') as stream:
                stream.write(content); stream.flush(); os.fsync(stream.fileno())
            preserve_permissions(config, path)
            if path == backup and os.name != 'nt':
                os.chmod(path, 0o600)
        if config.read_bytes() != raw:
            raise RuntimeError('Concurrent config edit detected; no default change applied')
        os.replace(temporary, config)
        return {'defaultProvider': provider, 'previousDefaultProvider': previous, 'configChanged': True,
                'configSha256': hashlib.sha256(candidate).hexdigest(), 'backup': str(backup),
                'scope': 'this-host', 'existingThreadsChanged': False, 'authWritten': False}
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        lock.unlink(missing_ok=True)


def persist_branch(receipt, provider, expected_sha):
    # A verified branch is kept even if a concurrent config edit blocks persistence.
    receipt['switchMode'] = 'persistent'
    try:
        receipt['defaultChange'] = set_default(provider, expected_sha)
        receipt['persistentApplied'] = True
    except Exception as error:
        receipt['persistentApplied'] = False
        receipt['persistenceError'] = redact(error)
    return receipt


def binary_path():
    if os.environ.get('CODEX_PROVIDER_CLI'):
        return os.environ['CODEX_PROVIDER_CLI']
    if os.name == 'nt':
        candidates = list((Path(os.environ['LOCALAPPDATA']) / 'OpenAI/Codex/bin').glob('*/codex.exe'))
        if candidates:
            return str(max(candidates, key=lambda p: p.stat().st_mtime))
    result = shutil.which('codex')
    if not result:
        raise RuntimeError('Codex CLI not found')
    return result


class Rpc:
    def __init__(self, transport='auto', launch_overrides=None):
        self.transport = 'stdio' if transport == 'auto' and os.name == 'nt' else ('daemon' if transport == 'auto' else transport)
        self.launch_overrides = launch_overrides or []
        self.serial = 0
        self.pending = []

    def __enter__(self):
        if self.transport == 'daemon':
            from websockets.legacy.client import unix_connect
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            sock = HOME / 'app-server-control/app-server-control.sock'
            self.ws = self.loop.run_until_complete(unix_connect(path=str(sock.resolve()), uri='ws://localhost/rpc', compression=None, max_size=None, open_timeout=12))
        else:
            argv = [binary_path(), 'app-server']
            for item in self.launch_overrides:
                argv.extend(['-c', item])
            self.proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding='utf-8', creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            self.messages = queue.Queue()
            def reader():
                try:
                    for line in self.proc.stdout:
                        with contextlib.suppress(json.JSONDecodeError):
                            self.messages.put(json.loads(line))
                finally:
                    self.messages.put(None)
            threading.Thread(target=reader, daemon=True).start()
        self.request('initialize', {'clientInfo': {'name': 'provider-fork', 'title': 'Provider Fork', 'version': '1.0.0'}, 'capabilities': {'experimentalApi': True}})
        self.send({'method': 'initialized'})
        return self

    def send(self, item):
        encoded = json.dumps(item, ensure_ascii=False)
        if self.transport == 'daemon':
            self.loop.run_until_complete(self.ws.send(encoded))
        else:
            self.proc.stdin.write(encoded + '\n')
            self.proc.stdin.flush()

    def receive(self, timeout=60):
        if self.transport == 'daemon':
            item = json.loads(self.loop.run_until_complete(asyncio.wait_for(self.ws.recv(), timeout)))
        else:
            item = self.messages.get(timeout=timeout)
        if item is None:
            raise RuntimeError('App-server exited')
        if 'id' in item and 'method' in item:
            # Never approve a model's tool/credential request during a connectivity probe.
            self.send({'id': item['id'], 'error': {'code': -32601, 'message': 'Interactive server requests unsupported by this helper'}})
        return item

    def request(self, method, params, timeout=60):
        self.serial += 1
        ident = self.serial
        self.send({'id': ident, 'method': method, 'params': params})
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            item = self.receive(max(.1, deadline - time.monotonic()))
            if item.get('id') == ident and 'method' not in item:
                if 'error' in item:
                    raise RuntimeError(redact(f"{method}: {item['error'].get('message', 'rejected')}"))
                return item.get('result', {})
            if 'id' not in item:
                self.pending.append(item)
        raise TimeoutError(method)

    def __exit__(self, *_):
        if self.transport == 'daemon':
            with contextlib.suppress(Exception):
                self.loop.run_until_complete(self.ws.close())
            self.loop.close()
            asyncio.set_event_loop(None)
        else:
            with contextlib.suppress(Exception):
                self.proc.stdin.close()
                self.proc.wait(timeout=5)
            if self.proc.poll() is None:
                self.proc.terminate()  # only the helper's child, never Desktop/daemon
                self.proc.wait(timeout=5)
            self.proc.stdout.close()


def verify(result, provider):
    effective = result.get('modelProvider', result.get('thread', {}).get('modelProvider'))
    if effective != provider:
        raise RuntimeError(f'Provider mismatch: requested {provider}, returned {effective}')
    return result['thread']['id']


def probe_config(data):
    result = {'features.memories': False, 'features.apps': False, 'features.multi_agent_v2': False,
              'model_reasoning_effort': 'low', 'service_tier': 'default'}
    for name in data.get('mcp_servers', {}):
        result[f'mcp_servers.{name}.enabled'] = False
    for name in data.get('plugins', {}):
        result[f'plugins.{name}.enabled'] = False
    return result


def new_test(rpc, provider, cwd, title):
    data = validate_provider(provider)
    result = rpc.request('thread/start', {'modelProvider': provider, 'model': data.get('model', 'gpt-6.1-sol'),
        'cwd': str(cwd), 'sandbox': 'read-only', 'approvalPolicy': 'never', 'config': probe_config(data),
        'developerInstructions': 'Connectivity test only. Never call tools, access files, use connectors, or execute commands. Answer the arithmetic question concisely.'})
    ident = verify(result, provider)
    rpc.request('thread/name/set', {'threadId': ident, 'name': title_for(provider, title)})
    return result


def run_turn(rpc, ident, prompt, timeout=120):
    before = time.monotonic()
    rpc.pending.clear()
    started = rpc.request('turn/start', {'threadId': ident, 'input': [{'type': 'text', 'text': prompt}], 'effort': 'low', 'serviceTierForTurn': 'default'})
    turn_id = started['turn']['id']
    deadline = time.monotonic() + timeout
    chunks, tool_calls, errors = [], [], []
    while time.monotonic() < deadline:
        try:
            item = rpc.pending.pop(0) if rpc.pending else rpc.receive(min(10, max(.1, deadline - time.monotonic())))
        except (queue.Empty, asyncio.TimeoutError):
            continue
        params = item.get('params', {})
        if params.get('threadId') != ident:
            continue
        method = item.get('method', '')
        if method == 'item/agentMessage/delta':
            chunks.append(params.get('delta', ''))
        elif method == 'item/completed':
            entry = params.get('item', {})
            if entry.get('type') not in ('agentMessage', 'reasoning', 'userMessage'):
                tool_calls.append(entry.get('type'))
        elif method == 'error':
            errors.append(redact(params.get('error', {}).get('message', 'error')))
        elif method == 'turn/completed' and params.get('turn', {}).get('id') == turn_id:
            turn = params['turn']
            return {'turnId': turn_id, 'status': turn.get('status'), 'seconds': round(time.monotonic()-before, 2),
                    'answer': ''.join(chunks).strip(), 'toolCalls': tool_calls,
                    'error': redact(turn.get('error') or '') if turn.get('error') else None, 'events': errors}
    rpc.request('turn/interrupt', {'threadId': ident, 'turnId': turn_id})
    return {'turnId': turn_id, 'status': 'timeout', 'seconds': round(time.monotonic()-before, 2), 'answer': ''.join(chunks), 'events': errors}


SANDBOX_TYPES = {'read-only': 'readOnly', 'workspace-write': 'workspaceWrite',
                 'danger-full-access': 'dangerFullAccess'}


def permission_state(result):
    if result.get('approvalPolicy') is None or not isinstance(result.get('sandbox'), dict):
        raise RuntimeError('Server did not return effective approval/sandbox settings')
    return {key: result[key] for key in ('approvalPolicy', 'approvalsReviewer', 'sandbox', 'activePermissionProfile')
            if key in result}


def permission_request(rpc, cwd, model, provider, mode, sandbox, approval_policy, permission_profile):
    """Resolve fresh configuration through the server, without inheriting stale source settings."""
    if sandbox and permission_profile:
        raise RuntimeError('Sandbox and permission profile overrides are mutually exclusive')
    overrides = {}
    if sandbox is not None:
        if sandbox not in SANDBOX_TYPES:
            raise RuntimeError('Unsupported sandbox mode')
        overrides['sandbox'] = sandbox
    if approval_policy is not None:
        overrides['approvalPolicy'] = approval_policy
    if permission_profile is not None:
        overrides['permissions'] = permission_profile
    if mode == 'inherit':
        return overrides, None
    if mode != 'config':
        raise RuntimeError('Unsupported permission mode')
    # A fresh ephemeral thread lets Codex resolve profiles, project layers, defaults,
    # granular approvals and managed requirements. It stores no conversation and
    # starts no turn. Avoid reimplementing this resolution from raw config/read TOML.
    probe = rpc.request('thread/start', {'cwd': cwd, 'model': model, 'modelProvider': provider,
        'ephemeral': True, 'config': {'features.memories': False}, 'serviceTier': 'default', **overrides})
    try:
        state = permission_state(probe)
        request = {'approvalPolicy': state['approvalPolicy']}
        if state.get('approvalsReviewer') is not None:
            request['approvalsReviewer'] = state['approvalsReviewer']
        profile = state.get('activePermissionProfile')
        if profile and profile.get('id'):
            request['permissions'] = profile['id']
        else:
            kinds = {value: key for key, value in SANDBOX_TYPES.items()}
            kind = state['sandbox'].get('type')
            if kind not in kinds:
                raise RuntimeError('Effective permission policy cannot be represented by this server API')
            request['sandbox'] = kinds[kind]
        return request, state
    finally:
        rpc.request('thread/unsubscribe', {'threadId': probe['thread']['id']})


def permission_receipt(result, mode, requested, expected):
    effective = permission_state(result)
    if expected is not None and effective != expected:
        raise RuntimeError('Created branch permissions differ from resolved configuration: ' + result['thread']['id'])
    for key in ('approvalPolicy', 'approvalsReviewer'):
        if key in requested and effective.get(key) != requested[key]:
            raise RuntimeError('Created branch did not honor ' + key + ': ' + result['thread']['id'])
    if 'sandbox' in requested and effective['sandbox'].get('type') != SANDBOX_TYPES[requested['sandbox']]:
        raise RuntimeError('Created branch did not honor sandbox: ' + result['thread']['id'])
    if 'permissions' in requested and (effective.get('activePermissionProfile') or {}).get('id') != requested['permissions']:
        raise RuntimeError('Created branch did not honor permission profile: ' + result['thread']['id'])
    return {'permissionMode': mode, 'requestedPermissions': requested,
            'effectivePermissions': effective, 'permissionsVerified': True}


def fork(rpc, source_id, provider, model=None, last_turn=None, allow_opaque=False, *,
         permission_mode='config', sandbox=None, approval_policy=None, permission_profile=None):
    data = validate_provider(provider)
    source = rpc.request('thread/read', {'threadId': source_id, 'includeTurns': True})['thread']
    turns = source.get('turns', [])
    if not last_turn:
        completed = [t['id'] for t in turns if t.get('status') == 'completed']
        if not completed:
            raise RuntimeError('No completed turn to fork; source unchanged')
        last_turn = completed[-1]
    # Select a completed boundary; compatibility is decided by the native fork API.
    selected = []
    for turn in turns:
        selected.append(turn)
        if turn['id'] == last_turn:
            break
    if not selected or selected[-1]['id'] != last_turn or selected[-1].get('status') != 'completed':
        raise RuntimeError('Requested fork boundary is not a completed turn')
    encoded = json.dumps(selected)
    opaque = 'encrypted_content' in encoded or 'encryptedContent' in encoded or 'contextCompaction' in encoded
    # Keep allow_opaque for callers of older helpers; inspection is no longer a gate.
    # An opaque marker or paginated history alone does not demonstrate incompatibility.
    target_model = model or source.get('model') or data.get('model', 'gpt-6.1-sol')
    requested, expected = permission_request(rpc, source.get('cwd'), target_model, provider,
        permission_mode, sandbox, approval_policy, permission_profile)
    params = {'threadId': source_id, 'modelProvider': provider, 'model': target_model,
              'lastTurnId': last_turn, 'excludeTurns': True,
              'config': {'features.memories': False}, 'serviceTier': 'default', **requested}
    result = rpc.request('thread/fork', params)
    ident = verify(result, provider)
    permissions = permission_receipt(result, permission_mode, requested, expected)
    name = title_for(provider, source.get('name') or source.get('preview') or source_id)
    rpc.request('thread/name/set', {'threadId': ident, 'name': name})
    saved = rpc.request('thread/read', {'threadId': ident, 'includeTurns': False})['thread']
    if saved.get('modelProvider') != provider:
        raise RuntimeError(f'Fork created but metadata verification failed: {ident}')
    return {'threadId': ident, 'sourceThreadId': source_id, 'provider': provider, 'model': result.get('model'),
            'name': name, 'lastTurnId': last_turn, 'opaqueHistoryDetected': opaque,
            'compatibilityAssessment': 'not-tested-until-continuation', 'verified': True,
            'inferenceStarted': False, 'defaultProvider': data.get('model_provider', 'openai'),
            'transport': rpc.transport, **permissions}


def status():
    data = settings()
    auth_path = HOME / 'auth.json'
    auth = json.loads(auth_path.read_text(encoding='utf-8-sig')) if auth_path.exists() else {}
    return {'defaultProvider': data.get('model_provider', 'openai'), 'officialLoginCached': bool(auth.get('tokens')),
            'configSha256': hashlib.sha256((HOME/'config.toml').read_bytes()).hexdigest(),
            'officialDirectConfigured': not bool(data.get('openai_base_url') or os.environ.get('OPENAI_BASE_URL')),
            'providers': list(LABELS), 'home': str(HOME)}


def handoff_thread(rpc, source_id, provider, summary, model=None, *,
                   permission_mode='config', sandbox=None, approval_policy=None, permission_profile=None):
    data = validate_provider(provider)
    if not summary.strip() or len(summary) > 100000:
        raise RuntimeError('Summary must be nonempty and at most 100000 characters')
    source = rpc.request('thread/read', {'threadId': source_id, 'includeTurns': False})['thread']
    target_model = model or source.get('model') or data.get('model', 'gpt-6.1-sol')
    requested, expected = permission_request(rpc, source['cwd'], target_model, provider,
        permission_mode, sandbox, approval_policy, permission_profile)
    result = rpc.request('thread/start', {'modelProvider': provider, 'model': target_model,
        'cwd': source['cwd'], 'serviceTier': 'default', 'config': {'features.memories': False}, **requested})
    ident = verify(result, provider)
    permissions = permission_receipt(result, permission_mode, requested, expected)
    name = title_for(provider, source.get('name') or source.get('preview'))
    rpc.request('thread/name/set', {'threadId': ident, 'name': name})
    # Persist plaintext as model-visible user history, not transient runtime instructions.
    rpc.request('thread/inject_items', {'threadId': ident, 'items': [{'type': 'message', 'role': 'user',
        'content': [{'type': 'input_text', 'text': 'Task handoff from another provider (plaintext summary):\n'+summary}]}]})
    saved = rpc.request('thread/read', {'threadId': ident, 'includeTurns': False})['thread']
    if saved.get('modelProvider') != provider:
        raise RuntimeError(f'Handoff metadata verification failed: {ident}')
    return {'threadId': ident, 'sourceThreadId': source_id, 'provider': provider, 'name': name, 'mode': 'plaintext-handoff',
            'verified': True, 'inferenceStarted': False, 'summarySha256': hashlib.sha256(summary.encode()).hexdigest(),
            **permissions}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--transport', choices=['auto', 'stdio', 'daemon'], default='auto')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('status')
    default = sub.add_parser('default', help='Persist this host default without changing existing threads')
    default.add_argument('--provider', choices=ALIASES, required=True)
    ls = sub.add_parser('list'); ls.add_argument('--limit', type=int, default=20)
    branch = sub.add_parser('fork')
    branch.add_argument('--thread', required=True); branch.add_argument('--provider', choices=ALIASES, required=True)
    branch.add_argument('--last-turn'); branch.add_argument('--model'); branch.add_argument('--request-id', default=None)
    branch.add_argument('--mode', choices=['session', 'persistent'], default='session')
    handoff = sub.add_parser('handoff')
    handoff.add_argument('--thread', required=True); handoff.add_argument('--provider', choices=ALIASES, required=True)
    handoff.add_argument('--summary-file', type=Path, required=True); handoff.add_argument('--model')
    handoff.add_argument('--mode', choices=['session', 'persistent'], default='session')
    handoff.add_argument('--request-id')
    for command in (branch, handoff):
        command.add_argument('--permission-mode', choices=['config', 'inherit'], default='config',
                             help='Use current effective config (default), or native source inheritance')
        group = command.add_mutually_exclusive_group()
        group.add_argument('--sandbox', choices=SANDBOX_TYPES)
        group.add_argument('--permission-profile', help='Named permission profile, where supported by the server')
        command.add_argument('--approval-policy', choices=['on-request', 'never'])
    args = parser.parse_args()
    if args.command == 'status':
        print(json.dumps(status(), ensure_ascii=False)); return
    if args.command == 'default':
        print(json.dumps(set_default(ALIASES[args.provider]), ensure_ascii=False)); return
    snapshot = config_snapshot()
    with Rpc(args.transport) as rpc:
        if args.command == 'list':
            items = rpc.request('thread/list', {'modelProviders': [], 'limit': min(100, args.limit), 'useStateDbOnly': True, 'archived': False})['data']
            print(json.dumps([{'id': t['id'], 'name': t.get('name'), 'provider': t.get('modelProvider')} for t in items], ensure_ascii=False)); return
        provider = ALIASES[args.provider]
        request_id = args.request_id or str(uuid.uuid4())
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', request_id):
            raise RuntimeError('Invalid request id')
        folder = HOME / 'provider-fork/receipts'; folder.mkdir(parents=True, exist_ok=True)
        path = folder / (request_id + '.json')
        operation = {'sourceThreadId': args.thread, 'provider': provider, 'requestedModel': args.model,
                     'requestedLastTurnId': getattr(args, 'last_turn', None), 'switchMode': args.mode,
                     'permissionMode': args.permission_mode, 'requestedSandbox': args.sandbox,
                     'requestedApprovalPolicy': args.approval_policy, 'requestedPermissionProfile': args.permission_profile}
        if args.command == 'handoff':
            summary = args.summary_file.read_text(encoding='utf-8-sig')
            operation['summarySha256'] = hashlib.sha256(summary.encode()).hexdigest()
        if path.exists():
            previous = json.loads(path.read_text())
            if any(previous.get(k, 'session' if k == 'switchMode' else None) != v for k, v in operation.items()):
                raise RuntimeError('Request id belongs to a different operation')
            if not previous.get('verified'):
                raise RuntimeError('Prior operation has unknown outcome; inspect it before retrying')
            print(json.dumps(previous, ensure_ascii=False))
            if previous.get('persistentApplied') is False:
                sys.exit(2)
            return  # Never reapply an old persistent default over a newer user choice.
        with path.open('x', encoding='utf-8') as f:
            json.dump({**operation, 'state': 'pending'}, f)
        if args.command == 'handoff':
            receipt = handoff_thread(rpc, args.thread, provider, summary, args.model,
                permission_mode=args.permission_mode, sandbox=args.sandbox,
                approval_policy=args.approval_policy, permission_profile=args.permission_profile)
        else:
            receipt = fork(rpc, args.thread, provider, args.model, args.last_turn,
                permission_mode=args.permission_mode, sandbox=args.sandbox,
                approval_policy=args.approval_policy, permission_profile=args.permission_profile)
        receipt.update(operation)
        if args.mode == 'persistent':
            persist_branch(receipt, provider, snapshot)
        path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(receipt, ensure_ascii=False))
        if receipt.get('persistentApplied') is False:
            sys.exit(2)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(json.dumps({'error': redact(error), 'originalThreadChanged': False}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)
