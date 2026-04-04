# Step 6 — First Observability Implementation Plan

## A. Overview

### Core Scope

The goal of this version is to **fill in the uncovered portions of the P0 signals defined in Step 4**, so that run-level and stage-level observation forms a complete closed loop. Changes are concentrated in two files (`runner.py`, `notify.py`); no new metrics are added, no new modules are added, and `instrument.py` is not modified.

### Guiding Principles

1. **P0 only**: P1 signals are already fully covered — no action needed. P2 is out of scope for this version.
2. **Reuse existing wrappers**: all new stage coverage is landed via the existing `log_stage()` context manager; no new abstractions invented.
3. **Minimal invasiveness**: do not change metric definitions in `instrument.py`, do not change pipeline control flow semantics, do not change the `PipelineResult` structure.
4. **After these changes, every pipeline stage will have consistent `stage.completed` / `stage.failed` structured events + `STAGE_DURATION` metric + `STAGE_ERRORS` metric**. Currently two stages (dedupe, cache invalidate) lack this consistency.

---

## B. Implementation Scope

### In Scope

- **Run started event**: emit `pipeline.started` event at the beginning of `run_pipeline()`
- **Run finished event fix**: move existing `pipeline.finished` into the `finally` block and add missing fields (`completion_status`, `duration`, `input_count`)
- **Dedupe stage structured wrapping**: wrap each URL's dedupe query with `log_stage("dedupe")`
- **Cache invalidate stage structured wrapping**: wrap the `cache.clear()` call with `log_stage("cache_invalidate")`
- **Notify error visibility fix**: let `notify()` failures be captured by the outer `log_stage("notify")` error path

### Out of Scope

- Do not change `instrument.py` (no new metrics, no modification of existing metric labels)
- Do not change the `PipelineResult` dataclass
- Do not integrate the Celery task layer logs in `tasks.py` with `run_pipeline()` layer logs (redundancy is temporarily acceptable)
- Do not add P2 downstream visibility signals (notify outcome / cache invalidation outcome as independent events)
- Do not set dashboards, alert thresholds, or alert rules
- Do not name or rename any Prometheus metrics
- Do not add new files beyond tests

---

## C. File / Code-path Plan

| Signal | Priority | Granularity | Current coverage | Best implementation point | Reuse existing structure? | Planned change |
|--------|----------|-------------|-----------------|--------------------------|--------------------------|----------------|
| Run started | P0 | run-level | Partially covered | `runner.py` — beginning of `run_pipeline()`, after contextvars binding | Yes — use existing `logger.info()` | Add `logger.info("pipeline.started")`; run_id and source automatically carried by contextvars |
| Run finished | P0 | run-level | Partially covered | `runner.py` — inside `finally` block, immediately after `RUN_DURATION.observe()` | Yes — rewrite existing `logger.info("pipeline.finished")` | Move `pipeline.finished` into `finally`; add `duration`, `input_count`, `completion_status` fields; initialize tracking variables before the try block (`input_count`, error flag) |
| Stage outcome (dedupe) | P0 | item-level | Missing | `runner.py` — inside for loop, at `News.objects.filter(...).exists()` call | Yes — use existing `log_stage("dedupe")` | Wrap DB query with `log_stage("dedupe", source=..., url=...)`; set `outcome` in ctx ("new" / "skip"); design decision needed: when dedupe DB query fails, skip that URL (consistent with fetch/parse/persist) or crash the run (current behavior) |
| Stage outcome (cache invalidate) | P0 | run-level | Partially covered | `runner.py` — inside the `if result.created > 0:` block | Yes — use existing `log_stage("cache_invalidate")` | Wrap `cache.clear()` with `log_stage("cache_invalidate", source=...)`; failures logged to `STAGE_ERRORS` by `log_stage` but should not crash the run |
| Stage outcome (notify) | P0 | item-level | Partially covered | `notify.py` — exception handling; `runner.py` — notify call site | Partial — `log_stage("notify")` already exists but cannot see failures | Remove the internal try/except from `notify.py` (let exceptions re-raise); add try/except around the `log_stage("notify")` in `runner.py` to prevent pipeline interruption. This allows `log_stage` to capture the exception → `stage.failed` event + `STAGE_ERRORS` metric |
| Stage duration (dedupe) | P0 | item-level | Missing | Same as Stage outcome (dedupe) | Yes | Automatically obtained after `log_stage()` wrapping; no additional action needed |
| Stage duration (cache invalidate) | P0 | run-level | Missing | Same as Stage outcome (cache invalidate) | Yes | Automatically obtained after `log_stage()` wrapping; no additional action needed |

**P0 signals that do not need changes (confirmed "Already covered" in Step 5):**

| Signal | Reason |
|--------|--------|
| Stage outcome (discover) | `log_stage("discover")` fully covered |
| Stage outcome (fetch) | `log_stage("fetch")` fully covered |
| Stage outcome (parse) | `log_stage("parse")` fully covered |
| Stage outcome (persist) | `log_stage("persist")` fully covered |
| Run duration metric | `RUN_DURATION` already observed in `finally` block |
| Stage duration (discover/fetch/parse/persist) | `log_stage()` automatically observes to `STAGE_DURATION` |
| Processing counts metric | `ARTICLES_TOTAL` already incremented at each point |

---

## D. Implementation Sequence

### Step 1: Fix Run started + Run finished events

**What to change:** in `run_pipeline()` in `runner.py`:

- After contextvars binding, before the `try` block: add `pipeline.started` event.
- Before the `try` block: initialize tracking variables: `input_count = 0`, error flag (used in `finally` to derive completion_status).
- Move the existing `pipeline.finished` (currently at lines 143–148, outside `finally`) into the `finally` block, immediately after `RUN_DURATION.observe()`.
- Add three fields to the moved `pipeline.finished`: `duration` (seconds), `input_count` (number of discovered URLs), `completion_status` (derived from error flag and result's created/failed/skipped counts).

**Why to do this first:** Run started + Run finished is the topmost pair of the entire observability skeleton. Without a reliable run finished, there is no way to tell whether a run crashed, whether it completed normally, or how long it took. This is a prerequisite for all subsequent stage-level analysis.

**Observability gained after completion:**
- Every run will definitely have a paired `pipeline.started` and `pipeline.finished` (including crashes and early returns).
- `pipeline.finished` can be directly read for completion_status, duration, input_count, created/skipped/failed.
- Two consecutive `pipeline.started` with no `pipeline.finished` in between → overlapping execution or crash.

### Step 2: Add log_stage wrapping for the dedupe stage

**What to change:** inside the for loop in `runner.py`, wrap `News.objects.filter(source_url=url).exists()` with `log_stage("dedupe", source=..., url=...)`. Set `outcome` in ctx as "new" or "skip."

A small design decision is needed: if the dedupe DB query raises an exception, what should happen? The current behavior is to crash the entire for loop. Recommended change: consistent with fetch/parse/persist — on failure, log the error, skip the URL, continue to the next one. This requires a try/except outside `log_stage("dedupe")` and `result.failed += 1` + `ARTICLES_TOTAL` fail increment + `continue` in the except block.

**Why second:** dedupe is the only stage in the ingestion main flow completely missing structured events and duration metrics. After this fix, all per-item stages have consistent `log_stage()` coverage.

**Observability gained after completion:**
- Dedupe stage has `stage.completed` / `stage.failed` structured events (with duration and outcome).
- `STAGE_DURATION` histogram starts receiving `stage="dedupe"` observations → can track whether dedupe DB queries are slowing down.
- Dedupe DB query failures appear in the `STAGE_ERRORS` metric.

### Step 3: Add log_stage wrapping for the cache invalidate stage

**What to change:** inside the `if result.created > 0:` block in `runner.py`, wrap `cache.clear()` with `log_stage("cache_invalidate", source=...)`. Remove the existing `pipeline.cache_cleared` log (its function is replaced by the `stage.completed` event from `log_stage`).

Cache invalidate failure should not crash the run: if `cache.clear()` raises, `log_stage` records it in `STAGE_ERRORS`, but the outer layer needs a try/except to prevent affecting the run's completion_status.

**Why third:** smallest effort (one `with` statement), and after completion all run-level stages have consistent coverage.

**Observability gained after completion:**
- Cache invalidate has `stage.completed` / `stage.failed` structured events.
- `STAGE_DURATION` histogram receives `stage="cache_invalidate"` observations.
- `cache.clear()` failures appear in the `STAGE_ERRORS` metric, no longer an untracked crash.

### Step 4: Fix notify error visibility

**What to change:** two locations:

1. **`notify.py`**: remove the try/except inside the `notify()` function, letting exceptions propagate naturally.
2. **`runner.py`**: add a try/except around the existing `with log_stage("notify", ...)` block, catching the exception and doing nothing (`log_stage` has already recorded `stage.failed` + `STAGE_ERRORS`). This preserves the original semantics of "notify failure does not affect pipeline completion."

**Why last:** this change touches two files and must be done together atomically to work correctly (changing only `notify.py` without `runner.py` would cause notify failures to crash the pipeline). The first three steps only touch `runner.py` and can be completed and verified independently.

**Observability gained after completion:**
- Notify failures correctly appear in `stage.failed` events and the `STAGE_ERRORS` metric.
- Failure still does not affect pipeline completion → `pipeline.finished`'s completion_status is not affected by notify failures.

---

## E. Acceptance Criteria

The following are specific outcomes that should be verifiable after the first version is complete. Each can be confirmed by running the pipeline once and checking logs/metrics.

### Run Lifecycle

1. Run `manage.py scrape_news` → `pipeline.started` event appears in log, with `run_id` and `source`.
2. Same run → `pipeline.finished` event appears in log, with `run_id`, `source`, `completion_status`, `duration`, `input_count`, `created`, `skipped`, `failed`.
3. Manually cause a failure in the discover stage (e.g., disconnect network) → `pipeline.finished` still appears, `completion_status` is "error", `input_count` is 0.
4. With empty URLs (discover returns empty list) → `pipeline.finished` still appears, `completion_status` reflects normal completion, `input_count` is 0.

### Stage Consistency

5. Run a pipeline with a mix of new and existing URLs → `stage.completed` events appear with `stage="dedupe"`, one per URL, each with `outcome` ("new" / "skip") and `duration_ms`.
6. Run a pipeline that produces new articles → `stage.completed` event appears with `stage="cache_invalidate"`, with `duration_ms`.
7. Manually cause a notify failure (e.g., channel layer misconfiguration that raises an exception) → `stage.failed` event appears with `stage="notify"`, with `error_type`. Pipeline still completes normally (`pipeline.finished`'s `completion_status` is not "error").

### Metric Coverage

8. After running the pipeline once, query Prometheus metrics → `scraper_stage_duration_seconds` histogram contains observations with `stage="dedupe"` and `stage="cache_invalidate"`.
9. Manually cause a notify failure → `scraper_stage_errors_total` counter shows increment with `stage="notify"`.

### No Regressions

10. Existing `stage.completed` events (discover, fetch, parse, persist) fields and behavior are unchanged.
11. Existing `ARTICLES_TOTAL`, `RUN_DURATION` metric behavior is unchanged.
12. Notify failures still do not affect the pipeline's final return value (`PipelineResult`'s created/skipped/failed counts are not affected by notify).

---

## F. Risks / Things to Avoid

### 1. Do not over-engineer the completion_status derivation logic

`completion_status` should be a simple three-value determination (e.g., "success" / "partial" / "error"), based on the already-available `result.created`, `result.failed`, and error flag. Do not add a complex state machine or attempt to enumerate a dozen status values.

### 2. Do not change the skip count semantics when adding log_stage wrapping for dedupe

Currently, dedupe skip and persist skip share the `ARTICLES_TOTAL`'s `outcome="skip"` label. After adding `log_stage("dedupe")`, do not add a dedupe-specific counter, and do not change the `ARTICLES_TOTAL` increment logic. The structured event from `log_stage` (`stage.completed` with `outcome="skip"`) is already sufficient for distinction.

### 3. The notify try/except move must be done atomically

Removing the try/except from `notify.py` and adding the try/except in `runner.py` must be done in the same change. If only `notify.py` is changed but `runner.py` is forgotten, notify failures will crash the entire pipeline — which is worse than the current behavior.

### 4. Do not let pipeline.finished's fields balloon

`pipeline.finished` only needs the minimum field set defined in Step 4: `completion_status`, `duration`, `input_count`, `created`, `skipped`, `failed`. Do not add per-stage breakdowns (e.g., error count per stage) or timing breakdowns in this version. If needed, these should be queried from stage outcome events, not stuffed into run finished.

### 5. Do not refactor the runner's for loop structure just to add dedupe/cache_invalidate log_stage

The current for loop in `runner.py` uses a try/except + continue pattern to progress through stages. Adding dedupe's `log_stage()` should be embedded in this existing pattern — do not refactor the entire for loop into a stage pipeline pattern or chain-of-responsibility for the sake of "elegance."

### 6. Do not touch the Celery task layer logs in tasks.py

`tasks.py` already has `celery.scrape_started` / `celery.scrape_finished`. After `run_pipeline()` adds `pipeline.started` / `pipeline.finished`, there will be two layers of logs. This redundancy is temporarily acceptable — Celery-layer logs provide task-level observation (e.g., task retry, task timeout) and are complementary to pipeline-level logs. Integration is for a later phase.

---

## G. Change Scope Summary

| File | Nature of change | Estimated size |
|------|-----------------|----------------|
| `news/pipeline/runner.py` | Add pipeline.started, fix pipeline.finished, add dedupe log_stage, add cache_invalidate log_stage, notify outer try/except | Medium (~30–40 line diff) |
| `news/pipeline/notify.py` | Remove internal try/except | Small (~5 line diff) |
| `news/pipeline/instrument.py` | No change | — |
| `news/pipeline/types.py` | No change | — |
| `news/pipeline/persist.py` | No change | — |
| `news/tasks.py` | No change | — |
