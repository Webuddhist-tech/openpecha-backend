# OpenPecha API v2

This folder documents the public FastAPI routes exposed by the backend. All endpoint paths below are relative to the API host.

## Base URLs

```text
Development: https://api-l25bgmwqoa-uc.a.run.app
Production: https://api-aq25662yyq-uc.a.run.app
Test: https://api-kwgjscy6gq-uc.a.run.app
Local Firebase emulator: http://127.0.0.1:5001/pecha-backend-test-3a4d0/us-central1/api
Local FastAPI app: http://127.0.0.1:8000
```

## Authentication

Most routes require `X-API-Key`. In local test/dev mode the dependency accepts requests without a real key, but deployed environments validate the header.

Application-scoped routes also require or accept `X-Application`:

- Required for `categories` and `tags`.
- Optional for `texts` and `segments`; when present, application-owned tags are filtered to that application.
- App-bound API keys must use the same `X-Application` value as the key's bound application.

Common errors:

- `401` for missing or invalid API keys in deployed environments.
- `404` when a requested resource or application does not exist.
- `409` for conflicts such as duplicate unique identifiers.
- `422` for Pydantic validation errors, missing required headers, invalid ranges, null values in PATCH requests, extra fields, or business validation errors.

## Common Data Shapes

Localized strings are objects keyed by language code:

```json
{
  "en": "Heart Sutra",
  "bo": "ཤེས་རབ་སྙིང་པོ།"
}
```

Strings are stored exactly as submitted and are never trimmed. Every string field must contain at least one non-whitespace character, so `""` and `"   "` are both rejected with `422`. A value sent with surrounding whitespace is stored with it, so `"W22084 "` will not match a later lookup for `"W22084"`; callers should send values already normalized. The one exception is the `text` of a content patch, where a whitespace-only payload such as a single space is a legitimate edit.

Character spans use half-open ranges: `start` is inclusive and `end` is exclusive. A segment contains one or more continuous `lines`; multiple lines inside one segment must be sorted and adjacent.

Paginated list endpoints return:

```json
{
  "items": [],
  "has_more": false,
  "offset": 0,
  "limit": 20
}
```

## Active Route Inventory

Use `GET /docs`
