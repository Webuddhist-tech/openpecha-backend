from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from content_search.opensearch_client import ContentSearchOpenSearchClient
from exceptions import DataNotFoundError
from models.annotation import SegmentWithContextOutput
from models.content_search import (
    ContentSearchResult,
    ContentSearchSpan,
)

if TYPE_CHECKING:
    from database import Database
    from storage import Storage

logger = logging.getLogger(__name__)

DEFAULT_CHUNK_CHARS = 4000
DEFAULT_CHUNK_OVERLAP_CHARS = 500
SIMILAR_PHRASE_SLOP = 12
CONTEXT_CHARS = 200


class ContentSearchService:
    def __init__(
        self,
        *,
        endpoint: str,
        index_name: str,
        region: str,
        auth_mode: str = "basic",
        username: str = "",
        password: str = "",
        chunk_chars: int = DEFAULT_CHUNK_CHARS,
        chunk_overlap_chars: int = DEFAULT_CHUNK_OVERLAP_CHARS,
        request_timeout: int = 120,
        max_retries: int = 3,
    ) -> None:
        if chunk_overlap_chars >= chunk_chars:
            raise ValueError("chunk_overlap_chars must be smaller than chunk_chars")
        self._client = ContentSearchOpenSearchClient(
            endpoint=endpoint,
            index_name=index_name,
            region=region,
            auth_mode=auth_mode,
            username=username,
            password=password,
            request_timeout=request_timeout,
            max_retries=max_retries,
        )
        self.chunk_chars = chunk_chars
        self.chunk_overlap_chars = chunk_overlap_chars

    async def connect(self) -> None:
        await self._client.connect()
        await self.setup_index()

    async def close(self) -> None:
        await self._client.close()

    async def delete_index(self) -> None:
        await self._client.delete_index()

    async def refresh_index(self) -> None:
        await self._client.refresh_index()

    async def setup_index(self) -> None:
        if await self._client.index_exists():
            return
        await self._client.create_index(_index_body())

    async def index_edition(self, edition_id: str, db: Database, storage: Storage, *, refresh: bool = True) -> None:
        try:
            edition = await db.edition.get(edition_id)
            text = await db.text.get(edition.text_id)
            content = await storage.retrieve_base_text(text_id=edition.text_id, edition_id=edition_id)
            segments = await _get_display_segments_for_edition(db, edition_id=edition_id, text_id=edition.text_id)
            if not segments:
                logger.warning(
                    "Skipping content search indexing for edition %s because it has no display segments",
                    edition_id,
                )
                await self.delete_edition(edition_id, refresh=refresh)
                return
            documents = _build_chunk_documents(
                text_id=edition.text_id,
                edition_id=edition_id,
                edition_type=edition.type.value,
                language=text.language,
                title=text.title.root,
                source=edition.source,
                content=content,
                segments=segments,
                chunk_chars=self.chunk_chars,
                chunk_overlap_chars=self.chunk_overlap_chars,
            )

            await self.delete_edition(edition_id, refresh=refresh)
            await self._client.bulk_index(documents, refresh=refresh)
            logger.info("Indexed %d content search chunks for edition %s", len(documents), edition_id)
        except Exception:
            logger.exception("Failed to index content search chunks for edition %s", edition_id)
            raise

    async def delete_edition(self, edition_id: str, *, refresh: bool = True) -> None:
        await self._client.delete_edition(edition_id, refresh=refresh)

    async def delete_all_documents(self, *, refresh: bool = True) -> None:
        await self._client.delete_all_documents(refresh=refresh)

    async def search(
        self,
        *,
        query: str,
        search_type: str,
        limit: int,
        text_id: str | None = None,
        edition_id: str | None = None,
    ) -> list[ContentSearchResult]:
        response = await self._client.search(
            _search_body(
                query=query,
                search_type=search_type,
                limit=limit,
                text_id=text_id,
                edition_id=edition_id,
            ),
        )
        return _parse_results(response, query=query, search_type=search_type, limit=limit)


async def _get_display_segments_for_edition(
    db: Database,
    *,
    edition_id: str,
    text_id: str,
) -> list[SegmentWithContextOutput]:
    try:
        segmentation = await db.annotation.segmentation.get_by_edition(edition_id)
    except DataNotFoundError:
        return []

    segments = await db.annotation.segmentation.get_all_segments_by_edition(edition_id)
    return [
        SegmentWithContextOutput(
            id=segment.id,
            reference=segment.reference,
            segmentation_id=segmentation.id,
            edition_id=edition_id,
            text_id=text_id,
            lines=segment.lines,
        )
        for segment in segments
    ]


def _index_body() -> dict:
    return {
        "settings": {
            "number_of_shards": 1,
            "analysis": {
                "analyzer": {
                    "content_search_default": {
                        "type": "custom",
                        "tokenizer": "icu_tokenizer",
                        "filter": ["lowercase"],
                    },
                },
            },
        },
        "mappings": {
            "properties": {
                "id": {"type": "keyword"},
                "document_type": {"type": "keyword"},
                "text_id": {"type": "keyword"},
                "edition_id": {"type": "keyword"},
                "primary_segment_id": {"type": "keyword"},
                "edition_type": {"type": "keyword"},
                "language": {"type": "keyword"},
                "title": {"type": "object", "enabled": False},
                "source": {"type": "keyword"},
                "segments": {
                    "type": "nested",
                    "properties": {
                        "id": {"type": "keyword"},
                        "span_start": {"type": "integer"},
                        "span_end": {"type": "integer"},
                    },
                },
                "context_span_start": {"type": "integer"},
                "context_span_end": {"type": "integer"},
                "content": {
                    "type": "text",
                    "analyzer": "content_search_default",
                },
            },
        },
    }


def _build_chunk_documents(
    *,
    text_id: str,
    edition_id: str,
    edition_type: str,
    language: str,
    title: dict[str, str],
    source: str | None,
    content: str,
    segments: list[SegmentWithContextOutput],
    chunk_chars: int,
    chunk_overlap_chars: int,
) -> list[dict]:
    documents = []
    overlap_start_index = 0
    chunk_start = 0
    chunk_index = 0
    step = chunk_chars - chunk_overlap_chars
    while chunk_start < len(content):
        chunk_end = min(len(content), chunk_start + chunk_chars)
        covered_segments, overlap_start_index = _segments_overlapping_from_index(
            segments,
            start=chunk_start,
            end=chunk_end,
            start_index=overlap_start_index,
        )
        if not covered_segments:
            chunk_start += step
            continue
        documents.append(
            _document(
                document_id=f"{edition_id}:chunk:{chunk_index}",
                text_id=text_id,
                edition_id=edition_id,
                primary_segment_id=covered_segments[0].id,
                edition_type=edition_type,
                language=language,
                title=title,
                source=source,
                content=content[chunk_start:chunk_end],
                context_start=chunk_start,
                context_end=chunk_end,
                segments=covered_segments,
            )
        )
        chunk_index += 1
        if chunk_end == len(content):
            break
        chunk_start += step
    return documents


def _document(
    *,
    document_id: str,
    text_id: str,
    edition_id: str,
    primary_segment_id: str | None,
    edition_type: str,
    language: str,
    title: dict[str, str],
    source: str | None,
    content: str,
    context_start: int,
    context_end: int,
    segments: list[SegmentWithContextOutput],
) -> dict:
    segment_docs = [
        {
            "id": segment.id,
            "span_start": segment.span.start,
            "span_end": segment.span.end,
        }
        for segment in segments
    ]
    return {
        "id": document_id,
        "document_type": "chunk",
        "text_id": text_id,
        "edition_id": edition_id,
        "primary_segment_id": primary_segment_id,
        "edition_type": edition_type,
        "language": language,
        "title": title,
        "source": source,
        "segments": segment_docs,
        "context_span_start": context_start,
        "context_span_end": context_end,
        "content": content,
    }


def _segments_overlapping_from_index(
    segments: list[SegmentWithContextOutput],
    *,
    start: int,
    end: int,
    start_index: int,
) -> tuple[list[SegmentWithContextOutput], int]:
    while start_index < len(segments) and segments[start_index].span.end <= start:
        start_index += 1

    overlapping = []
    index = start_index
    while index < len(segments):
        segment = segments[index]
        if segment.span.start >= end:
            break
        if segment.span.end > start:
            overlapping.append(segment)
        index += 1
    return overlapping, start_index


def _search_body(
    *,
    query: str,
    search_type: str,
    limit: int,
    text_id: str | None,
    edition_id: str | None,
) -> dict:
    filters = []
    if text_id:
        filters.append({"term": {"text_id": text_id}})
    if edition_id:
        filters.append({"term": {"edition_id": edition_id}})

    must = [_exact_candidate_query(query)] if search_type == "exact" else [_similar_candidate_query(query)]
    return {
        "size": max(limit * 10, 50) if search_type == "exact" else limit,
        "query": {"bool": {"must": must, "filter": filters}},
        "highlight": {
            "pre_tags": [""],
            "post_tags": [""],
            "fields": {
                "content": {
                    "number_of_fragments": 1,
                    "fragment_size": CONTEXT_CHARS,
                }
            },
        },
    }


def _exact_candidate_query(query: str) -> dict:
    return {
        "bool": {
            "should": [
                {"match_phrase": {"content": {"query": query, "boost": 3}}},
                {"match": {"content": {"query": query, "operator": "and"}}},
            ],
            "minimum_should_match": 1,
        }
    }


def _similar_candidate_query(query: str) -> dict:
    return {"match_phrase": {"content": {"query": query, "slop": SIMILAR_PHRASE_SLOP}}}


def _parse_results(response: dict, *, query: str, search_type: str, limit: int) -> list[ContentSearchResult]:
    results: list[ContentSearchResult] = []
    seen: set[tuple[str, int | None, int | None, int, int]] = set()
    for hit in response.get("hits", {}).get("hits", []):
        source = hit.get("_source", {})
        if search_type == "exact":
            for result in _exact_results_from_hit(hit, source, query):
                key = (
                    result.edition_id,
                    result.match_span.start if result.match_span else None,
                    result.match_span.end if result.match_span else None,
                    0,
                    0,
                )
                if key in seen:
                    continue
                seen.add(key)
                results.append(result)
                if len(results) >= limit:
                    return results
        else:
            result = _similar_result_from_hit(hit, source)
            key = (result.edition_id, None, None, result.context_span.start, result.context_span.end)
            if key in seen:
                continue
            seen.add(key)
            results.append(result)
            if len(results) >= limit:
                return results
    return results


def _exact_results_from_hit(hit: dict, source: dict, query: str) -> list[ContentSearchResult]:
    content = source.get("content", "")
    context_start = source.get("context_span_start", 0)
    results = []
    search_from = 0
    while True:
        local_start = content.find(query, search_from)
        if local_start == -1:
            break
        local_end = local_start + len(query)
        match_span = ContentSearchSpan(start=context_start + local_start, end=context_start + local_end)
        context, result_context_span = _context_around_match(source, match_span)
        results.append(
            _result(
                hit=hit,
                source=source,
                context=context,
                context_span=result_context_span,
                match_span=match_span,
                segment_ids=_segment_ids_from_source(source, match_span),
            )
        )
        search_from = local_start + 1
    return results


def _similar_result_from_hit(hit: dict, source: dict) -> ContentSearchResult:
    context, context_span = _context_from_hit(hit, source)
    return _result(
        hit=hit,
        source=source,
        context=context,
        context_span=context_span,
        match_span=None,
        segment_ids=_segment_ids_from_source(source, context_span),
    )


def _result(
    *,
    hit: dict,
    source: dict,
    context: str,
    context_span: ContentSearchSpan,
    match_span: ContentSearchSpan | None,
    segment_ids: list[str],
) -> ContentSearchResult:
    return ContentSearchResult(
        text_id=source["text_id"],
        edition_id=source["edition_id"],
        segment_ids=segment_ids,
        context_span=context_span,
        match_span=match_span,
        score=float(hit.get("_score") or 0.0),
        context=context,
    )


def _segment_ids_from_source(
    source: dict,
    match_span: ContentSearchSpan | None = None,
) -> list[str]:
    raw_segments = source.get("segments", [])
    if match_span is not None:
        raw_segments = [
            segment
            for segment in raw_segments
            if segment["span_start"] < match_span.end and segment["span_end"] > match_span.start
        ]
    return [segment["id"] for segment in raw_segments]


def _context_around_match(source: dict, match_span: ContentSearchSpan) -> tuple[str, ContentSearchSpan]:
    content = source.get("content", "")
    chunk_start = source.get("context_span_start", 0)
    local_start = max(0, match_span.start - chunk_start)
    local_end = min(len(content), match_span.end - chunk_start)
    match_length = local_end - local_start
    remaining_context_chars = max(CONTEXT_CHARS - match_length, 0)
    before_chars = remaining_context_chars // 2
    after_chars = remaining_context_chars - before_chars
    context_start = max(0, local_start - before_chars)
    context_end = min(len(content), local_end + after_chars)
    return _context_from_local_span(source, context_start, context_end)


def _context_from_hit(hit: dict, source: dict) -> tuple[str, ContentSearchSpan]:
    content = source.get("content", "")
    highlights = hit.get("highlight", {}).get("content", [])
    if highlights:
        highlighted_context = highlights[0]
        local_start = content.find(highlighted_context)
        if local_start != -1:
            return _context_from_local_span(source, local_start, local_start + len(highlighted_context))

    return _context_from_local_span(source, 0, min(len(content), CONTEXT_CHARS))


def _context_from_local_span(source: dict, start: int, end: int) -> tuple[str, ContentSearchSpan]:
    content = source.get("content", "")
    chunk_start = source.get("context_span_start", 0)
    return (
        content[start:end],
        ContentSearchSpan(start=chunk_start + start, end=chunk_start + end),
    )
