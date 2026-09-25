from typing import TYPE_CHECKING, LiteralString

from database.database_validator import DatabaseValidator
from exceptions import DataNotFoundError

if TYPE_CHECKING:
    from neo4j import AsyncManagedTransaction

    from database.database import Database
from identifier import generate_id
from models.annotation import MarkInput, MarkOutput
from models.enums import MarkType


class MarkDatabase:
    GET_BY_ID_QUERY: LiteralString = """
    MATCH (span:Span)-[:SPAN_OF]->(mark:Mark {id: $mark_id})
        -[:MARK_OF]->(edition:Edition)-[:EDITION_OF]->(text:Text)
    WHERE span.start < span.end
    RETURN mark.id AS id,
           edition.id AS edition_id,
           text.id AS text_id,
           {start: span.start, end: span.end} AS span
    """

    GET_BY_EDITION_ID_QUERY: LiteralString = """
    MATCH (edition:Edition {id: $edition_id})<-[:MARK_OF]-(mark:Mark)
        -[:HAS_TYPE]->(:MarkType {name: $mark_type}),
        (edition)-[:EDITION_OF]->(text:Text)
    MATCH (span:Span)-[:SPAN_OF]->(mark)
    WHERE span.start < span.end
    RETURN mark.id AS id,
           edition.id AS edition_id,
           text.id AS text_id,
           {start: span.start, end: span.end} AS span
    ORDER BY span.start
    """

    CREATE_QUERY: LiteralString = """
    MATCH (edition:Edition {id: $edition_id})
    MERGE (mark_type:MarkType {name: $mark_type})
    CREATE (span:Span {start: $span_start, end: $span_end})
        -[:SPAN_OF]->(mark:Mark {id: $mark_id})
        -[:MARK_OF]->(edition),
        (mark)-[:HAS_TYPE]->(mark_type)
    RETURN mark.id AS mark_id
    """

    DELETE_QUERY: LiteralString = """
    MATCH (mark:Mark {id: $mark_id})
    OPTIONAL MATCH (span:Span)-[:SPAN_OF]->(mark)
    DETACH DELETE span, mark
    FINISH
    """

    DELETE_ALL_QUERY: LiteralString = """
    MATCH (mark:Mark)-[:MARK_OF]->(:Edition {id: $edition_id})
    OPTIONAL MATCH (span:Span)-[:SPAN_OF]->(mark)
    DETACH DELETE span, mark
    FINISH
    """

    def __init__(self, db: Database) -> None:
        self._db = db

    async def get(self, mark_id: str) -> MarkOutput:
        async def read(tx: AsyncManagedTransaction) -> MarkOutput:
            result = await tx.run(MarkDatabase.GET_BY_ID_QUERY, mark_id=mark_id)
            record = await result.single()
            if record is None:
                raise DataNotFoundError(f"Mark with ID '{mark_id}' not found")
            return MarkOutput.model_validate(record)

        async with self._db.get_session() as session:
            return await session.execute_read(read)

    async def get_all(
        self,
        edition_id: str,
        mark_type: MarkType = MarkType.YIGCHUNG,
    ) -> list[MarkOutput]:
        async def read(tx: AsyncManagedTransaction) -> list[MarkOutput]:
            result = await tx.run(
                MarkDatabase.GET_BY_EDITION_ID_QUERY,
                edition_id=edition_id,
                mark_type=mark_type.value,
            )
            return [MarkOutput.model_validate(record) for record in await result.data()]

        async with self._db.get_session() as session:
            return await session.execute_read(read)

    async def add_yigchung(self, edition_id: str, mark: MarkInput) -> str:
        async with self._db.get_session() as session:
            return await session.execute_write(
                lambda tx: MarkDatabase.add_with_transaction(tx, edition_id, mark, MarkType.YIGCHUNG)
            )

    @staticmethod
    async def add_with_transaction(
        tx: AsyncManagedTransaction,
        edition_id: str,
        mark: MarkInput,
        mark_type: MarkType,
    ) -> str:
        await DatabaseValidator.validate_edition_spans(tx, edition_id, mark.max_end)

        generated_id = generate_id()
        await tx.run(
            MarkDatabase.CREATE_QUERY,
            edition_id=edition_id,
            mark_id=generated_id,
            mark_type=mark_type.value,
            span_start=mark.span.start,
            span_end=mark.span.end,
        )
        return generated_id

    @staticmethod
    async def delete_with_transaction(tx: AsyncManagedTransaction, mark_id: str) -> None:
        await tx.run(MarkDatabase.DELETE_QUERY, mark_id=mark_id)

    async def delete(self, mark_id: str) -> None:
        async with self._db.get_session() as session:
            await session.execute_write(lambda tx: MarkDatabase.delete_with_transaction(tx, mark_id))

    @staticmethod
    async def delete_all_with_transaction(tx: AsyncManagedTransaction, edition_id: str) -> None:
        await tx.run(MarkDatabase.DELETE_ALL_QUERY, edition_id=edition_id)
