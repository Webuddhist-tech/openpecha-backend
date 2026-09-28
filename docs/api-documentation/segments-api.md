# Segments API Documentation

This document provides comprehensive documentation for all Segments-related endpoints in the OpenPecha API v2.

---

## Table of Contents

1. [Overview](#overview)
2. [Authentication](#authentication)
3. [Segment Endpoints](#segment-endpoints)
   - [Get Segment](#get-segment)
   - [Get Segment Content](#get-segment-content)
   - [Find Related Segments](#find-related-segments)
   - [Search Segments](#search-segments)
   - [Tag and Untag Segment](#tag-and-untag-segment)
---

## Overview

Segments are portions of edition content defined by character spans (one or more ranges). They are created as part of segmentations and enable fine-grained text operations, alignment between texts, and targeted content retrieval.

### Key Concepts

- **Segment**: A logical unit of text defined by one or more character spans
- **Segment Type**: A constrained string describing the segment's role: `paragraph`, `verse`, `title`, `back_matter`, `front_matter`, or `top_segment`
- **Lines**: Character spans that define segment boundaries (can be non-contiguous)
- **Segmentation**: Collection of segments that divide an edition's content
- **Alignment**: Direct `ALIGNED_TO` relationship between existing segments
- **Related Segments**: Segments that are aligned together across editions

### Segment Creation

Segments are not created directly. They are created as part of:
1. **Edition segmentation** via `POST /v2/editions/{edition_id}/segmentation`
2. **Edition creation** with inline annotations via `POST /v2/texts/{text_id}/editions`

Text-pair alignment endpoints link existing segments; they do not create new segments.

### Base URL

```
Development: https://api-l25bgmwqoa-uc.a.run.app
Production: https://api-aq25662yyq-uc.a.run.app
Test: https://api-kwgjscy6gq-uc.a.run.app
Local: http://127.0.0.1:5001/pecha-backend-test-3a4d0/us-central1/api
```

---

## Authentication

All API requests require authentication using an API key.

**Header:**
```
X-API-Key: your_api_key_here
```

`X-Application` is optional on segment, segment content, and related-segment reads. When supplied, tag IDs are filtered to the requested application.

---

## Segment Endpoints

### Get Segment

Retrieve a segment with its segmentation, edition, text, line spans, and optional tag context.

**Endpoint:**
```
GET /v2/segments/{segment_id}
```

**Parameters:**

| Name | Type | Location | Required | Description |
|------|------|----------|----------|-------------|
| `segment_id` | string | path | Yes | The ID of the segment |

**Response: 200 OK**

```json
{
  "id": "SEG001",
  "segmentation_id": "SGN12345678",
  "edition_id": "ED12345678",
  "text_id": "TXT12345678",
  "type": "paragraph",
  "lines": [
    {"start": 0, "end": 100}
  ],
  "tag_ids": ["TAG123"]
}
```

`type` is always present and defaults to `"paragraph"` for segments created without an explicit type. `tag_ids` is omitted when the segment has no tags. If `X-Application` is supplied, returned tag IDs are filtered to tags belonging to that application.

**Error Responses:**
- `401 Unauthorized`: Missing or invalid API key in deployed environments
- `404 Not Found`: Segment does not exist

**Example Usage:**

```bash
curl -X GET "https://api-l25bgmwqoa-uc.a.run.app/v2/segments/SEG001" \
  -H "X-API-Key: your_api_key"
```

---

### Get Segment Content

Retrieve the base text content for a segment based on its character span(s).

**Endpoint:**
```
GET /v2/segments/{segment_id}/content
```

**Parameters:**

| Name | Type | Location | Required | Description |
|------|------|----------|----------|-------------|
| `segment_id` | string | path | Yes | The ID of the segment |

**Response: 200 OK**

```json
"This is the text content of the segment."
```

**Response Type:** Plain text string (JSON-encoded)

The response contains the actual text content extracted from the edition based on the segment's span(s).

**Error Responses:**
- `401 Unauthorized`: Missing or invalid API key in deployed environments
- `404 Not Found`: Segment does not exist
- `500 Server Error`: Internal server error

**Example Usage:**

```bash
curl -X GET "https://api-l25bgmwqoa-uc.a.run.app/v2/segments/SEG001/content" \
  -H "X-API-Key: your_api_key"
```

**Use Cases:**
- Display segment text in UI
- Export segment content for analysis
- Retrieve aligned text portions
- Build parallel text views

---

### Find Related Segments

Find all segments that are directly or transitively aligned to a specific segment. Returns segments connected through direct `ALIGNED_TO` relationships.

**Endpoint:**
```
GET /v2/segments/{segment_id}/related
```

**Parameters:**

| Name | Type | Location | Required | Default | Description |
|------|------|----------|----------|---------|-------------|
| `segment_id` | string | path | Yes | - | The ID of the segment to find related segments for |
| `limit` | integer | query | No | 20 | Number of related segments to return (1-100) |
| `offset` | integer | query | No | 0 | Number of related segments to skip |
| `text_id` | string | query | No | - | Filter related segments to one text |
| `edition_id` | string | query | No | - | Filter related segments to one edition |
| `language` | string | query | No | - | Filter related segments by text language code |

**Response: 200 OK**

```json
{
  "items": [
    {
      "id": "SEG001",
      "segmentation_id": "SGN12345678",
      "edition_id": "M12345678",
      "text_id": "E12345678",
      "type": "paragraph",
      "lines": [{"start": 0, "end": 100}],
      "tag_ids": ["TAG123"]
    }
  ],
  "has_more": false,
  "offset": 0,
  "limit": 20
}
```

**Response Structure:**
- Returns a paginated object with flat segment objects in `items`
- Each segment includes `segmentation_id`, `edition_id`, `text_id`, and `type`
- Optional filters are applied to related display results before pagination; combined filters are conjunctive
- Empty result uses `"items": []`

**Error Responses:**
- `401 Unauthorized`: Missing or invalid API key in deployed environments
- `422 Validation Error`: Invalid `limit` or `offset`
- `500 Server Error`: Internal server error

If the segment ID does not exist, this endpoint returns an empty paginated response instead of `404`.

**Example Usage:**

```bash
curl -X GET "https://api-l25bgmwqoa-uc.a.run.app/v2/segments/SEG001/related" \
  -H "X-API-Key: your_api_key"
```

```bash
curl -X GET "https://api-l25bgmwqoa-uc.a.run.app/v2/segments/SEG001/related?text_id=TXT456&language=en" \
  -H "X-API-Key: your_api_key"
```

**Use Cases:**
- Find translation segments for source text segment
- Navigate between aligned editions
- Display parallel text views
- Build cross-edition references

---

### Search Segments

Search segments by forwarding request to external search API and enriching results with overlapping segmentation annotation segment IDs.

**Endpoint:**
```
GET /v2/segments/search
```

**Parameters:**

| Name | Type | Location | Required | Default | Description |
|------|------|----------|----------|---------|-------------|
| `query` | string | query | Yes | - | The search query text |
| `search_type` | string | query | No | "semantic" | Type of search forwarded to the search service. Common values are `hybrid`, `bm25`, `semantic`, or `exact`. |
| `limit` | integer | query | No | 10 | Maximum number of results (1-100) |
| `title` | string | query | No | - | Filter results by title |
| `return_text` | boolean | query | No | true | Whether to include text content in results |

**Search Types:**

| Type | Description | Best For |
|------|-------------|----------|
| `hybrid` | Combines BM25 and semantic search | General purpose, balanced results |
| `bm25` | Keyword-based ranking (BM25 algorithm) | Exact term matching, keyword search |
| `semantic` | Vector similarity search | Meaning-based search, conceptual queries |
| `exact` | Exact text matching | Precise phrase matching |

**Response: 200 OK**

```json
{
  "query": "བོད་ཀྱི་རིག་གནས།",
  "results": [
    {
      "id": "SEG_SEARCH_001",
      "distance": 0.85,
      "entity": {
        "text": "Sample text content from the segment"
      },
      "segmentation_ids": [
        "SEG_001",
        "SEG_002",
        "SEG_003"
      ]
    },
    {
      "id": "SEG_SEARCH_002",
      "distance": 0.78,
      "entity": {
        "text": "Another matching text segment"
      },
      "segmentation_ids": [
        "SEG_004",
        "SEG_005"
      ]
    }
  ],
  "count": 2
}
```

**Response Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `query` | string | The search query that was used |
| `results` | array | List of search results with enriched data |
| `results[].id` | string | Search segmentation segment ID |
| `results[].distance` | number | Search relevance score/distance |
| `results[].entity` | object | Additional entity data (includes `text` if return_text=true) |
| `results[].segmentation_ids` | array | Overlapping segmentation annotation segment IDs |
| `count` | integer | Number of results returned |

**Key Feature - Segmentation Mapping:**

The search endpoint enriches external search results with local segmentation IDs. For each search result:
1. The search API returns a segment with its span
2. The endpoint finds all segmentation annotation segments that overlap with that span
3. Returns both the search result and the overlapping segmentation IDs

This enables:
- Mapping search results to your annotation segments
- Finding related segments via alignment
- Integrating external search with local segmentation

**Error Responses:**
- `400 Bad Request`: Invalid query parameters
- `422 Validation Error`: Validation failed (e.g., invalid search_type, limit out of range)
- `500 Server Error`: Internal server error

**Example Usage:**

```bash
# Basic search with default settings
curl -X GET "https://api-l25bgmwqoa-uc.a.run.app/v2/segments/search?query=བོད་ཀྱི་རིག་གནས།" \
  -H "X-API-Key: your_api_key"

# Hybrid search with custom limit
curl -X GET "https://api-l25bgmwqoa-uc.a.run.app/v2/segments/search?query=Heart%20Sutra&search_type=hybrid&limit=20" \
  -H "X-API-Key: your_api_key"

# BM25 keyword search
curl -X GET "https://api-l25bgmwqoa-uc.a.run.app/v2/segments/search?query=prajnaparamita&search_type=bm25" \
  -H "X-API-Key: your_api_key"

# Semantic search
curl -X GET "https://api-l25bgmwqoa-uc.a.run.app/v2/segments/search?query=emptiness%20teaching&search_type=semantic" \
  -H "X-API-Key: your_api_key"

# Exact phrase search
curl -X GET "https://api-l25bgmwqoa-uc.a.run.app/v2/segments/search?query=སྟོང་པ་ཉིད་&search_type=exact" \
  -H "X-API-Key: your_api_key"

# Search with title filter
curl -X GET "https://api-l25bgmwqoa-uc.a.run.app/v2/segments/search?query=wisdom&title=Heart%20Sutra" \
  -H "X-API-Key: your_api_key"

# Search without text content (faster)
curl -X GET "https://api-l25bgmwqoa-uc.a.run.app/v2/segments/search?query=meditation&return_text=false" \
  -H "X-API-Key: your_api_key"
```

---

### Tag and Untag Segment

Attach or remove an application tag from a segment.

**Endpoints:**

```
POST /v2/segments/{segment_id}/tags/{tag_id}
DELETE /v2/segments/{segment_id}/tags/{tag_id}
```

**Response: 204 No Content**

```bash
curl -X POST "https://api-l25bgmwqoa-uc.a.run.app/v2/segments/SEG001/tags/TAG123" \
  -H "X-API-Key: your_api_key"

curl -X DELETE "https://api-l25bgmwqoa-uc.a.run.app/v2/segments/SEG001/tags/TAG123" \
  -H "X-API-Key: your_api_key"
```

**Developer Notes:**
- Implemented in `routers/segments.py`.
- Segment response models live in `models/annotation.py`.
- Search response models live in `models/search.py`.
- The search endpoint forwards to `settings.search_api_url` and enriches results by looking up local overlapping segmentation IDs.
