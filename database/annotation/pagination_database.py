from typing import TYPE_CHECKING, LiteralString

from database.database_validator import DatabaseValidator
from exceptions import DataConflictError, DataNotFoundError

if TYPE_CHECKING:
    from neo4j import AsyncManagedTransaction

    from database.database import Database
from identifier import generate_id
from models.annotation import PaginationInput, PaginationOutput


class PaginationDatabase:
    _GET_QUERY_BODY: LiteralString = """
    WITH pagination, edition, text, volume, page, span
    ORDER BY volume.index, span.start, span.end
    WITH pagination, edition, text, volume, page, collect({start: span.start, end: span.end}) AS lines
    WITH pagination, edition, text, volume, collect({reference: page.reference, lines: lines}) AS pages
    WITH pagination, edition, text, collect({index: volume.index, pages: pages}) AS volumes
    RETURN pagination.id AS id, edition.id AS edition_id, text.id AS text_id, volumes
    """

    GET_BY_ID_QUERY: LiteralString = f"""
    MATCH (pagination:Pagination {{id: $pagination_id}})
        -[:PAGINATION_OF]->(edition:Edition)
        -[:EDITION_OF]->(text:Text),
        (pagination)<-[:VOLUME_OF]-(volume:Volume)
        <-[:PAGE_OF]-(page:Page)
        <-[:SPAN_OF]-(span:Span)
    {_GET_QUERY_BODY}
    """

    GET_BY_EDITION_ID_QUERY: LiteralString = f"""
    MATCH (edition:Edition {{id: $edition_id}})
        -[:EDITION_OF]->(text:Text),
        (edition)<-[:PAGINATION_OF]-(pagination:Pagination)
        <-[:VOLUME_OF]-(volume:Volume)
        <-[:PAGE_OF]-(page:Page)
        <-[:SPAN_OF]-(span:Span)
    {_GET_QUERY_BODY}
    """

    CREATE_QUERY: LiteralString = """
    MATCH (edition:Edition {id: $edition_id})
    CREATE (pagination:Pagination {id: $pagination_id})-[:PAGINATION_OF]->(edition)
    WITH pagination
    UNWIND $volumes AS volume_data
    CREATE (volume:Volume {id: volume_data.id, index: volume_data.index})-[:VOLUME_OF]->(pagination)
    WITH pagination, volume, volume_data
    UNWIND volume_data.pages AS page_data
    CREATE (page:Page {id: page_data.id, reference: page_data.reference})-[:PAGE_OF]->(volume)
    WITH pagination, page, page_data
    UNWIND page_data.lines AS line
    CREATE (:Span {start: line.start, end: line.end})-[:SPAN_OF]->(page)
    RETURN pagination.id AS id, count(*) AS count
    """

    DELETE_QUERY: LiteralString = """
    MATCH (pagination:Pagination {id: $pagination_id})
    OPTIONAL MATCH (span:Span)-[:SPAN_OF]->(page:Page)-[:PAGE_OF]->(volume:Volume)-[:VOLUME_OF]->(pagination)
    DETACH DELETE span, page, volume, pagination
    FINISH
    """

    DELETE_ALL_QUERY: LiteralString = """
    MATCH (pagination:Pagination)-[:PAGINATION_OF]->(:Edition {id: $edition_id})
    OPTIONAL MATCH (span:Span)-[:SPAN_OF]->(page:Page)-[:PAGE_OF]->(volume:Volume)-[:VOLUME_OF]->(pagination)
    DETACH DELETE span, page, volume, pagination
    FINISH
    """

    def __init__(self, db: Database) -> None:
        self._db = db

    async def get(self, pagination_id: str) -> PaginationOutput:
        async def read(tx: AsyncManagedTransaction) -> PaginationOutput:
            result = await tx.run(PaginationDatabase.GET_BY_ID_QUERY, pagination_id=pagination_id)
            record = await result.single()
            if record is None:
                raise DataNotFoundError(f"Pagination with ID '{pagination_id}' not found")
            return PaginationOutput.model_validate(record)

        async with self._db.get_session() as session:
            return await session.execute_read(read)

    async def get_all(self, edition_id: str) -> PaginationOutput | None:
        async def read(tx: AsyncManagedTransaction) -> PaginationOutput | None:
            result = await tx.run(PaginationDatabase.GET_BY_EDITION_ID_QUERY, edition_id=edition_id)
            record = await result.single()
            return PaginationOutput.model_validate(record) if record else None

        async with self._db.get_session() as session:
            return await session.execute_read(read)

    async def add(self, edition_id: str, pagination: PaginationInput) -> str:
        async with self._db.get_session() as session:
            return await session.execute_write(
                lambda tx: PaginationDatabase.add_with_transaction(tx, edition_id, pagination)
            )

    @staticmethod
    async def add_with_transaction(
        tx: AsyncManagedTransaction,
        edition_id: str,
        pagination: PaginationInput,
    ) -> str:
        await DatabaseValidator.validate_edition_spans(tx, edition_id, pagination.max_end)

        existing = await tx.run(
            "RETURN EXISTS { (:Pagination)-[:PAGINATION_OF]->(:Edition {id: $edition_id}) } AS exists",
            edition_id=edition_id,
        )
        record = await existing.single()
        if record and record["exists"]:
            raise DataConflictError(f"Edition '{edition_id}' already has a pagination")

        pagination_id = generate_id()

        volumes_data = []
        for volume in pagination.volumes:
            volume_id = generate_id()
            pages_data = [
                {
                    "id": generate_id(),
                    "reference": page.reference,
                    "lines": [{"start": line.start, "end": line.end} for line in page.lines],
                }
                for page in volume.pages
            ]
            volumes_data.append({"id": volume_id, "index": volume.index, "pages": pages_data})

        result = await tx.run(
            PaginationDatabase.CREATE_QUERY,
            edition_id=edition_id,
            pagination_id=pagination_id,
            volumes=volumes_data,
        )
        record = await result.single(strict=True)
        return str(record["id"])

    @staticmethod
    async def delete_with_transaction(tx: AsyncManagedTransaction, pagination_id: str) -> None:
        await tx.run(PaginationDatabase.DELETE_QUERY, pagination_id=pagination_id)

    async def delete(self, pagination_id: str) -> None:
        async with self._db.get_session() as session:
            await session.execute_write(lambda tx: PaginationDatabase.delete_with_transaction(tx, pagination_id))

    @staticmethod
    async def delete_all_with_transaction(tx: AsyncManagedTransaction, edition_id: str) -> None:
        await tx.run(PaginationDatabase.DELETE_ALL_QUERY, edition_id=edition_id)
