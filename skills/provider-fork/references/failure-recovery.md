# Failure recovery

Read this reference only after fork creation or continuation reports an actual failure. Do not use it as a routine preflight.

## Diagnose before replacing history

1. Inspect the error and operation receipt. Determine whether no fork was created, a verified fork exists, or the outcome is unknown. Read existing metadata before retrying an uncertain operation; do not create duplicates.
2. Check the effective provider and model. Use an explicit `modelProvider` for a direct resume. Retain the source thread, and create another fork with a supported `--model` if necessary; do not rewrite its provider. A read-only metadata check is not proof of successful continuation.
3. Repair the identified endpoint, credential, model, transport, or configuration issue within the user's requested scope. A timeout, temporary connectivity failure, active writer lock, or provider mismatch is not evidence that inherited history needs replacing. Connect through the owning app-server where applicable; do not restart services or archive user threads to release locks.
4. Consider plaintext handoff if the failure is specifically tied to copied history and cannot be repaired while retaining that history, or the native fork operation is unavailable after checking the correct server/capabilities. For example, an actual target error rejecting encrypted history can justify handoff. Do not infer such an error merely from encrypted markers or incomplete history inspection.

If fork creation fails, persistent mode has not changed the default. If continuation fails after a successful persistent switch, inspect the receipt and current default, and report their actual state; do not silently claim the default remained unchanged or roll it back over subsequent user edits.

## Exceptional plaintext handoff

Extract a concise task summary from readable source content: objective, constraints, completed work, file paths, results, and next steps. Exclude credentials, raw encrypted blocks, and full logs. Do not invent missing context or claim to decrypt history.

Save it in a temporary UTF-8 file with restricted permissions:

```text
python "<skill-directory>/scripts/provider_fork.py" handoff --thread <source-id> --provider beeapi --summary-file <summary-file> --mode session --request-id <unique-id>
```

Use `--mode persistent` only if the user requested a persistent default switch. The helper creates a new thread and persists the summary as model-visible history without starting inference. Verify the receipt, remove the temporary summary file, and explain that this is a summary handoff rather than a full-history fork.

## Evidence behind this fallback

The short real-provider fork tests succeeded. No tested third-party response demonstrated that copied encrypted or compacted history required handoff. Earlier helper rejections were conservative local checks: paginated history could not be inspected completely. Those checks have been removed as fork gates. An opaque-history indicator in a receipt is informational; successful creation verifies provider metadata, while model compatibility is established when continuation actually runs.
