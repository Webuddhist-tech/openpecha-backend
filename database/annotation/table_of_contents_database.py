from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, LiteralString

from database.database_validator import DatabaseValidator
from database.nomen_database import NomenDatabase
from exceptions import DataNotFoundError
from identifier import generate_id
from models.annotation import (
    TableOfContentsInput,
    TableOfContentsOutput,
    TableOfContentsSectionInput,
    TableOfContentsSectionOutput,
)

if TYPE_CHECKING:
    from neo4j import AsyncManagedTransaction, Record

    from database.database import Database


class TableOfContentsDatabase:
    CREATE_TOC_QUERY: LiteralString = """
    MATCH (edition:Edition {id: $edition_id})
    CREATE (toc:TableOfContents {id: $toc_id})-[:TOC_OF]->(edition)
    WITH toc
    CALL (*) {
        WHEN $metadata_id IS NOT NULL THEN {
            CREATE (metadata:AnnotationMetadata {id: $metadata_id, name: $metadata_name})
            CREATE (toc)-[:HAS_METADATA]->(metadata)
        }
    }
    RETURN toc.id AS id
    """

    CREATE_SECTIONS_QUERY: LiteralString = """
    MATCH (toc:TableOfContents {id: $toc_id})
    UNWIND $sections AS section_data
    MATCH (title:Nomen {id: section_data.title_nomen_id})
    OPTIONAL MATCH (summary:Nomen {id: section_data.summary_nomen_id})
    CREATE (section:TableOfContentsSection {id: section_data.id})-[:SECTION_OF]->(toc)
    CREATE (section)-[:HAS_TITLE]->(title)
    CREATE (:Span {start: section_data.span_start, end: section_data.span_end})-[:SPAN_OF]->(section)
    WITH section, summary
    CALL (*) {
        WHEN summary IS NOT NULL THEN {
            CREATE (section)-[:HAS_SUMMARY]->(summary)
        }
    }
    RETURN count(section) AS count
    """

    CREATE_HIERARCHY_QUERY: LiteralString = """
    UNWIND $sections AS section_data
    WITH section_data
    WHERE section_data.parent_id IS NOT NULL
    MATCH (section:TableOfContentsSection {id: section_data.id})
    MATCH (parent:TableOfContentsSection {id: section_data.parent_id})
    CREATE (section)-[:SUBSECTION_OF]->(parent)
    RETURN count(section) AS count
    """

    GET_BY_ID_QUERY: LiteralString = """
    MATCH (toc:TableOfContents {id: $toc_id})-[:TOC_OF]->(edition:Edition)-[:EDITION_OF]->(text:Text)
    OPTIONAL MATCH (toc)-[:HAS_METADATA]->(metadata:AnnotationMetadata)
    RETURN {
        id: toc.id,
        edition_id: edition.id,
        text_id: text.id,
        metadata: CASE WHEN metadata IS NULL THEN null ELSE {name: metadata.name} END
    } AS toc
    """

    GET_BY_EDITION_ID_QUERY: LiteralString = """
    MATCH (edition:Edition {id: $edition_id})-[:EDITION_OF]->(text:Text)
    MATCH (toc:TableOfContents)-[:TOC_OF]->(edition)
    OPTIONAL MATCH (toc)-[:HAS_METADATA]->(metadata:AnnotationMetadata)
    RETURN {
        id: toc.id,
        edition_id: edition.id,
        text_id: text.id,
        metadata: CASE WHEN metadata IS NULL THEN null ELSE {name: metadata.name} END
    } AS toc
    ORDER BY toc.id
    """

    GET_SECTIONS_QUERY: LiteralString = """
    MATCH (section:TableOfContentsSection)-[:SECTION_OF]->(:TableOfContents {id: $toc_id})
    MATCH (span:Span)-[:SPAN_OF]->(section)
    OPTIONAL MATCH (section)-[:SUBSECTION_OF]->(parent:TableOfContentsSection)
    WITH section, parent, span,
           apoc.map.fromPairs([
               (section)-[:HAS_TITLE]->(:Nomen)-[:HAS_LOCALIZATION]->(title:LocalizedText)
                   -[title_rel:HAS_LANGUAGE]->(title_lang:Language) |
               [coalesce(title_rel.bcp47, title_lang.code), title.text]
           ]) AS title,
           apoc.map.fromPairs([
               (section)-[:HAS_SUMMARY]->(:Nomen)-[:HAS_LOCALIZATION]->(summary:LocalizedText)
                   -[summary_rel:HAS_LANGUAGE]->(summary_lang:Language) |
               [coalesce(summary_rel.bcp47, summary_lang.code), summary.text]
           ]) AS summary
    RETURN {
        id: section.id,
        title: title,
        summary: CASE WHEN size(keys(summary)) = 0 THEN null ELSE summary END,
        span: {start: span.start, end: span.end}
    } AS section,
    parent.id AS parent_id
    ORDER BY parent_id, section.span.start, section.span.end, section.id
    """

    DELETE_QUERY: LiteralString = """
    MATCH (toc:TableOfContents {id: $toc_id})
    OPTIONAL MATCH (toc)-[:HAS_METADATA]->(metadata:AnnotationMetadata)
    OPTIONAL MATCH (section:TableOfContentsSection)-[:SECTION_OF]->(toc)
    OPTIONAL MATCH (span:Span)-[:SPAN_OF]->(section)
    OPTIONAL MATCH (section)-[:HAS_TITLE|HAS_SUMMARY]->(nomen:Nomen)
    OPTIONAL MATCH (nomen)-[:HAS_LOCALIZATION]->(localized:LocalizedText)
    DETACH DELETE span, localized, nomen, section, metadata, toc
    FINISH
    """

    DELETE_ALL_QUERY: LiteralString = """
    MATCH (toc:TableOfContents)-[:TOC_OF]->(:Edition {id: $edition_id})
    OPTIONAL MATCH (toc)-[:HAS_METADATA]->(metadata:AnnotationMetadata)
    OPTIONAL MATCH (section:TableOfContentsSection)-[:SECTION_OF]->(toc)
    OPTIONAL MATCH (span:Span)-[:SPAN_OF]->(section)
    OPTIONAL MATCH (section)-[:HAS_TITLE|HAS_SUMMARY]->(nomen:Nomen)
    OPTIONAL MATCH (nomen)-[:HAS_LOCALIZATION]->(localized:LocalizedText)
    DETACH DELETE span, localized, nomen, section, metadata, toc
    FINISH
    """

    def __init__(self, db: Database) -> None:
        self._db = db

    @staticmethod
    async def _flatten_sections(
        tx: AsyncManagedTransaction,
        sections: list[TableOfContentsSectionInput],
        *,
        parent_id: str | None = None,
    ) -> list[dict[str, str | int | None]]:
        flattened: list[dict[str, str | int | None]] = []
        for section in sections:
            section_id = generate_id()
            title_nomen_id = await NomenDatabase.create_with_transaction(tx, section.title.root, None)
            summary_nomen_id = (
                await NomenDatabase.create_with_transaction(tx, section.summary.root, None)
                if section.summary is not None
                else None
            )
            flattened.append(
                {
                    "id": section_id,
                    "parent_id": parent_id,
                    "title_nomen_id": title_nomen_id,
                    "summary_nomen_id": summary_nomen_id,
                    "span_start": section.span.start,
                    "span_end": section.span.end,
                }
            )
            flattened.extend(
                await TableOfContentsDatabase._flatten_sections(tx, section.subsections, parent_id=section_id)
            )
        return flattened

    @staticmethod
    def _build_sections(records: Sequence[dict[str, Any] | Record]) -> list[TableOfContentsSectionOutput]:
        nodes: dict[str, TableOfContentsSectionOutput] = {}
        parent_ids: dict[str, str | None] = {}
        spans: dict[str, tuple[int, int]] = {}

        for record in records:
            node = TableOfContentsSectionOutput.model_validate(record["section"])
            nodes[node.id] = node
            parent_ids[node.id] = record["parent_id"]
            spans[node.id] = (node.span.start, node.span.end)

        roots: list[TableOfContentsSectionOutput] = []
        for node_id, node in nodes.items():
            parent_id = parent_ids[node_id]
            if parent_id and parent_id in nodes:
                nodes[parent_id].subsections.append(node)
            else:
                roots.append(node)

        for node in nodes.values():
            node.subsections.sort(key=lambda item: (*spans[item.id], item.id))
        roots.sort(key=lambda item: (*spans[item.id], item.id))
        return roots

    @staticmethod
    async def _build_toc_output(tx: AsyncManagedTransaction, record: dict[str, Any] | Record) -> TableOfContentsOutput:
        toc_data = dict(record["toc"])
        result = await tx.run(TableOfContentsDatabase.GET_SECTIONS_QUERY, toc_id=toc_data["id"])
        sections = TableOfContentsDatabase._build_sections(await result.data())
        return TableOfContentsOutput.model_validate(toc_data | {"sections": sections})

    async def get(self, toc_id: str) -> TableOfContentsOutput:
        async with self._db.get_session() as session:
            return await session.execute_read(lambda tx: TableOfContentsDatabase.get_with_transaction(tx, toc_id))

    async def get_all(self, edition_id: str) -> list[TableOfContentsOutput]:
        async with self._db.get_session() as session:
            return await session.execute_read(
                lambda tx: TableOfContentsDatabase.get_all_with_transaction(tx, edition_id)
            )

    async def add(self, edition_id: str, toc: TableOfContentsInput) -> str:
        async with self._db.get_session() as session:
            return await session.execute_write(
                lambda tx: TableOfContentsDatabase.add_with_transaction(tx, edition_id, toc)
            )

    async def delete(self, toc_id: str) -> None:
        async with self._db.get_session() as session:
            await session.execute_write(lambda tx: TableOfContentsDatabase.delete_with_transaction(tx, toc_id))

    @staticmethod
    async def get_with_transaction(tx: AsyncManagedTransaction, toc_id: str) -> TableOfContentsOutput:
        result = await tx.run(TableOfContentsDatabase.GET_BY_ID_QUERY, toc_id=toc_id)
        record = await result.single()
        if record is None:
            raise DataNotFoundError(f"Table of contents with ID '{toc_id}' not found")
        return await TableOfContentsDatabase._build_toc_output(tx, record)

    @staticmethod
    async def get_all_with_transaction(tx: AsyncManagedTransaction, edition_id: str) -> list[TableOfContentsOutput]:
        await DatabaseValidator.validate_edition_exists(tx, edition_id)
        result = await tx.run(TableOfContentsDatabase.GET_BY_EDITION_ID_QUERY, edition_id=edition_id)
        return [await TableOfContentsDatabase._build_toc_output(tx, record) for record in await result.data()]

    @staticmethod
    async def add_with_transaction(
        tx: AsyncManagedTransaction,
        edition_id: str,
        toc: TableOfContentsInput,
    ) -> str:
        await DatabaseValidator.validate_edition_spans(tx, edition_id, toc.max_end)

        toc_id = generate_id()
        metadata_id = generate_id() if toc.metadata is not None else None
        metadata_name = toc.metadata.name if toc.metadata is not None else None
        sections = await TableOfContentsDatabase._flatten_sections(tx, toc.sections)

        result = await tx.run(
            TableOfContentsDatabase.CREATE_TOC_QUERY,
            edition_id=edition_id,
            toc_id=toc_id,
            metadata_id=metadata_id,
            metadata_name=metadata_name,
        )
        record = await result.single(strict=True)

        sections_result = await tx.run(TableOfContentsDatabase.CREATE_SECTIONS_QUERY, toc_id=toc_id, sections=sections)
        sections_record = await sections_result.single(strict=True)
        if sections_record["count"] != len(sections):
            raise DataNotFoundError(f"Failed to create table of contents sections for table of contents '{toc_id}'")

        hierarchy_result = await tx.run(TableOfContentsDatabase.CREATE_HIERARCHY_QUERY, sections=sections)
        hierarchy_record = await hierarchy_result.single(strict=True)
        expected_hierarchy_count = sum(section["parent_id"] is not None for section in sections)
        if hierarchy_record["count"] != expected_hierarchy_count:
            raise DataNotFoundError(f"Failed to create table of contents hierarchy for table of contents '{toc_id}'")

        return str(record["id"])

    @staticmethod
    async def delete_with_transaction(tx: AsyncManagedTransaction, toc_id: str) -> None:
        await tx.run(TableOfContentsDatabase.DELETE_QUERY, toc_id=toc_id)

    @staticmethod
    async def delete_all_with_transaction(tx: AsyncManagedTransaction, edition_id: str) -> None:
        await tx.run(TableOfContentsDatabase.DELETE_ALL_QUERY, edition_id=edition_id)
