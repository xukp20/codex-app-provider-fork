<h1 align="center">Codex App Provider Fork</h1>

<p align="center">
  <strong>English</strong> |
  <a href="README.zh-CN.md">简体中文</a>
</p>

<p align="center">
  <strong>Switch providers through a new Codex task fork, with an optional persistent default.</strong>
</p>

<p align="center">
  <a href="skills/provider-fork/SKILL.md">
    <img alt="Codex Skill" src="https://img.shields.io/badge/Codex-Skill-2563eb?style=flat-square">
  </a>
  <a href="https://www.python.org/">
    <img alt="Python 3.11+" src="https://img.shields.io/badge/Python-3.11%2B-172554?style=flat-square">
  </a>
  <img alt="Transport" src="https://img.shields.io/badge/transport-App%20Server-0f8f88?style=flat-square">
  <img alt="Status" src="https://img.shields.io/badge/status-experimental-d97706?style=flat-square">
</p>

<p align="center">
  <a href="#why-this-exists">Why</a>
  &middot;
  <a href="#capabilities">Capabilities</a>
  &middot;
  <a href="#switch-modes">Switch modes</a>
  &middot;
  <a href="#install">Install</a>
  &middot;
  <a href="skills/provider-fork/SKILL.md">Skill Reference</a>
</p>

Codex App Provider Fork packages the `provider-fork` skill and a Python helper
for switching between an existing official login, BeeAPI, and Krill Code.
It forks completed task history with an explicit target provider, names the
new task, and checks the returned and saved provider metadata. The source
task stays intact, and the helper never writes `auth.json` or starts inference.

The default **session** mode leaves `config.toml` unchanged. The optional
**persistent** mode first creates and verifies the fork, then changes only
the root `model_provider` for subsequent tasks using that default.

## Why This Exists

Editing a global provider setting does not immediately replace the provider
of a task already loaded by an App Server. Repeatedly restarting the app to
switch providers can also interrupt unrelated work.

This skill makes the provider choice explicit at a new branch boundary using
the native `thread/fork` operation. The fork retains completed history and
gets a separate title such as `BeeAPI | Fix parser`. Switching that fork to
Krill produces `Krill Code | Fix parser`, replacing the recognized prefix.

It uses the [Codex App Server protocol](https://developers.openai.com/codex/app-server).
It is a configuration helper and RPC client; it does not proxy inference traffic.

## Capabilities

| Capability | What it provides |
| --- | --- |
| Provider-specific forks | A new task with an explicit provider and a completed history boundary |
| Session switching | A fork without changing the global default |
| Persistent switching | A verified fork followed by a minimal default-provider edit |
| Default-only changes | Change or restore the default without creating a task |
| Official login preservation | No login/logout commands or writes to `auth.json` |
| Predictable titles | `Official |`, `BeeAPI |`, or `Krill Code |` replaces an existing recognized prefix |
| Operation receipts | Provider readback, source/new task IDs, mode, and inference status |
| Retry recovery | A request ID returns the verified receipt without creating another fork or replaying an old default change |
| Read-only inspection | Inspect the configured default and list recent task IDs |

Supported names are `official` / `openai`, `beeapi`, and `krill` / `krill-code`.
Third-party definitions and credentials must already exist in the target
Codex configuration. Additional providers currently require extending the
helper's aliases and labels.

## Switch Modes

| Mode | Changes user config? | Result |
| --- | --- | --- |
| `fork --mode session` (default) | No | A new task saves the requested provider |
| `fork --mode persistent` | Only root `model_provider` | A verified fork plus a new default for subsequent tasks |
| `default` | Only root `model_provider` | A new default without a fork |

The default change does not switch other loaded tasks. Explicit profiles,
project configuration, or model/provider overrides can take precedence over
the user-level default. Persistent mode does not remove those overrides.

### What happens after restart?

In the tested Codex versions, an ordinary resume without model-related
overrides restores a task's saved model/provider. A session-mode fork can
therefore remain on BeeAPI while the global default stays official.

Explicit model/provider settings or selected profiles can change that
precedence. In particular, a model-only override can cause the App Server to
use the current default provider. The helper does not intercept App or CLI
resume requests; provider definitions must remain in config, and direct RPC
callers should specify `modelProvider` and verify the effective result.

## Install

Requires Python 3.11+ and a compatible Codex executable. Only the daemon
transport needs the dependency in `requirements.txt`.

### Linux / Unix

```bash
git clone https://github.com/xukp20/codex-app-provider-fork.git
cd codex-app-provider-fork
python -m pip install -r requirements.txt
mkdir -p "${CODEX_HOME:-$HOME/.codex}/skills"
ln -s "$PWD/skills/provider-fork" \
  "${CODEX_HOME:-$HOME/.codex}/skills/provider-fork"
```

A linked install can be updated with `git pull --ff-only`.

### Windows PowerShell

```powershell
git clone https://github.com/xukp20/codex-app-provider-fork.git
Set-Location codex-app-provider-fork
$codexDir = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $env:USERPROFILE '.codex' }
$skillsDir = Join-Path $codexDir 'skills'
New-Item -ItemType Directory -Force -Path $skillsDir | Out-Null
Copy-Item -LiteralPath '.\skills\provider-fork' -Destination $skillsDir -Recurse
```

Reload skill discovery after installation. A copied installation must be
updated separately after pulling repository changes. If `provider-fork`
already exists, update its files in place rather than copying a directory
inside it.

### Provider configuration

Merge provider definitions into your existing user `config.toml`; preserve
the rest of the file and your official login. The following addresses are
placeholders, not working service endpoints:

```toml
# Root setting, before any [table]. Keep official as the initial default.
model_provider = "openai"

[model_providers.beeapi]
name = "BeeAPI"
base_url = "https://YOUR-BEEAPI-ENDPOINT/v1"
wire_api = "responses"
requires_openai_auth = false
env_key = "BEEAPI_API_KEY"

[model_providers.krill-code]
name = "Krill Code"
base_url = "https://YOUR-KRILL-ENDPOINT/v1"
wire_api = "responses"
requires_openai_auth = false
env_key = "KRILL_CODE_API_KEY"
```

Set each named environment variable to that provider's own credential in the
environment inherited by the App Server. Setting it only in a new terminal
does not update an already-running daemon. Existing
`experimental_bearer_token` definitions are supported, but contain plaintext
secrets and should stay private. Do not put official login tokens into either
definition. See the [Codex configuration reference](https://developers.openai.com/codex/config-reference).

## Use

Ask Codex, for example:

> Use $provider-fork to fork this task to BeeAPI. Keep the global default unchanged.

> Use $provider-fork to fork task THREAD_ID to Krill and make Krill the persistent default.

> Use $provider-fork to restore the default to official.

Or run the helper directly from the repository root:

```bash
python skills/provider-fork/scripts/provider_fork.py status
python skills/provider-fork/scripts/provider_fork.py list --limit 30
python skills/provider-fork/scripts/provider_fork.py fork \
  --thread THREAD_ID --provider beeapi --mode session --request-id bee-switch-001
python skills/provider-fork/scripts/provider_fork.py fork \
  --thread THREAD_ID --provider krill --mode persistent --request-id krill-switch-001
python skills/provider-fork/scripts/provider_fork.py default --provider official
```

Use a new request ID for each new operation and reuse it only to recover that
same operation. `--model` selects a target-supported model; otherwise the
source model is retained. `--last-turn` selects a completed boundary;
otherwise the helper uses the last completed turn returned by the server.

Check `verified: true`, the requested provider, and the new `threadId`.
Persistent mode additionally requires `persistentApplied: true`. An exit
code of `2` means a verified fork exists but the default change failed;
inspect that receipt and current config before changing the default separately.

Fork creation confirms provider metadata. It does not prove that the target
can continue every inherited history item. Continue the new task in Codex
when ready; the switch itself starts no model turn. Open the returned task ID
in the App and confirm it is readable. Visibility and live sidebar refresh
depend on the App build.

### Transport selection

| Transport | Behavior |
| --- | --- |
| `auto` on Windows | Starts a temporary stdio App Server using the same `CODEX_HOME` |
| `auto` on other platforms | Connects to the existing daemon's Unix control socket |
| `--transport stdio` | Uses a temporary child process; requires a compatible Codex executable |
| `--transport daemon` | Uses the existing Unix socket; requires `websockets` |

The transport option goes **before** the subcommand. The daemon socket is
`${CODEX_HOME:-$HOME/.codex}/app-server-control/app-server-control.sock`.
Set `CODEX_PROVIDER_CLI` to override executable discovery. Windows discovery
checks the App's bundled executable, then `PATH`; other platforms use `PATH`.

A separate stdio process cannot take over a thread held by another writer.
If a writer lock is reported, inspect the owning server and use its available
transport. The helper never restarts the App or daemon to release a lock.

### Permissions

Provider switching and permission selection are independent. The default
`--permission-mode config` uses the current effective configuration in the
source working directory, including project layers, named profiles, granular
approval policies, and managed restrictions. The server resolves it through
a fresh ephemeral thread, which is unsubscribed immediately, stores no task
history, and starts no inference. The helper explicitly applies the resulting
settings to the new fork and verifies the effective response.

This avoids carrying an old `on-request` approval policy into a fork when the
current configuration is Full Access. Simply omitting the RPC permission
fields can restore the source's saved settings instead. If that native
behavior is desired, use `--permission-mode inherit`; sandbox/profile
restoration depends on what was saved and the server version.
For summary handoff, `inherit` omits overrides on native `thread/start`, so
it uses fresh defaults rather than source-history permissions.

Explicit options are supported for both fork and exceptional handoff:

```bash
python skills/provider-fork/scripts/provider_fork.py fork \
  --thread THREAD_ID --provider krill --sandbox danger-full-access \
  --approval-policy never --request-id full-access-switch-001
python skills/provider-fork/scripts/provider_fork.py fork \
  --thread THREAD_ID --provider beeapi --sandbox read-only \
  --approval-policy never --request-id readonly-switch-001
```

`--permission-profile PROFILE_ID` selects a named permission profile instead
of `--sandbox`; those two options are mutually exclusive. Explicit options
take precedence over the selected permission mode and remain subject to
server restrictions. The receipt includes `requestedPermissions`,
`effectivePermissions`, and `permissionsVerified`. Check both the sandbox
and approval policy: [Full Access](https://learn.chatgpt.com/docs/sandboxing)
means `danger-full-access` together with `never`. Windows `sandbox = "elevated"`
chooses the sandbox implementation; it does not set the approval policy.

These options never edit global approval/sandbox settings or change existing
branches. Previously created branches need a separate permission change.
Request IDs include permission options; use a new ID when changing them.
Receipts from older helper versions do not certify effective permissions.

## Safety Boundaries

- No writes to `auth.json`, official token copies, direct thread JSONL/SQLite
  edits, logout operations, or source-provider changes.
- Official switching refuses root `openai_base_url` and `OPENAI_BASE_URL`
  overrides. Third-party switching refuses non-HTTPS endpoints, definitions
  requesting official authentication, and definitions without a provider
  credential setting. These checks cover the inspected user config and
  helper environment, not every external configuration layer or network proxy.
- Persistent edits preserve other TOML values, formatting where supported,
  and file permissions. Original config backups are private data under
  `$CODEX_HOME/provider-fork/backups/`; they may contain credentials.
  Detected concurrent edits block replacement.
- Receipts are stored under `$CODEX_HOME/provider-fork/receipts/`. An uncertain
  operation is not automatically retried. A previously successful persistent
  receipt does not overwrite a later intentional default change.
- New branches use resolved configuration or explicitly selected permissions,
  disabled memories, and the default service tier. The helper does not auto-approve
  interactive server requests. These permissions are not strong isolation
  against an untrusted model accessing local credential files.
- Forked history is sent to the selected provider when inference continues.
  Review sensitive history before switching. Login preservation does not
  imply a guarantee about any service's account-enforcement decisions.

Native fork is the normal path. Read
[failure recovery](skills/provider-fork/references/failure-recovery.md) only
after an actual failure; summary handoff is an exceptional fallback.

## Repository Layout

```text
codex-app-provider-fork/
├── README.md
├── README.zh-CN.md
├── LICENSE
├── requirements.txt
├── tests/
└── skills/
    └── provider-fork/
        ├── SKILL.md
        ├── agents/openai.yaml
        ├── references/failure-recovery.md
        └── scripts/provider_fork.py
```

The root README is repository documentation. Only `skills/provider-fork/`
is installed into the Codex skills directory. The Skill and its reference
are entirely in English and contain no machine-specific routing instructions.

## Validation

```bash
python -m unittest discover -s tests -v
python /path/to/skill-creator/scripts/quick_validate.py skills/provider-fork
```

The default suite tests title replacement, fork failure behavior, provider
guards, and minimal persistent edits without accessing live App state. Native
integration tests are opt-in and use a temporary `CODEX_HOME`, fake credentials,
and a local mock Responses server. They use a real Codex executable but make
no official or third-party inference requests:

```bash
PROVIDER_FORK_NATIVE_TESTS=1 python -m unittest discover -s tests -v
```

In PowerShell, set `$env:PROVIDER_FORK_NATIVE_TESTS = '1'` before running the
same unittest command. The native tests cover fork continuation, dedicated
Authorization headers, config/auth preservation, restart restoration,
resume overrides, persistent receipt recovery, Full Access defaults despite
old source approvals, native inheritance, and explicit restricted/profile settings.

## Compatibility

Experimental. Verified with Codex CLI `0.161.0` on Linux and the Windows App
bundled CLI `0.162.0-alpha.2` (App `26.1002.7124.0`). Short real-provider
forks also succeeded for BeeAPI, Krill Code, and the official route. Those
checks do not establish compatibility with every model, long compacted
history, future App build, or macOS environment. No actual provider rejection
in those tests established that handoff was required.

Re-run the isolated tests after Codex upgrades. Built-in ordinary task tools
remain useful; this helper supplies the explicit provider override and
optional persistent default change that this workflow needs.
