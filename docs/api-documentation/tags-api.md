# Tags API Documentation

Tags are application-scoped labels that can be attached to texts and segments. They are useful for cross-cutting collections such as "philosophy", "practice", "featured", or project-specific editorial states.

## Concepts

- Tags belong to one application, selected with the required `X-Application` header on tag CRUD routes.
- Tag titles and descriptions are localized string objects.
- Texts can be created or patched with `tag_ids`, and can also be tagged or untagged through dedicated endpoints.
- Segment tags are attached directly to segment nodes.
- Listing tags only returns tags for the requested application.

## Authentication

Use `X-API-Key` in deployed environments. Tag CRUD routes also require `X-Application`.

```text
X-API-Key: your_api_key
X-Application: webuddhist
```

## List Tags

```http
GET /v2/tags
```

Returns all tags that belong to the application in `X-Application`.

```json
[
  {
    "id": "TAG123",
    "title": {
      "en": "Philosophy",
      "bo": "གྲུབ་མཐའ"
    },
    "description": {
      "en": "Texts related to philosophical systems"
    }
  }
]
```

Example:

```bash
curl "https://api-l25bgmwqoa-uc.a.run.app/v2/tags" \
  -H "X-API-Key: your_api_key" \
  -H "X-Application: webuddhist"
```

## Create Tag

```http
POST /v2/tags
```

Creates a tag in the requested application. The same title can exist in different applications, but duplicate titles in the same application are rejected.

Request:

```json
{
  "title": {
    "en": "Meditation",
    "bo": "སྒོམ།"
  },
  "description": {
    "en": "Meditation and contemplative practice texts"
  }
}
```

Response:

```json
{
  "id": "TAG123"
}
```

Example:

```bash
curl -X POST "https://api-l25bgmwqoa-uc.a.run.app/v2/tags" \
  -H "X-API-Key: your_api_key" \
  -H "X-Application: webuddhist" \
  -H "Content-Type: application/json" \
  -d '{
    "title": {"en": "Meditation", "bo": "སྒོམ།"},
    "description": {"en": "Meditation and contemplative practice texts"}
  }'
```

## Delete Tag

```http
DELETE /v2/tags/{tag_id}
```

Deletes the tag from the application in `X-Application`. Deleting a tag in one application does not delete same-title tags in another application.

Successful deletion returns `204 No Content`.

Delete behavior:

- Deletes the `Tag` node and its title/description `Nomen` and `LocalizedText` subgraphs.
- Removes all `HAS_TAG` relationships from works and segments that used this tag.
- Does not delete works, texts, editions, segmentations, segments, or applications.

Error responses:

- `404 Not Found`: Tag does not exist in the requested application.
- `401 Unauthorized`: Missing or invalid API key in deployed environments.
- `422 Validation Error`: Missing `X-Application` header.

```bash
curl -X DELETE "https://api-l25bgmwqoa-uc.a.run.app/v2/tags/TAG123" \
  -H "X-API-Key: your_api_key" \
  -H "X-Application: webuddhist"
```

## Tag or Untag a Text

```http
POST /v2/texts/{text_id}/tags/{tag_id}
DELETE /v2/texts/{text_id}/tags/{tag_id}
```

These endpoints attach or remove a tag from the work behind a text. They return `204 No Content`.

```bash
curl -X POST "https://api-l25bgmwqoa-uc.a.run.app/v2/texts/TEXT123/tags/TAG123" \
  -H "X-API-Key: your_api_key"

curl -X DELETE "https://api-l25bgmwqoa-uc.a.run.app/v2/texts/TEXT123/tags/TAG123" \
  -H "X-API-Key: your_api_key"
```

Texts can also be created or replaced with tag IDs:

```json
{
  "title": {"bo": "ཆོས་ཀྱི་གཞུང་།"},
  "language": "bo",
  "category_id": "category",
  "contributions": [{"type": "person", "id": "PERSON123", "role": "author"}],
  "tag_ids": ["TAG123"]
}
```

Filter texts by tag. Pass comma-separated IDs in `tag_id`. The default `tag_id_match=all` requires every listed
tag:

```bash
curl "https://api-l25bgmwqoa-uc.a.run.app/v2/texts?tag_id=TAG123,TAG456" \
  -H "X-API-Key: your_api_key"
```

Use `tag_id_match=any` to return texts having at least one listed tag:

```bash
curl "https://api-l25bgmwqoa-uc.a.run.app/v2/texts?tag_id=TAG123,TAG456&tag_id_match=any" \
  -H "X-API-Key: your_api_key"
```

## Tag or Untag a Segment

```http
POST /v2/segments/{segment_id}/tags/{tag_id}
DELETE /v2/segments/{segment_id}/tags/{tag_id}
```

These endpoints attach or remove a tag from a segment. They return `204 No Content`.

```bash
curl -X POST "https://api-l25bgmwqoa-uc.a.run.app/v2/segments/SEG123/tags/TAG123" \
  -H "X-API-Key: your_api_key"
```

## Developer Notes

The router lives in `routers/tags.py`; text and segment tagging endpoints are in `routers/texts.py` and `routers/segments.py`. The request and response models are `TagInput` and `TagOutput` in `models/tag.py`.

Tag titles and descriptions use the same `LocalizedString` shape as categories. Empty localized strings, extra request fields, and missing required application headers are rejected by Pydantic/FastAPI validation.
