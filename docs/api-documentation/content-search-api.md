# Content Search API Documentation

Content search finds where a query appears in stored edition content and returns the text, edition, and segment locations.

The base text remains canonical in S3. OpenSearch stores derived, fixed-size overlapping chunks with segment span metadata.

## Authentication

Use `X-API-Key` in deployed environments.

```text
X-API-Key: your_api_key
```

## Search Content

```http
GET /v2/content-search
```

Query parameters:

| Query | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `query` | string | Yes | - | Search string |
| `search_type` | `exact` or `similar` | No | `exact` | Exact substring search or OpenSearch-ranked similar search |
| `limit` | integer | No | `10` | Maximum results, 1-100 |
| `text_id` | string | No | - | Filter to one text |
| `edition_id` | string | No | - | Filter to one edition |

Exact search uses the analyzed content field to find candidate chunks, then verifies the exact substring and computes `match_span` from the returned chunk text. Similar search uses the same analyzed content field for near-phrase matches and leaves `match_span` as `null` unless a precise match span is available.

`context` is a plain text fragment from the matched chunk. `context_span` is the location of that returned `context` in the full edition text.

`segment_ids` contains all segment IDs covered by the result. For exact search, these are the segments overlapping `match_span`; for similar search, these are the segments covered by `context_span`.

Response:

```json
[
  {
    "text_id": "TXT123",
    "edition_id": "ED123",
    "segment_ids": ["SEG001", "SEG002"],
    "context_span": {"start": 80, "end": 220},
    "match_span": {"start": 132, "end": 151},
    "score": 12.4,
    "context": "..."
  }
]
```

Example:

```bash
curl "https://api-l25bgmwqoa-uc.a.run.app/v2/content-search?query=%E0%BD%96%E0%BD%91%E0%BD%BA%E0%BC%8B%E0%BD%A3%E0%BD%BA%E0%BD%82%E0%BD%A6&search_type=exact" \
  -H "X-API-Key: your_api_key"
```

Error responses:

- `400 Bad Request`: OpenSearch auth mode is invalid.
- `401 Unauthorized`: Missing or invalid API key in deployed environments.
- `422 Unprocessable Entity`: Missing `query`, invalid `search_type`, or invalid `limit`.

## Operations

The content search index is derived data:

- Creating an edition indexes overlapping content chunks in the background.
- Patching edition content reindexes the edition after the storage write succeeds.
- Deleting an edition deletes derived OpenSearch documents for that edition.
- Existing editions can be bulk indexed with `python -m scripts.content_search reindex`.

## Setup

```bash
python -m scripts.content_search setup-index
python -m scripts.content_search reindex
```

When the OpenSearch mapping changes, recreate the derived index before reindexing:

```bash
python -m scripts.content_search recreate-index
python -m scripts.content_search reindex
```

## Developer Notes

Relevant code:

- `routers/content_search.py`
- `content_search/service.py`
- `models/content_search.py`
- `models/requests.py`
- `database/segment_database.py`
- `scripts/content_search.py`
