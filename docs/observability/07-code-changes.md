# Step 7 — Observability v1 Code Change Plan

## A. Short Implementation Summary

### What this patch set implements

Four small patches that close every P0 signal gap identified in Step 5 and planned in Step 6:

1. Run lifecycle events — a reliable `pipeline.started` / `pipeline.finished` pair that fires on every code path (normal, early return, crash).
2. Dedupe stage wrapping — `log_stage("dedupe")` for the last ingestion stage missing structured events and duration metric.
3. Cache invalidate stage wrapping — `log_stage("cache_invalidate")` for the only run-level stage missing structured events.
4. Notify error visibility — let `notify()` exceptions propagate to `log_stage("notify")` so failures appear in `stage.failed` events and `STAGE_ERRORS` metric.

### What is intentionally left out

- No new metrics or metric renames (`instrument.py` untouched).
- No `PipelineResult` changes (`types.py` untouched).
- No Celery task layer changes (`tasks.py` untouched).
- No P1/P2 signals work (all P1 already covered, P2 out of scope).
- No dashboard, alert, or threshold design.

### Recommended review strategy

Review and apply patches **in order** (1 → 2 → 3 → 4). Each patch can be tested independently after applying, except Patch 4 which touches two files atomically. After each patch, run `python manage.py test news.tests.test_scraper` to confirm no regressions.

---

## B. Patch Plan

| Patch | Purpose | Files touched | Why separated |
|-------|---------|---------------|---------------|
| 1 | Run started + Run finished events | `runner.py` | Establishes top-level observability pair; all other patches benefit from a reliable pipeline.finished |
| 2 | Dedupe `log_stage` wrapping | `runner.py` | Isolated to dedupe block in the for loop; independent of Patch 1 structurally but reviewed after because pipeline.finished now correctly counts dedupe failures |
| 3 | Cache invalidate `log_stage` wrapping | `runner.py` | Isolated to cache block after the for loop; smallest patch, no dependencies on 2 |
| 4 | Notify error visibility | `runner.py` + `notify.py` | Two-file atomic change; placed last because it's the only cross-file patch and requires Patch 1's try/except structure in runner.py |

---

## C. Per-patch Implementation Instructions

### Patch 1 — Run started + Run finished events

**Target file:** `news/pipeline/runner.py`

**Target function:** `run_pipeline()`

**What to change — 4 modifications in order of location:**

#### 1a. Add `pipeline.started` event

Location: after `structlog.contextvars.bind_contextvars(...)` (current line 27), before `result = PipelineResult()`.

Add a single `logger.info("pipeline.started")` call. The `run_id` and `source` fields are already bound via contextvars and will appear automatically in the log event.

#### 1b. Add tracking variables

Location: after `run_start = time.monotonic()` (current line 30), before the `try:`.

Add two variables:
- `input_count = 0` — will be set to `len(urls)` after discover succeeds
- `run_error = None` — will be set if an unhandled exception escapes the try block

#### 1c. Set `input_count` after discover

Location: inside the try block, immediately after the `log_stage("discover")` block ends (after current line 38), before the `if not urls:` check.

Add `input_count = len(urls)`. This must be outside the `log_stage("discover")` context manager but inside the try block, so that `input_count` is only set when discover succeeds.

#### 1d. Restructure the try/except/finally block and move `pipeline.finished`

This is the main structural change. The current structure is:

```
try:
    ... pipeline body ...
finally:
    RUN_DURATION.observe(...)
    unbind_contextvars(...)

logger.info("pipeline.finished", created=..., skipped=..., failed=...)
return result
```

Change to:

```
try:
    ... pipeline body ... (unchanged)
except Exception as exc:
    run_error = exc
    raise
finally:
    duration = time.monotonic() - run_start
    RUN_DURATION.labels(source=source.name).observe(duration)

    if run_error is not None:
        completion_status = "error"
    elif result.failed > 0:
        completion_status = "partial"
    else:
        completion_status = "success"

    logger.info(
        "pipeline.finished",
        completion_status=completion_status,
        duration=round(duration, 3),
        input_count=input_count,
        created=result.created,
        skipped=result.skipped,
        failed=result.failed,
    )

    structlog.contextvars.unbind_contextvars("run_id", "source")

return result
```

Key points:
- `except Exception as exc:` captures the error for status derivation, then re-raises so the caller still sees the exception.
- `pipeline.finished` is emitted **before** `unbind_contextvars`, so `run_id` and `source` are still in context.
- `duration` is computed once and shared between `RUN_DURATION.observe()` and the log event.
- `completion_status` uses a simple three-value derivation: `"error"` if an exception escaped, `"partial"` if any items failed, `"success"` otherwise.
- The `return result` at the very bottom only executes on the non-exception path (same as before).

**What existing structure is reused:**
- `logger.info()` with structlog contextvars (same pattern as all other logs)
- `RUN_DURATION` metric (same metric, just shared duration variable)

**What should NOT be changed in this patch:**
- The pipeline body inside the try block (for loop, all stage wrappers) — untouched.
- `PipelineResult` — untouched.
- `instrument.py` — untouched.
- The existing `logger.warning("pipeline.empty")` — keep as-is. It provides warning-level visibility that `pipeline.finished` (info-level) doesn't duplicate.

---

### Patch 2 — Dedupe `log_stage` wrapping

**Target file:** `news/pipeline/runner.py`

**Target function:** `run_pipeline()`, inside the `for url in urls:` loop

**What to change:**

Replace the current inline dedupe block (current lines 46–51):

```python
            if News.objects.filter(source_url=url).exists():
                logger.info("pipeline.skip", url=url, reason="duplicate")
                result.skipped += 1
                ARTICLES_TOTAL.labels(source=source.name, outcome="skip").inc()
                continue
```

With a `log_stage`-wrapped version following the same try/except pattern as fetch, parse, and persist:

```python
            # --- dedupe ---
            try:
                with log_stage("dedupe", source=source.name, url=url) as ctx:
                    is_dup = News.objects.filter(source_url=url).exists()
                    ctx["outcome"] = "skip" if is_dup else "new"
            except Exception:
                result.failed += 1
                ARTICLES_TOTAL.labels(source=source.name, outcome="fail").inc()
                if delay:
                    time.sleep(delay)
                continue

            if is_dup:
                result.skipped += 1
                ARTICLES_TOTAL.labels(source=source.name, outcome="skip").inc()
                continue
```

Key points:
- `log_stage("dedupe")` provides `stage.completed` / `stage.failed` events, `STAGE_DURATION` observation, and `STAGE_ERRORS` tracking — all automatically via the existing `log_stage()` context manager.
- The `ctx["outcome"]` field records whether each URL was "new" or "skip" in the structured event.
- The outer try/except follows the identical pattern as fetch/parse/persist: on exception, count as failed, continue to next URL. This is a **behavior change** from the current code where a DB error would crash the entire for loop. The new behavior is more resilient and consistent.
- `ARTICLES_TOTAL` skip/fail increments stay **outside** the `log_stage` block, because these are run-level counters, not stage event fields.
- The old `logger.info("pipeline.skip")` is removed — its information is now in the `stage.completed` event with `outcome="skip"`.

**What existing structure is reused:**
- `log_stage()` context manager (identical to fetch/parse/persist usage)
- try/except + `result.failed += 1` + `ARTICLES_TOTAL.fail` + `continue` pattern (identical to fetch/parse/persist)

**What should NOT be changed in this patch:**
- The `ARTICLES_TOTAL` increment logic (same labels, same positions).
- The fetch/parse/persist/notify blocks — untouched.
- The cache invalidate block — untouched (that's Patch 3).

---

### Patch 3 — Cache invalidate `log_stage` wrapping

**Target file:** `news/pipeline/runner.py`

**Target function:** `run_pipeline()`, the `if result.created > 0:` block after the for loop

**What to change:**

Replace the current cache invalidation block (current lines 131–135):

```python
        if result.created > 0:
            cache.clear()
            logger.info(
                "pipeline.cache_cleared", articles_created=result.created
            )
```

With a `log_stage`-wrapped version:

```python
        if result.created > 0:
            try:
                with log_stage("cache_invalidate", source=source.name) as ctx:
                    cache.clear()
                    ctx["articles_created"] = result.created
            except Exception:
                pass
```

Key points:
- `log_stage("cache_invalidate")` provides `stage.completed` / `stage.failed` events and `STAGE_DURATION` observation.
- This is a **run-level** stage (one per run, not per URL), unlike dedupe/fetch/parse/persist.
- The outer `try: ... except Exception: pass` prevents cache invalidation failures from crashing the run. `log_stage` has already recorded the failure in `stage.failed` event and `STAGE_ERRORS` metric before re-raising.
- The old `logger.info("pipeline.cache_cleared")` is removed — its information is now in `stage.completed` with `articles_created` in ctx.

**What existing structure is reused:**
- `log_stage()` context manager

**What should NOT be changed in this patch:**
- The `if result.created > 0:` condition — same logic.
- The for loop body — untouched.
- `notify.py` — untouched (that's Patch 4).

---

### Patch 4 — Notify error visibility

**Target files:** `news/pipeline/notify.py` + `news/pipeline/runner.py`

**These two changes MUST be applied together** (atomic). If only `notify.py` is changed, `notify()` exceptions will crash the pipeline.

#### 4a. `notify.py` — remove internal try/except

Replace the current `notify()` function body:

```python
def notify(news_obj: News) -> None:
    """Push a WebSocket notification for a newly created article."""
    try:
        channel_layer = get_channel_layer()
        if channel_layer is None:
            logger.warning("notify.no_channel_layer", article_id=news_obj.id)
            return
        async_to_sync(channel_layer.group_send)(
            GROUP_NAME,
            {
                "type": "new_article",
                "article": {
                    "id": news_obj.id,
                    "title": news_obj.title,
                    "author": news_obj.author,
                    "published_at": news_obj.published_at.isoformat(),
                    "hero_image_url": news_obj.hero_image_url,
                },
            },
        )
    except Exception:
        logger.exception(
            "notify.failed", article_id=news_obj.id, title=news_obj.title
        )
```

With:

```python
def notify(news_obj: News) -> None:
    """Push a WebSocket notification for a newly created article."""
    channel_layer = get_channel_layer()
    if channel_layer is None:
        raise RuntimeError("No channel layer configured")
    async_to_sync(channel_layer.group_send)(
        GROUP_NAME,
        {
            "type": "new_article",
            "article": {
                "id": news_obj.id,
                "title": news_obj.title,
                "author": news_obj.author,
                "published_at": news_obj.published_at.isoformat(),
                "hero_image_url": news_obj.hero_image_url,
            },
        },
    )
```

Changes:
- Remove the outer try/except. Exceptions from `group_send` now propagate to the caller.
- The `channel_layer is None` case changes from a warning-and-return to a `raise RuntimeError`. This makes the failure **visible** to `log_stage`: it will appear as `stage.failed` with `error_type="RuntimeError"` instead of being silently swallowed as `stage.completed`.
- The `logger.exception("notify.failed")` line is removed — `log_stage` in `runner.py` will now handle failure logging via `stage.failed` event.
- The `structlog` and `logger` imports can be removed from this file since they're no longer used.

#### 4b. `runner.py` — add try/except around notify `log_stage`

Replace the current notify block (current lines 122–126):

```python
            # --- notify ---
            if news_obj is not None:
                with log_stage("notify", source=source.name, article_id=news_obj.id) as ctx:
                    notify(news_obj)
                    ctx["delivered"] = True
```

With:

```python
            # --- notify ---
            if news_obj is not None:
                try:
                    with log_stage("notify", source=source.name, article_id=news_obj.id) as ctx:
                        notify(news_obj)
                        ctx["delivered"] = True
                except Exception:
                    pass
```

The outer `try: ... except Exception: pass` catches the re-raised exception from `log_stage`. By this point, `log_stage` has already:
- Emitted `stage.failed` structured event with `error_type`, `error`, `duration_ms`
- Incremented `STAGE_ERRORS` counter

The `pass` ensures notify failure doesn't affect the pipeline's `PipelineResult` or `completion_status`. This preserves the original design intent: "notify failure doesn't crash the pipeline."

**What existing structure is reused:**
- `log_stage("notify")` — already exists, just needs failures to reach it

**What should NOT be changed in this patch:**
- The `if news_obj is not None:` condition — same logic.
- The `ctx["delivered"] = True` — only set on success path (inside the `with` block, after `notify()` returns without raising).
- `PipelineResult` counting — notify failures are intentionally not counted in `result.failed`.

---

## D. Expected Behavior After Each Patch

### After Patch 1 (Run lifecycle)

| What to verify | How |
|----------------|-----|
| `pipeline.started` appears on every run | Run `manage.py scrape_news`, grep log for `pipeline.started` — must have `run_id` and `source` |
| `pipeline.finished` appears on every run (including crash) | 1) Normal run → `completion_status="success"` or `"partial"` 2) Disconnect network then run → discover fails, `completion_status="error"`, `input_count=0` 3) All URLs are dupes → `completion_status="success"`, `input_count=N`, `created=0` |
| `pipeline.finished` has all required fields | Check for: `completion_status`, `duration`, `input_count`, `created`, `skipped`, `failed` |
| Early return (empty URLs) still emits `pipeline.finished` | Mock discover to return `[]` → `pipeline.finished` appears with `input_count=0`, `completion_status="success"` |
| Existing tests pass | `python manage.py test news.tests.test_scraper` — all 8 tests green |

### After Patch 2 (Dedupe log_stage)

| What to verify | How |
|----------------|-----|
| `stage.completed` with `stage="dedupe"` per URL | Run pipeline with mix of new/existing URLs → one `stage.completed` event per URL, each with `outcome="skip"` or `"new"` and `duration_ms` |
| `STAGE_DURATION` has dedupe observations | Check Prometheus metrics endpoint for `scraper_stage_duration_seconds{stage="dedupe"}` |
| Dedupe DB failure is resilient | Mock `News.objects.filter` to raise → that URL counted as failed, pipeline continues to next URL |
| Old `pipeline.skip` log no longer emitted | Grep log — `pipeline.skip` should not appear; replaced by `stage.completed` with `stage="dedupe"` and `outcome="skip"` |
| Existing tests pass | All 8 tests green |

### After Patch 3 (Cache invalidate log_stage)

| What to verify | How |
|----------------|-----|
| `stage.completed` with `stage="cache_invalidate"` | Run pipeline that creates articles → `stage.completed` event with `articles_created` field |
| No `stage.completed` for cache_invalidate when nothing created | Run pipeline where all URLs are dupes → no `cache_invalidate` stage event |
| `cache.clear()` failure is resilient | Mock `cache.clear` to raise → `stage.failed` event appears, but `pipeline.finished` still has `completion_status="success"` (or `"partial"` based on item results) |
| Old `pipeline.cache_cleared` log no longer emitted | Grep log — replaced by `stage.completed` event |
| Existing tests pass | All 8 tests green |

### After Patch 4 (Notify error visibility)

| What to verify | How |
|----------------|-----|
| Notify failure appears in `stage.failed` event | Mock `get_channel_layer` to return `None` → `stage.failed` with `error_type="RuntimeError"` |
| Notify failure appears in `STAGE_ERRORS` metric | Check `scraper_stage_errors_total{stage="notify"}` counter after a notify failure |
| Notify failure does NOT crash pipeline | After notify fails, pipeline continues; `pipeline.finished` appears with `completion_status` NOT "error" (unless other stages also failed) |
| Notify failure does NOT affect `PipelineResult` | `result.failed` does not increment from notify failure |
| Notify success still logs `stage.completed` with `delivered=True` | Run pipeline with working channel layer → `stage.completed` event for `stage="notify"` |
| Existing tests pass | All 8 tests green (tests mock `notify` so the try/except change is transparent) |

---

## E. Risks / Review Checklist

### Signal integrity

- [x] **No duplicated signal emission**: After Patch 1, `pipeline.finished` is emitted exactly once per run (in `finally`), not twice. Verify the old `logger.info("pipeline.finished")` outside the try block is removed.
- [x] **Run-level vs item-level not mixed**: `pipeline.started/finished` are run-level. `stage.completed` for dedupe/fetch/parse/persist/notify are item-level. `stage.completed` for discover/cache_invalidate are run-level. Verify no stage event accidentally emits at the wrong granularity.
- [x] **`completion_status` derivation is correct**: "error" only when an unhandled exception escaped; "partial" when items failed but run completed; "success" otherwise. An early return (empty URLs) should be "success", not "error".

### Correlation fields

- [x] **`run_id` present in all events**: `pipeline.started`, `pipeline.finished`, and all `stage.completed`/`stage.failed` events must carry `run_id` via structlog contextvars. Verify `unbind_contextvars` happens **after** `pipeline.finished` in the `finally` block.
- [x] **`source` present in all events**: Same as above — bound via contextvars.

### Control flow preservation

- [x] **Notify failure doesn't crash pipeline**: After Patch 4, `notify()` can raise, but the outer try/except in `runner.py` catches it. Test with a broken channel layer.
- [x] **Cache invalidate failure doesn't crash pipeline**: After Patch 3, `cache.clear()` failure is caught. Test with a broken cache backend.
- [x] **Dedupe failure doesn't crash the entire for loop**: After Patch 2, a DB error on one URL skips to the next URL instead of aborting the loop. This is a **behavior change** from the current code — verify it's acceptable.
- [x] **Early return (empty URLs) still works**: The `return result` inside the try block on the empty-URLs path still triggers `finally`, which now emits `pipeline.finished`. Verify the function still returns the correct `PipelineResult`.

### Metric hygiene

- [x] **No new metrics created**: `instrument.py` is untouched. All four existing metrics (`ARTICLES_TOTAL`, `STAGE_DURATION`, `STAGE_ERRORS`, `RUN_DURATION`) are reused as-is.
- [x] **No new labels added**: Dedupe uses `stage="dedupe"`, cache invalidate uses `stage="cache_invalidate"` — these are new label **values**, not new label **keys**. No dimension explosion.
- [x] **`ARTICLES_TOTAL` semantics unchanged**: skip/fail/create/discover outcomes are incremented at the same logical points as before.

### Atomicity

- [x] **Patch 4 is atomic**: `notify.py` removing try/except and `runner.py` adding try/except MUST be applied together. Applying only one side creates a regression (notify failure crashes pipeline).

### Test regression

- [x] **All 8 existing tests pass after each patch**: `RunPipelineTest` mocks `notify` at the import path `news.pipeline.runner.notify`, which remains unchanged. The `test_skips_duplicate_urls` test creates a pre-existing article then runs pipeline — after Patch 2, dedupe is wrapped in `log_stage` but the skip logic is identical.
