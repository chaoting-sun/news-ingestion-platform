# TSNA Source — API Discovery Notes

## Goal

Scrape the "近期熱門" (recent popular) posts from https://tsna.com/.

## Discovery Process

### 1. Initial page fetch — client-side rendered

Fetched `https://tsna.com/` directly. The HTML contained only CSS, font declarations, and schema.org metadata — no article content. The site is a **Nuxt.js SPA** that renders content client-side via JavaScript.

### 2. Extracting JS bundle URLs

Parsed the raw HTML for `/_nuxt/*.js` script references and found several bundles:

```
/_nuxt/d93f0ff.js
/_nuxt/3b6b78f.js
/_nuxt/fa88251.js
...
```

### 3. Searching bundles for API paths

Searched each bundle for keywords like `popular`, `hot`, `front/` and found all API route paths in `fa88251.js`:

```
front/hot/keywords
front/news/top
front/news/list
front/news/carousel
front/news
...
```

### 4. Finding the API base URL

Grepped the same bundle for full URLs and found the API base in the Nuxt config:

```
API_URL: "https://webdata-api.tsna.com"
```

### 5. Testing the "近期熱門" endpoint

The `front/news/top` endpoint requires two params (`Newest` and `Random`). Discovered this from the error response:

```
GET https://webdata-api.tsna.com/front/news/top
→ 1299: Field validation for 'Newest' failed on the 'required' tag
```

Working call:

```
GET https://webdata-api.tsna.com/front/news/top?Newest=10&Random=1
```

Returns `Result.Newest[]` — each item has `ID`, `Title`, `Cover`, `Unit`.

### 6. Finding the article detail endpoint

Searched the JS bundle for how the detail page fetches data:

```js
t.get("front/news", { params: { ID: n } })
```

Working call:

```
GET https://webdata-api.tsna.com/front/news?ID=124754
```

Returns `Result.Body` with: `Title`, `Author`, `Content` (HTML), `PublishTime` (ISO 8601 with `Z` suffix), `Cover.Url`, `Cover.Title`, `Hits`, `Keywords`.

### 7. Finding the frontend article URL pattern

Extracted Nuxt route definitions from the JS bundle:

```js
{ path: "/article/:newsId", component: R, name: "article-newsId___zh-TW___default" }
```

So article pages live at `https://tsna.com/article/{ID}`.

## Summary of endpoints

| Purpose          | URL                                                        |
| ---------------- | ---------------------------------------------------------- |
| Popular articles | `GET webdata-api.tsna.com/front/news/top?Newest=N&Random=M` |
| Article detail   | `GET webdata-api.tsna.com/front/news?ID={id}`              |
| Frontend page    | `https://tsna.com/article/{id}`                            |
