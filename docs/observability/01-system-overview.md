# Step 1 — Understand What the System Does

## Core Workflow

The system's core job is: **a scheduled trigger fires a scraping job, which fetches the UDN spotlight news page, retrieves each article, parses it into structured data, writes it to the database, and if any new articles are created, notifies the frontend and invalidates the list cache.**

This pipeline is the primary chain we will be observing.

## Pipeline Stages

A single pipeline run passes through the following stages in order:

### 1. Trigger

Celery Beat sends a task every hour; the Worker receives it and calls `run_pipeline(source)`.
The pipeline can also be triggered manually via `manage.py scrape_news` (same code path, just bypassing Celery).

### 2. Discover

Fetches the UDN NBA homepage, parses the `#focus` carousel section, and collects a list of article URLs.
This is the only step in the entire run that performs a "batch fetch of the work list."

### 3. Dedupe

Checks the DB for each URL (`News.objects.filter(source_url=url).exists()`); if it already exists, skip it.
This is pipeline-level deduplication; the persist stage has a DB unique constraint as a second line of defense.

### 4. Fetch

HTTP GET on each individual article page, returning the full HTML.
Synchronous, processed one at a time, with a polite delay between fetches.

### 5. Parse

Uses BeautifulSoup to extract structured data from the HTML (title, author, content, hero_image_url).
Sources: JSON-LD `NewsArticle` schema, meta tags, and `#story_body_content`.

### 6. Persist

Writes `ArticleData` to PostgreSQL.
If an `IntegrityError` occurs (duplicate `source_url`), it is treated as a duplicate and returns `None` rather than raising.

### 7. Notify

Only executes when persist actually creates a new article.
Sends a new article summary to all connected frontends via Django Channels `group_send`.

### 8. Cache Invalidate

After the URL loop completes, if any new articles were created, clears the Django cache.
This immediately invalidates the `@cache_page` cache on the API list endpoint.

## System Context

The pipeline does not operate in isolation — it depends on several surrounding services:

- **Celery Beat + Worker**: responsible for scheduling and executing the pipeline; broker is Redis.
- **PostgreSQL**: the data source for persist and dedupe.
- **Redis**: simultaneously serves as Celery broker, Django cache, and Channels layer.
- **API (DRF)**: the downstream consumer; lets the frontend read news data written by the pipeline.
- **WebSocket (Channels)**: the downstream consumer; receives real-time pushes from the notify stage.
