# Step 5 — Current State Audit and Instrumentation Plan

## A. Overview

### Existing Observability State

The repo already has a usable instrumentation skeleton, centralized in `news/pipeline/instrument.py`:

- **Structured logging**: all pipeline code uses structlog; the `log_stage()` context manager provides a consistent `stage.completed` / `stage.failed` structured event for each stage, including duration and caller-supplied supplemental fields.
- **Prometheus metrics**: four metrics are defined (`ARTICLES_TOTAL` counter, `STAGE_DURATION` histogram, `STAGE_ERRORS` counter, `RUN_DURATION` histogram), covering both the run and stage levels.
- **Run correlation**: `new_run_id()` generates a run_id, which is bound via structlog contextvars; all subsequent logs automatically carry run_id and source.

This skeleton already covers a significant proportion of the signal requirements from Step 4. The main issue is not "no instrumentation at all," but rather **gaps or structural inconsistencies at a few key locations**.

### Existing Coverage of Step 4 P0 Signals

- **Run duration metric**: present, and observed in a `finally` block — reliable.
- **Stage duration metric**: present, automatically observed by `log_stage()`, but the dedupe stage does not use this mechanism.
- **Processing counts metric**: present; `ARTICLES_TOTAL` counter tracks four outcomes: discover/skip/fail/create.
- **Stage outcome event**: `log_stage()` already provides the structured event framework, but dedupe and cache invalidate do not use it.
- **Run started / Run finished event**: where the largest gaps are.

### Gaps Concentrated in Three Areas

1. **Run lifecycle events (Run started / Run finished)**: `run_pipeline()` itself does not emit a clear run started event; a run finished event exists, but it is outside the `finally` block (not emitted on crash), and is missing the key fields required by Step 4 (`completion_status`, `duration`, `input_count`).
2. **Dedupe stage lacks structured wrapping**: all other stages emit events and metrics via `log_stage()`; dedupe alone is handled inline with just a single `logger.info("pipeline.skip")` — no stage duration, no stage error tracking.
3. **Notify silently swallows errors**: `notify.py` internally catches all exceptions without re-raising, so the outer `log_stage("notify")` always sees `stage.completed`, even when notify actually failed.

---

## B. Signal Coverage Table

### P0 Signals

| Signal | Priority | Current status | Current implementation evidence | Gap | Best emission point / location | Recommended action |
|--------|----------|----------------|--------------------------------|-----|-------------------------------|-------------------|
| Run started | P0 | Partially covered | `tasks.py:13` emits `celery.scrape_started` at the Celery task layer; `runner.py:26-27` generates run_id and binds contextvars, but does not emit an event | 1) `run_pipeline()` itself does not emit a run started event; CLI trigger (management command) has no run started record at all 2) Missing `timestamp` field required by Step 4 (structlog adds it automatically, but the semantic intent is unclear) | `runner.py` — beginning of `run_pipeline()`, after run_id generation and contextvars binding | Add a single `logger.info("pipeline.started")` at the top of `run_pipeline()` |
| Run finished | P0 | Partially covered | `runner.py:143-148` emits `pipeline.finished` with created / skipped / failed | 1) Outside `finally` block — not emitted when discover stage throws an exception 2) Missing `completion_status` (success/partial/error) 3) Missing `duration` 4) Missing `input_count` (total number of discovered URLs) | `runner.py` — move into `finally` block, immediately after `RUN_DURATION.observe()` | Move `pipeline.finished` into `finally`; add duration, input_count, completion_status fields |
| Stage outcome (discover) | P0 | Already covered | `runner.py:33-38` uses `log_stage("discover")`; ctx carries `url_count`; both success and failure have structured events | — | — | No action needed |
| Stage outcome (dedupe) | P0 | Missing | `runner.py:47-50` only has `logger.info("pipeline.skip")` per item; no `log_stage()` wrapping, no duration, no stage error tracking | 1) No structured stage event 2) No duration metric for the dedupe stage 3) DB query failures are not captured by `STAGE_ERRORS` | `runner.py` — wrap the `News.objects.filter(...).exists()` call for each URL | Wrap the dedupe query with `log_stage("dedupe")`; note: dedupe is per-item but currently inline in the for loop with `continue` control flow — the wrapping must account for the skip logic integration |
| Stage outcome (fetch) | P0 | Already covered | `runner.py:55-57` uses `log_stage("fetch")`; ctx carries `status_code` and `content_length` | — | — | No action needed |
| Stage outcome (parse) | P0 | Already covered | `runner.py:68-83` uses `log_stage("parse")`; ctx carries `fields_extracted` and `missing_fields` | — | — | No action needed |
| Stage outcome (persist) | P0 | Already covered | `runner.py:101-114` uses `log_stage("persist")`; ctx carries `outcome` ("created" / "skipped") | — | — | No action needed |
| Stage outcome (notify) | P0 | Partially covered | `runner.py:124-126` uses `log_stage("notify")`; ctx carries `delivered=True` | `notify.py:31-34` internally catches all exceptions without re-raising → `log_stage` always records `stage.completed`, even when notify actually failed; failure is only visible in `notify.py`'s own `notify.failed` log, and does not appear in the `STAGE_ERRORS` metric | `notify.py` — make failure state visible to the outer layer | Let `notify()` failure state be sensed by `log_stage` (e.g., return a bool or re-raise and let the runner decide whether to swallow it) |
| Stage outcome (cache invalidate) | P0 | Partially covered | `runner.py:131-135` calls `cache.clear()` directly then logs `pipeline.cache_cleared` | 1) Not inside `log_stage()` — no duration metric, no `STAGE_ERRORS` tracking 2) If `cache.clear()` raises, it bubbles up and affects the entire run | `runner.py` — wrap the `cache.clear()` call with `log_stage("cache_invalidate")` | Add `log_stage()` wrapping |
| Run duration | P0 | Already covered | `instrument.py:37-41` defines `RUN_DURATION` histogram; `runner.py:138-139` observes in `finally` block | — | — | No action needed |
| Stage duration | P0 | Partially covered | `instrument.py:25-29` defines `STAGE_DURATION` histogram; `log_stage()` automatically observes | dedupe does not use `log_stage()` → no duration metric for dedupe; same for cache invalidate | Same fix as stage outcome (dedupe) and (cache invalidate) | Fixed automatically after correcting `log_stage()` coverage for dedupe and cache invalidate |
| Processing counts | P0 | Already covered | `instrument.py:19-23` defines `ARTICLES_TOTAL` counter; `runner.py` increments at discover / skip / fail / create | — | — | No action needed |

### P1 Signals (Quality Enrichments)

| Signal | Priority | Current status | Current implementation evidence | Gap | Best emission point / location | Recommended action |
|--------|----------|----------------|--------------------------------|-----|-------------------------------|-------------------|
| Discover: URL count | P1 | Already covered | `runner.py:35` sets `ctx["url_count"]`; `runner.py:36-38` increments `ARTICLES_TOTAL` discover outcome by url count | — | — | No action needed |
| Fetch: response size | P1 | Already covered | `runner.py:57` sets `ctx["content_length"] = len(raw_html)` | — | — | No action needed |
| Parse: field completeness | P1 | Already covered | `runner.py:71-83` sets `ctx["fields_extracted"]` and `ctx["missing_fields"]` | — | — | No action needed |
| Persist: result type | P1 | Already covered | `runner.py:104,110` sets `ctx["outcome"]` to "skipped" / "created" | — | — | No action needed |

---

## C. First-pass Instrumentation Plan

### Items most worth addressing first (in priority order)

**1. Add Run started event + fix Run finished event**

- Impact: this is the topmost layer of the entire observability skeleton. Without a reliable run started / run finished pair, there is no way to tell whether a run is executing, whether it crashed midway, or whether executions are overlapping. Currently, run finished is not emitted on exception, meaning crashes are silent.
- Effort: small. Run started is one line of log; Run finished is moving an existing log into `finally` and adding a few fields.
- Location: `run_pipeline()` in `runner.py`.

**2. Add `log_stage()` wrapping for the dedupe stage**

- Impact: dedupe is the only stage in the ingestion main flow without a unified stage event and duration metric. If the dedupe DB query slows down or fails, there is currently no metric to reflect it.
- Effort: medium. Need to consider how `continue` control flow interacts with the `log_stage()` context manager. Dedupe is per-item — one `log_stage("dedupe")` per URL, with outcome "new" or "skip."
- Location: inside the for loop in `runner.py`, around the `News.objects.filter(...).exists()` section.

**3. Add `log_stage()` wrapping for the cache invalidate stage**

- Impact: cache invalidate failures are currently not tracked by `STAGE_ERRORS`. Although cache invalidate is a P2 downstream signal in Step 4, it already has a code path — adding the wrapping is very cheap.
- Effort: small. A single `with log_stage("cache_invalidate"):` wrapping `cache.clear()` is sufficient.
- Location: the `if result.created > 0:` block in `runner.py`.

**4. Fix notify error visibility**

- Impact: notify failures are currently invisible to `log_stage()` and the `STAGE_ERRORS` metric. If notify silently fails all day, you can only discover it by digging through the `notify.failed` log — the metric dashboard will show nothing.
- Effort: small to medium. The core issue is that `notify.py` swallows the exception. The fix requires deciding: let `notify()` re-raise and handle in the runner, or switch to a return value.
- Location: exception handling in `notify.py` + the notify call site in `runner.py`.

### What can be deferred

- **P1 quality enrichment signals**: discover url_count, fetch response size, parse field completeness, persist result type — **all four are already covered**, no additional action needed.
- **P2 downstream visibility — Notify outcome and Cache invalidation outcome as independent events** (the P2 signals in the Step 4 design): defer. For now, just ensure they have basic coverage inside the `log_stage()` framework.
- **Celery task layer instrumentation**: `tasks.py` already has `celery.scrape_started` / `celery.scrape_finished` logs, but these are outside `run_pipeline()`. Once `run_pipeline()` adds run started/finished, there will be two layers of logs. This redundancy is temporarily acceptable; integration is for a later phase.

### Easiest things to over-build — avoid these

1. **Do not create an independent metric for dedupe**. The dedupe skip count is already covered by `ARTICLES_TOTAL`'s `outcome="skip"` label. Adding `log_stage()` is for stage events and duration, not a reason to add a new counter.

2. **Do not turn notify into synchronous, blocking error propagation**. The current design of "notify failure does not affect pipeline completion" is correct behavior. The goal of the fix is to make failure **visible**, not to have failure block the pipeline.

3. **Do not layer new abstractions on top of `log_stage()`**. The existing `log_stage()` context manager is already clean and concise, handling structured log + duration metric + error metric simultaneously. There is no need to invent new wrappers / decorators / middleware to fill Step 5's coverage gaps.

4. **Do not split run started / run finished into independent event emitter modules**. Use `logger.info()` directly in `run_pipeline()`, consistent with the existing log style.
