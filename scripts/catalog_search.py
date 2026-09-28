import argparse
import asyncio
import logging
from typing import LiteralString

from neo4j import AsyncManagedTransaction

from catalog_search import CatalogSearchService
from config import settings
from database import Database

GET_ALL_PERSON_IDS_QUERY: LiteralString = """
MATCH (p:Person)
RETURN p.id AS person_id
ORDER BY person_id
"""

GET_ALL_TEXT_IDS_QUERY: LiteralString = """
MATCH (t:Text)
RETURN t.id AS text_id
ORDER BY text_id
"""

logger = logging.getLogger(__name__)


def _service() -> CatalogSearchService:
    if not settings.opensearch_endpoint:
        raise ValueError("OPENSEARCH_ENDPOINT is required")
    return CatalogSearchService(
        endpoint=settings.opensearch_endpoint,
        index_name=settings.opensearch_catalog_index,
        region=settings.aws_region,
        auth_mode=settings.opensearch_auth_mode,
        username=settings.opensearch_username,
        password=settings.opensearch_password,
    )


async def _reindex(person_ids: list[str] | None, text_ids: list[str] | None) -> None:
    db = Database(
        neo4j_uri=settings.neo4j_uri,
        neo4j_auth=(settings.neo4j_username, settings.neo4j_password),
        neo4j_database=settings.neo4j_database,
    )
    search = _service()
    await db.verify_connectivity()
    try:
        await search.connect()
        resolved_person_ids = person_ids or await _get_all_person_ids(db)
        resolved_text_ids = text_ids or await _get_all_text_ids(db)
        failed: list[str] = []

        logger.info("Starting catalog person reindex for %d person(s)", len(resolved_person_ids))
        for index, person_id in enumerate(resolved_person_ids, start=1):
            logger.info("Reindexing person %s (%d/%d)", person_id, index, len(resolved_person_ids))
            try:
                await search.index_person(person_id, db, refresh=False)
            except Exception:
                failed.append(f"person:{person_id}")
                logger.exception("Failed to reindex person %s", person_id)

        logger.info("Starting catalog text reindex for %d text(s)", len(resolved_text_ids))
        for index, text_id in enumerate(resolved_text_ids, start=1):
            logger.info("Reindexing text %s (%d/%d)", text_id, index, len(resolved_text_ids))
            try:
                await search.index_text(text_id, db, refresh=False)
            except Exception:
                failed.append(f"text:{text_id}")
                logger.exception("Failed to reindex text %s", text_id)

        logger.info("Refreshing catalog search index")
        await search.refresh_index()
        if failed:
            raise RuntimeError(f"Failed to reindex {len(failed)} catalog document(s): {', '.join(failed)}")
        logger.info(
            "Finished catalog search reindex for %d person(s) and %d text(s)",
            len(resolved_person_ids),
            len(resolved_text_ids),
        )
    finally:
        await search.close()
        await db.close()


async def _get_all_person_ids(db: Database) -> list[str]:
    async def read(tx: AsyncManagedTransaction) -> list[str]:
        result = await tx.run(GET_ALL_PERSON_IDS_QUERY)
        return [record["person_id"] for record in await result.data()]

    async with db.get_session() as session:
        return await session.execute_read(read)


async def _get_all_text_ids(db: Database) -> list[str]:
    async def read(tx: AsyncManagedTransaction) -> list[str]:
        result = await tx.run(GET_ALL_TEXT_IDS_QUERY)
        return [record["text_id"] for record in await result.data()]

    async with db.get_session() as session:
        return await session.execute_read(read)


async def _setup_index() -> None:
    search = _service()
    try:
        await search.connect()
    finally:
        await search.close()


async def _recreate_index() -> None:
    search = _service()
    try:
        await search.connect()
        logger.warning("Deleting catalog search index %s", settings.opensearch_catalog_index)
        await search.delete_index()
        logger.info("Creating catalog search index %s", settings.opensearch_catalog_index)
        await search.setup_index()
    finally:
        await search.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage the OpenSearch catalog search index.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("setup-index", help="Create the catalog search index if it does not exist.")
    subparsers.add_parser("recreate-index", help="Delete and recreate the catalog search index.")
    reindex = subparsers.add_parser("reindex", help="Reindex persons and texts into OpenSearch.")
    reindex.add_argument("--person-id", action="append", dest="person_ids", help="Person ID to reindex.")
    reindex.add_argument("--text-id", action="append", dest="text_ids", help="Text ID to reindex.")

    args = parser.parse_args()
    if args.command == "setup-index":
        asyncio.run(_setup_index())
    elif args.command == "recreate-index":
        asyncio.run(_recreate_index())
    elif args.command == "reindex":
        asyncio.run(_reindex(args.person_ids, args.text_ids))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s - %(name)s - %(message)s")
    logging.getLogger("neo4j").setLevel(logging.WARNING)
    logging.getLogger("neo4j.notifications").setLevel(logging.ERROR)
    main()
