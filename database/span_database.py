from typing import TYPE_CHECKING, LiteralString

from .database_validator import DatabaseValidator

if TYPE_CHECKING:
    from neo4j import AsyncManagedTransaction

    from .database import Database


def _adjust_continuous_for_insert(start: int, end: int, insert_pos: int, insert_len: int) -> tuple[int, int]:
    """Adjust continuous span (Segmentation/Pagination) for INSERT. Expands at end boundary and position 0."""
    if insert_pos == 0 and start == 0:
        return (start, end + insert_len)
    if insert_pos <= start:
        return (start + insert_len, end + insert_len)
    if insert_pos <= end:
        return (start, end + insert_len)
    return (start, end)


def _adjust_annotation_for_insert(start: int, end: int, insert_pos: int, insert_len: int) -> tuple[int, int]:
    """Adjust annotation span for INSERT. Shifts at boundaries, only expands when strictly inside."""
    if insert_pos <= start:
        return (start + insert_len, end + insert_len)
    if insert_pos < end:
        return (start, end + insert_len)
    return (start, end)


def _adjust_span_for_delete(start: int, end: int, del_start: int, del_end: int) -> tuple[int, int] | None:
    """Adjust span for DELETE. Returns None if fully encompassed."""
    del_len = del_end - del_start

    if del_end <= start:
        return (start - del_len, end - del_len)
    if del_start >= end:
        return (start, end)
    if del_start <= start and del_end >= end:
        return None
    if del_start <= start < del_end < end:
        return (del_start, end - del_len)
    if start < del_start < end <= del_end:
        return (start, del_start)
    if start < del_start and del_end < end:
        return (start, end - del_len)
    return (start, end)


def _adjust_continuous_for_replace(
    start: int,
    end: int,
    replace_start: int,
    replace_end: int,
    new_len: int,
    *,
    is_first_encompassed: bool,
) -> tuple[int, int] | None:
    """Adjust continuous span (Segmentation/Pagination) for REPLACE. Keeps first encompassed segment."""
    delta = new_len - (replace_end - replace_start)

    if replace_start >= end:
        return (start, end)
    if replace_end <= start:
        return (start + delta, end + delta)
    if start == replace_start and end == replace_end:
        return (start, start + new_len)
    if replace_start <= start and replace_end >= end:
        if is_first_encompassed:
            return (replace_start, replace_start + new_len)
        return None
    if start < replace_start and replace_end < end:
        return (start, end + delta)
    if replace_start <= start < replace_end < end:
        return (replace_start + new_len, end + delta)
    if start < replace_start < end <= replace_end:
        return (start, replace_start + new_len)
    return (start, end)


def _adjust_annotation_for_replace(
    start: int,
    end: int,
    replace_start: int,
    replace_end: int,
    new_len: int,
) -> tuple[int, int] | None:
    """Adjust annotation span for REPLACE. Deletes on exact match or encompass."""
    delta = new_len - (replace_end - replace_start)

    if replace_start >= end:
        return (start, end)
    if replace_end <= start:
        return (start + delta, end + delta)
    if replace_start <= start and replace_end >= end:
        return None
    if start < replace_start and replace_end < end:
        return (start, end + delta)
    if replace_start <= start < replace_end < end:
        return (replace_start + new_len, end + delta)

    return (start, replace_start + new_len)  # start < replace_start < end <= replace_end


class SpanDatabase:
    FIND_CONTINUOUS_SPANS_QUERY: LiteralString = """
    CALL {
        MATCH (m:Edition {id: $edition_id})
            -[:HAS_SEGMENTATION]->()
            <-[:SEGMENT_OF]-(entity:Segment)
            <-[:SPAN_OF]-(span:Span)
        RETURN elementId(span) AS span_id, span.start AS span_start, span.end AS span_end
        UNION ALL
        MATCH (m:Edition {id: $edition_id})
            <-[:PAGINATION_OF]-(:Pagination)
            <-[:VOLUME_OF]-(:Volume)
            <-[:PAGE_OF]-(entity:Page)
            <-[:SPAN_OF]-(span:Span)
        RETURN elementId(span) AS span_id, span.start AS span_start, span.end AS span_end
    }
    RETURN span_id, span_start, span_end
    ORDER BY span_start, span_id, span_end
    """

    FIND_ANNOTATION_SPANS_QUERY: LiteralString = """
    CALL {
        MATCH (m:Edition {id: $edition_id})
            <-[:NOTE_OF|BIBLIOGRAPHY_OF|ATTRIBUTE_OF]-(entity)
            <-[:SPAN_OF]-(span:Span)
        RETURN elementId(span) AS span_id, span.start AS span_start, span.end AS span_end
        UNION ALL
        MATCH (m:Edition {id: $edition_id})
            <-[:TOC_OF]-(:TableOfContents)
            <-[:SECTION_OF]-(entity:TableOfContentsSection)
            <-[:SPAN_OF]-(span:Span)
        RETURN elementId(span) AS span_id, span.start AS span_start, span.end AS span_end
    }
    RETURN span_id, span_start, span_end
    ORDER BY span_start
    """

    BATCH_UPDATE_SPANS_QUERY: LiteralString = """
    UNWIND $updates AS u
    MATCH (span:Span)
    WHERE elementId(span) = u.span_id
    SET span.start = u.new_start, span.end = u.new_end
    FINISH
    """

    BATCH_DELETE_SPANS_QUERY: LiteralString = """
    UNWIND $span_ids AS span_id
    MATCH (span:Span)-[:SPAN_OF]->(
        entity:Segment|Page|BibliographicMetadata|Note|Attribute|TableOfContentsSection
    )
    WHERE elementId(span) = span_id
    DETACH DELETE span
    WITH DISTINCT entity
    WHERE NOT (:Span)-[:SPAN_OF]->(entity)
    OPTIONAL MATCH (entity)-[:HAS_TITLE|HAS_SUMMARY]->(nomen:Nomen)
    OPTIONAL MATCH (nomen)-[:HAS_LOCALIZATION]->(localized:LocalizedText)
    DETACH DELETE localized, nomen, entity
    FINISH
    """

    SHIFT_CONTENT_LENGTH_QUERY: LiteralString = """
    MATCH (m:Edition {id: $edition_id})
    SET m.content_length = m.content_length + $delta
    FINISH
    """

    def __init__(self, db: Database) -> None:
        self._db = db

    @staticmethod
    async def _shift_content_length(tx: AsyncManagedTransaction, edition_id: str, delta: int) -> None:
        if delta:
            await tx.run(SpanDatabase.SHIFT_CONTENT_LENGTH_QUERY, edition_id=edition_id, delta=delta)

    @staticmethod
    async def _flush_batch(
        tx: AsyncManagedTransaction,
        updates: list[dict[str, str | int]],
        deletes: list[str],
    ) -> None:
        """Execute batched span updates and deletions."""
        if updates:
            await tx.run(SpanDatabase.BATCH_UPDATE_SPANS_QUERY, updates=updates)
        if deletes:
            await tx.run(SpanDatabase.BATCH_DELETE_SPANS_QUERY, span_ids=deletes)

    async def adjust_spans_for_insert(self, edition_id: str, position: int, length: int) -> None:
        """Adjust all spans for an INSERT operation."""

        async def write(tx: AsyncManagedTransaction) -> None:
            await DatabaseValidator.validate_edition_spans(tx, edition_id, position)
            updates: list[dict[str, str | int]] = []

            result = await tx.run(self.FIND_CONTINUOUS_SPANS_QUERY, edition_id=edition_id)
            for record in await result.data():
                adjusted = _adjust_continuous_for_insert(record["span_start"], record["span_end"], position, length)
                if adjusted != (record["span_start"], record["span_end"]):
                    updates.append({"span_id": record["span_id"], "new_start": adjusted[0], "new_end": adjusted[1]})

            result = await tx.run(self.FIND_ANNOTATION_SPANS_QUERY, edition_id=edition_id)
            for record in await result.data():
                adjusted = _adjust_annotation_for_insert(record["span_start"], record["span_end"], position, length)
                if adjusted != (record["span_start"], record["span_end"]):
                    updates.append({"span_id": record["span_id"], "new_start": adjusted[0], "new_end": adjusted[1]})

            await self._flush_batch(tx, updates, [])
            await self._shift_content_length(tx, edition_id, length)

        async with self._db.get_session() as session:
            await session.execute_write(write)

    async def adjust_spans_for_delete(self, edition_id: str, start: int, end: int) -> None:
        """Adjust all spans for a DELETE operation."""

        async def write(tx: AsyncManagedTransaction) -> None:
            await DatabaseValidator.validate_edition_spans(tx, edition_id, end)
            updates: list[dict[str, str | int]] = []
            deletes: list[str] = []

            result = await tx.run(self.FIND_CONTINUOUS_SPANS_QUERY, edition_id=edition_id)
            for record in await result.data():
                adjusted = _adjust_span_for_delete(record["span_start"], record["span_end"], start, end)
                if adjusted is None:
                    deletes.append(record["span_id"])
                elif adjusted != (record["span_start"], record["span_end"]):
                    updates.append({"span_id": record["span_id"], "new_start": adjusted[0], "new_end": adjusted[1]})

            result = await tx.run(self.FIND_ANNOTATION_SPANS_QUERY, edition_id=edition_id)
            for record in await result.data():
                adjusted = _adjust_span_for_delete(record["span_start"], record["span_end"], start, end)
                if adjusted is None:
                    deletes.append(record["span_id"])
                elif adjusted != (record["span_start"], record["span_end"]):
                    updates.append({"span_id": record["span_id"], "new_start": adjusted[0], "new_end": adjusted[1]})

            await self._flush_batch(tx, updates, deletes)
            await self._shift_content_length(tx, edition_id, start - end)

        async with self._db.get_session() as session:
            await session.execute_write(write)

    async def adjust_spans_for_replace(self, edition_id: str, start: int, end: int, new_len: int) -> None:
        """Adjust all spans for a REPLACE operation."""

        async def write(tx: AsyncManagedTransaction) -> None:
            await DatabaseValidator.validate_edition_spans(tx, edition_id, end)
            updates: list[dict[str, str | int]] = []
            deletes: list[str] = []
            first_encompassed_found = False

            result = await tx.run(self.FIND_CONTINUOUS_SPANS_QUERY, edition_id=edition_id)
            for record in await result.data():
                span_start = record["span_start"]
                span_end = record["span_end"]
                is_encompassed = start <= span_start and end >= span_end
                is_first = is_encompassed and not first_encompassed_found
                if is_first:
                    first_encompassed_found = True

                adjusted = _adjust_continuous_for_replace(
                    span_start, span_end, start, end, new_len, is_first_encompassed=is_first
                )
                if adjusted is None:
                    deletes.append(record["span_id"])
                elif adjusted != (span_start, span_end):
                    updates.append({"span_id": record["span_id"], "new_start": adjusted[0], "new_end": adjusted[1]})

            result = await tx.run(self.FIND_ANNOTATION_SPANS_QUERY, edition_id=edition_id)
            for record in await result.data():
                adjusted = _adjust_annotation_for_replace(record["span_start"], record["span_end"], start, end, new_len)
                if adjusted is None:
                    deletes.append(record["span_id"])
                elif adjusted != (record["span_start"], record["span_end"]):
                    updates.append({"span_id": record["span_id"], "new_start": adjusted[0], "new_end": adjusted[1]})

            await self._flush_batch(tx, updates, deletes)
            await self._shift_content_length(tx, edition_id, new_len - (end - start))

        async with self._db.get_session() as session:
            await session.execute_write(write)
