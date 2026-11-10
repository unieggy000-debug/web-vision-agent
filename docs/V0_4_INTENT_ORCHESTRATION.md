# V0.4 draft: Intent routing and multi-site orchestration

This is a draft integration layer on top of the V0.3 batch scheduler.
The user's Windows workspace contains additional V0.1/V0.3 changes not
necessarily present on GitHub; integrate files carefully. Do not merge the PR
or overwrite local source.

## Design and implementation status

Natural-language goal
→ intent routing / optional one-shot LLM intent classification
→ target URL validation / search-based candidate discovery
→ capped per-site manifest
→ independent per-site Single Agent worker processes (agent.batch)
→ deterministic batch-status aggregate
→ **separate business-quality review**

The planner supports:
- Named website(s): extract only URLs literally present in the user request.
- Website discovery requests: on explicit live execution, classify intent once
  and use the real Tavily search result to obtain candidate URLs. The LLM is
  NOT allowed to invent site URLs. Results are candidates, NOT confirmed fit.
- Multi-URL requests: split into at most 5 independent site tasks.
- Mixed research + application generation: research is supported, application
  generation is ONLY flagged for an external handoff. There is NO working
  template generator integration or result synthesis model in this draft.
- Out-of-scope and generation-only requests: do not dispatch research workers.

Each site task has its own worker, AgentState, History and Trace.
The outer scheduler is process-isolated and capped at 2 workers by this CLI.
Workers in the existing architecture still open Chromium per tool call:
this is NOT a shared-browser-context architecture.

## Commands

Offline (no API calls, no DB writes):

    python -m agent.orchestrate "研究 https://linear.app 和 https://www.framer.com 并保存案例"
    python -m unittest scripts.test_intent_orchestrate -v
    python -m scripts.score_intent_eval

The deterministic routing scorecard contains 12 designed cases; it is a
development smoke test, not an unbiased measure of production intent accuracy.

ONLY after integrating with the local source and inspecting test-project identity:

    python -m agent.orchestrate "研究 https://linear.app 并保存案例" --workers 1 --env-file .env.batch-test --execute

For a later parallel E2E, pick *two previously unused URLs*. Do not repeat a URL
from the one-site smoke test: it may already be in the test DB.

Default preview never calls models/search/DB. --execute requires an explicit
distinct .env file and applies the existing V0.3 batch safeguards.

## Rubric: do not conflate technical and business success

Use independent checks and keep "not measured" separate from "passed".

| Level | Suggested check | Automatic vs human |
| --- | --- | --- |
| Intent planning | Correct intent; exact requested URLs; no fabricated targets | Offline auto against labeled cases |
| Orchestration | Exactly one task per target; stable task IDs; no shared state | Auto/unit and worker tests |
| Technical completion | Each task has run_id, finished status, expected tool results | Auto against artifacts |
| Persistence | Research case saved with correct URL; embedding and semantic retrieval work | DB readback and auto checks |
| Evidence integrity | No unverified framework claim; screenshot coverage documented | Rules + human review |
| Visual quality | Relevant, accurate analysis of layout/color/typography/effects | Evidence-based human Rubric |
| Efficiency | Decision tokens, model/tool count, duration and resource usage | Trace/metrics; set thresholds based on baseline |

A task that is technically finished can still fail the business Rubric.
business_pass is deliberately null in the aggregate until independently judged.

## Next acceptance experiment

1. Integrate only new modules into the Windows workspace.
2. Confirm local requirements and env-file safeguards; never print keys.
3. Run the 13 offline regressions and 12 routing samples.
4. Choose a new URL not already stored in the isolated Supabase test project.
5. Dry-run a one-site query, then run exactly one live Agent task with workers=1.
6. Inspect routing, artifact, Trace, screenshot coverage, framework evidence,
   saved case, embedding status and DB readback. Apply the business Rubric.
7. Only if the one-site case passes the required gates, run two different new
   URLs with workers=2. Verify task histories and DB rows remain isolated.
8. Record all failures and their step/span identifiers; do not rerun blindly.

## Known limitations / risks

- No production-level intent classifier evaluation; actual semantic LLM
  classification has not been exercised with API calls.
- Candidate discovery searches can return listing sites, irrelevant pages,
  or sites that change. Qualify candidates before using them as a benchmark.
- Normalized URL and cross-project identity checks cannot detect every
  custom-domain alias. Confirm test project identity manually.
- No support for generating apps, coordinating dependencies between research
  and app generation, or LLM-based final synthesis.
- Existing screenshot partial-coverage issues remain; success requires a
  separate capture-quality check.
- Batch execution writes goals in local manifests and can write case records
  in the configured DB. Avoid sensitive inputs.
