---
name: provider-fork
description: Switch a Codex thread to another provider through a new fork, or change the persistent provider default, while preserving the source thread and official login.
---

# Provider Fork

Use for thread provider switches or changes to the default provider. Supported aliases: `official`, `beeapi`, and `krill`. Use the execution scope requested by the user; do not assume a machine or connection method.

## Modes and commands

Use Python 3.11 or newer with this skill's `scripts/provider_fork.py`:

```text
python "<skill-directory>/scripts/provider_fork.py" status
python "<skill-directory>/scripts/provider_fork.py" list --limit 30
python "<skill-directory>/scripts/provider_fork.py" fork --thread <source-id> --provider beeapi --mode session --request-id <unique-id>
python "<skill-directory>/scripts/provider_fork.py" fork --thread <source-id> --provider krill --mode persistent --request-id <unique-id>
python "<skill-directory>/scripts/provider_fork.py" default --provider official
```

- **Session** (default): fork with an explicit target provider; leave config unchanged. The fork saves its provider and does not expire on restart.
- **Persistent**: when explicitly requested, create and verify the fork, then change only the root `model_provider` in user config. Keep it until the next requested default change.
- **Default only**: use `default` without creating a fork. Restore a previous default using the same command, not an entire config backup.

## Normal workflow

1. Resolve the requested source thread ID; do not assume the most recent thread is the current one. Choose the provider and requested mode.
2. **Fork by default.** Do not require a compatibility audit or summary handoff first. Paginated history or an opaque-history marker alone is not a demonstrated incompatibility. `--last-turn` selects a completed boundary; otherwise use the last completed turn. `--model` selects a target-supported model; otherwise retain the source model.
3. Permissions default to `--permission-mode config`: resolve current effective configuration through a temporary, non-persisted thread without inference, then explicitly apply it to the branch. Do not force `workspace-write/on-request` or assume Full Access. Use `--permission-mode inherit` only when the user wants native source inheritance. Explicit `--sandbox` or `--permission-profile` (mutually exclusive), and `--approval-policy` override the selected mode. Full Access requires both `danger-full-access` and `never`.
4. Verify `verified: true`, the requested provider, `permissionsVerified: true`, `effectivePermissions`, a new thread ID, and `inferenceStarted: false`. Persistent mode also requires `persistentApplied: true`. Confirm app readability and return the new title/link. Titles replace a recognized prefix with `Official |`, `BeeAPI |`, or `Krill Code |` while preserving the source title.

Only if fork creation or continuation actually fails, read [failure recovery](references/failure-recovery.md). Diagnose and repair the concrete failure first; summary handoff is an exceptional fallback.

## Operational boundaries

- Never write `auth.json`, log out, replace the official login, copy official tokens, or edit thread JSONL/SQLite directly. Do not change the source provider or restart services to switch.
- Persistent mode preserves all other config settings and backs up the original under `$CODEX_HOME/provider-fork/backups/` (the user `.codex` directory when unset). Backups may contain credentials; keep them private. Concurrent edits block replacement.
- Refuse official base-URL overrides and third-party routes requiring official authentication, lacking dedicated credentials, or using non-HTTPS endpoints. Do not fall back to official inference after failure.
- A request ID recovers the same verified receipt without creating duplicates or replaying an old default change. Inspect unknown outcomes before retrying. If persistence fails after fork creation, report the usable fork and failed default change, then inspect config before using `default` separately.
- The helper selects its transport; `--transport stdio|daemon` precedes the subcommand. Use an existing daemon where applicable; do not take over another process's loaded thread or archive user threads to release writer locks.
- Ordinary resume can retain the saved provider, but explicit model/provider settings or selected profiles can override it. When calling `thread/resume` directly, pass the intended `modelProvider` and check the effective result. Provider definitions must remain available in config. This helper does not intercept app resume requests.
- Creating a fork does not automatically start inference. Branch permissions do not strongly isolate credential files; use a separate system user or container if the user requires protection from an untrusted model reading credentials.
- Permission options do not edit global approval/sandbox configuration or repair existing branches. Preserve managed restrictions. Native inheritance may restore saved approvals/profile settings rather than the current defaults; report the effective receipt. A request ID includes permission options, so changed options require a new ID.
