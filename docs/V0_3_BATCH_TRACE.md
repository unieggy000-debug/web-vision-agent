# V0.3: Bounded Batch Orchestration + Local Trace

This draft GitHub branch is based on the remote main branch, not on any newer
uncommitted Windows workspace. Reconcile local changes with Codex before merge.
No live API requests or Supabase writes were performed in development.

## Changes

- Preserve the existing single-site Agent Loop. The outer scheduler launches
  independent worker processes; each worker has its own State, History, browser
  process, and client objects.
- Control concurrent site execution (default 2, hard upper cap 4 as a safety
  starting point, NOT an optimized value).
- Write incremental JSONL trace spans per run: model/tool timing, tool success,
  JSON parse failures, provider-supplied decision-model token usage.
  Unknown costs and business-quality scores remain null, never guessed.
- Avoid screenshot filename collision by using microseconds plus random bytes.
- Avoid DB generated ID collision via random IDs; preserve existing embeddings
  for duplicate URLs instead of recomputing from incomplete records.
- Record batch_id/task_id in run artifacts; each batch saves per-task logs and a
  manifest updated as tasks complete.

## Important limitations

- This is an orchestrator for ALREADY SPLIT website tasks; it does not parse an
  open-ended request such as "find 30 websites" into 30 independent plans.
- Each worker currently opens a separate Playwright browser per tool call. One
  shared Chromium process is NOT implemented. If implemented later, use a
  separate BrowserContext and Page per task and close them after use.
- DB rows are shared inside the chosen Supabase project; URL uniqueness and
  unique case IDs protect basic concurrent inserts, but they do not isolate
  search results across tests or provide general exactly-once transactions.
- For evaluation do not reuse the production DB. Live batch mode requires a
  distinct environment file with a different Supabase project URL.
- Existing Supabase SQL policies are very permissive for personal use.
  Review RLS/permissions before multi-user deployments.
- No remote Langfuse tracing / Dataset Experiment has been executed; traces
  are local JSONL files only. Use the CURRENT Langfuse Python SDK when adding
  the separate Cloud exporter / experiment adapter.
- The model usage field covers only the decision LLM; usage for the separate
  vision model and Tavily costs is not automatically available.
- The business result must be evaluated against the rubric: finished alone is
  NOT business success.
- Traces avoid raw prompts, raw webpage text and credentials; console logs may
  still contain sensitive data. Do not upload raw logs to Langfuse.

## Commands

Build a manifest from the existing exported Langfuse mixed dataset CSV.
Only controlled_live entries are included; mocked/historical tests are excluded.

    python scripts/prepare_eval_manifest.py vision_agent_evaluation_dataset_v0_2_mixed.csv

Dry run (no API calls or DB writes):

    python -m agent.batch reports/eval_live_manifest.json --workers 2

To run ONE isolated test site: put a one-task manifest in JSON and configure
.env.batch-test with the required API keys and an isolated Supabase test project.

    python -m agent.batch reports/one_site.json --workers 1 --env-file .env.batch-test --execute

Check:
- reports/batches/<batch_id>/manifest.json
- reports/batches/<batch_id>/<task_id>.log
- reports/runs/<run_id>.json
- reports/traces/<run_id>.jsonl

Offline regression:

    python -m unittest scripts.test_batch_v03
    python scripts/test_finish_validation.py
    python scripts/test_run_packaging.py

## Recovery vs reproduction

Production retry: rerun only failed jobs after inspecting failure reasons.
Concurrency bug reproduction: run the involved concurrent subset or the full
batch in an isolated environment with saved inputs, worker cap, DB snapshot,
logs and run IDs. Rerunning only 5 failed tasks may NOT reproduce a race.

## Selective recovery vs full concurrency repro

After a batch finishes, prepare a replay containing ONLY non-finished tasks:

    python scripts/prepare_retry_manifest.py reports/batches/<batch_id>/manifest.json
    python -m agent.batch reports/retry_failed_tasks.json --workers 1

This command is a dry run unless --execute and isolated --env-file are supplied.
It is not automatic retry; evaluate failure type first.

To reproduce a possible shared-resource race, use the original batch task list
from its manifest and re-run the entire relevant group with the SAME concurrency
cap. Logs, original DB snapshot, and task order are needed for deeper diagnosis.
