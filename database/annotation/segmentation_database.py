from typing import TYPE_CHECKING, LiteralString

from neo4j.exceptions import ResultNotSingleError

from exceptions import DataConflictError, DataNotFoundError

if TYPE_CHECKING:
    from neo4j import AsyncManagedTransaction

    from database.database import Database
from database.database_validator import DatabaseValidator
from identifier import generate_id
from models.annotation import SegmentationInput, SegmentationOutput, SegmentOutput


class SegmentationDatabase:
    _GET_PARENT_QUERY_BODY: LiteralString = """
    MATCH (edition)-[:EDITION_OF]->(text:Text)
    RETURN segmentation.id AS id,
           edition.id AS edition_id,
           text.id AS text_id
    ORDER BY id
    """

    _GET_SEGMENTS_QUERY_BODY: LiteralString = """
    MATCH (segment:Segment)-[:SEGMENT_OF]->(segmentation)
    CALL (segment) {
        MATCH (span:Span)-[:SPAN_OF]->(segment)
        WHERE span.start < span.end
        WITH span ORDER BY span.start
        RETURN collect({start: span.start, end: span.end}) AS lines,
               min(span.start) AS min_start
    }
    WITH segment, lines, min_start
    WHERE size(lines) > 0
    ORDER BY min_start, segment.id
    RETURN segment.id AS id, segment.type AS type, segment.reference AS reference, lines
    """

    GET_BY_EDITION_ID_QUERY: LiteralString = f"""
    MATCH (edition:Edition {{id: $edition_id}})-[:HAS_SEGMENTATION]->(segmentation:Segmentation)
    {_GET_PARENT_QUERY_BODY}
    """

    GET_SEGMENTS_BY_EDITION_ID_QUERY: LiteralString = f"""
    MATCH (:Edition {{id: $edition_id}})-[:HAS_SEGMENTATION]->(segmentation:Segmentation)
    {_GET_SEGMENTS_QUERY_BODY}
    SKIP $offset
    LIMIT $limit
    """

    GET_ALL_SEGMENTS_BY_EDITION_ID_QUERY: LiteralString = f"""
    MATCH (:Edition {{id: $edition_id}})-[:HAS_SEGMENTATION]->(segmentation:Segmentation)
    {_GET_SEGMENTS_QUERY_BODY}
    """

    CHECK_EDITION_SEGMENTATION_EXISTS_QUERY: LiteralString = """
    RETURN EXISTS { (:Edition {id: $edition_id})-[:HAS_SEGMENTATION]->(:Segmentation) } AS exists
    """

    CREATE_QUERY: LiteralString = """
    MATCH (edition:Edition {id: $edition_id})
    WITH edition
    WHERE NOT EXISTS { (edition)-[:HAS_SEGMENTATION]->(:Segmentation) }
    CREATE (edition)-[:HAS_SEGMENTATION]->(segmentation:Segmentation {id: $segmentation_id})
    WITH segmentation
    UNWIND $segments AS segment_data
    CREATE (segment:Segment {id: segment_data.id})-[:SEGMENT_OF]->(segmentation)
    SET segment.reference = segment_data.reference,
        segment.type = segment_data.type
    WITH segmentation, segment, segment_data
    UNWIND segment_data.lines AS line
    CREATE (:Span {start: line.start, end: line.end})-[:SPAN_OF]->(segment)
    RETURN segmentation.id AS id, count(*) AS segment_count
    """

    DELETE_BY_EDITION_ID_QUERY: LiteralString = """
    MATCH (edition:Edition {id: $edition_id})
    OPTIONAL MATCH (edition)-[:HAS_SEGMENTATION]->(segmentation:Segmentation)
    OPTIONAL MATCH (segment:Segment)-[:SEGMENT_OF]->(segmentation)
    OPTIONAL MATCH (span:Span)-[:SPAN_OF]->(segment)
    DETACH DELETE span, segment, segmentation
    FINISH
    """

    def __init__(self, db: Database) -> None:
        self._db = db

    async def get_by_edition(self, edition_id: str) -> SegmentationOutput:
        async with self._db.get_session() as session:
            return await session.execute_read(
                lambda tx: SegmentationDatabase.get_by_edition_with_transaction(tx, edition_id)
            )

    async def get_segments_by_edition(
        self,
        edition_id: str,
        *,
        offset: int,
        limit: int,
    ) -> list[SegmentOutput]:
        async with self._db.get_session() as session:
            return await session.execute_read(
                lambda tx: SegmentationDatabase.get_segments_by_edition_with_transaction(
                    tx,
                    edition_id,
                    offset=offset,
                    limit=limit,
                )
            )

    async def get_all_segments_by_edition(self, edition_id: str) -> list[SegmentOutput]:
        async with self._db.get_session() as session:
            return await session.execute_read(
                lambda tx: SegmentationDatabase.get_all_segments_by_edition_with_transaction(tx, edition_id)
            )

    @staticmethod
    async def add_with_transaction(
        tx: AsyncManagedTransaction, edition_id: str, segmentation: SegmentationInput
    ) -> str:
        await DatabaseValidator.validate_edition_spans(tx, edition_id, segmentation.max_end)

        segmentation_id = generate_id()

        segments_data = [
            {
                "id": generate_id(),
                "type": seg.type.value,
                "reference": seg.reference,
                "lines": [{"start": line.start, "end": line.end} for line in seg.lines],
            }
            for seg in segmentation.segments
        ]

        result = await tx.run(
            SegmentationDatabase.CREATE_QUERY,
            edition_id=edition_id,
            segmentation_id=segmentation_id,
            segments=segments_data,
        )
        try:
            record = await result.single(strict=True)
        except ResultNotSingleError as exc:
            raise DataConflictError(f"Edition with ID '{edition_id}' already has a segmentation") from exc
        if record["segment_count"] == 0:
            raise DataConflictError(f"Edition with ID '{edition_id}' already has a segmentation")
        return str(record["id"])

    async def add(self, edition_id: str, segmentation: SegmentationInput) -> str:
        async with self._db.get_session() as session:
            return await session.execute_write(
                lambda tx: SegmentationDatabase.add_with_transaction(tx, edition_id, segmentation)
            )

    @staticmethod
    async def get_by_edition_with_transaction(tx: AsyncManagedTransaction, edition_id: str) -> SegmentationOutput:
        await DatabaseValidator.validate_edition_exists(tx, edition_id)
        result = await tx.run(SegmentationDatabase.GET_BY_EDITION_ID_QUERY, edition_id=edition_id)
        record = await result.single()
        if record is None:
            raise DataNotFoundError(f"Segmentation for edition '{edition_id}' not found")
        return SegmentationOutput.model_validate(record)

    @staticmethod
    async def get_segments_by_edition_with_transaction(
        tx: AsyncManagedTransaction,
        edition_id: str,
        *,
        offset: int,
        limit: int,
    ) -> list[SegmentOutput]:
        await DatabaseValidator.validate_edition_exists(tx, edition_id)
        result = await tx.run(
            SegmentationDatabase.GET_SEGMENTS_BY_EDITION_ID_QUERY,
            edition_id=edition_id,
            offset=offset,
            limit=limit,
        )
        records = await result.data()
        if not records:
            await SegmentationDatabase._validate_edition_has_segmentation(tx, edition_id)
        return [SegmentOutput.model_validate(record) for record in records]

    @staticmethod
    async def get_all_segments_by_edition_with_transaction(
        tx: AsyncManagedTransaction,
        edition_id: str,
    ) -> list[SegmentOutput]:
        await DatabaseValidator.validate_edition_exists(tx, edition_id)
        result = await tx.run(SegmentationDatabase.GET_ALL_SEGMENTS_BY_EDITION_ID_QUERY, edition_id=edition_id)
        records = await result.data()
        if not records:
            await SegmentationDatabase._validate_edition_has_segmentation(tx, edition_id)
        return [SegmentOutput.model_validate(record) for record in records]

    @staticmethod
    async def _validate_edition_has_segmentation(tx: AsyncManagedTransaction, edition_id: str) -> None:
        exists_result = await tx.run(
            SegmentationDatabase.CHECK_EDITION_SEGMENTATION_EXISTS_QUERY,
            edition_id=edition_id,
        )
        exists_record = await exists_result.single()
        if not exists_record or not exists_record["exists"]:
            raise DataNotFoundError(f"Segmentation for edition '{edition_id}' not found")

    async def delete_by_edition(self, edition_id: str) -> None:
        async with self._db.get_session() as session:
            await session.execute_write(
                lambda tx: SegmentationDatabase.delete_by_edition_with_transaction(tx, edition_id)
            )

    @staticmethod
    async def delete_by_edition_with_transaction(tx: AsyncManagedTransaction, edition_id: str) -> None:
        await DatabaseValidator.validate_edition_exists(tx, edition_id)
        await tx.run(SegmentationDatabase.DELETE_BY_EDITION_ID_QUERY, edition_id=edition_id)
