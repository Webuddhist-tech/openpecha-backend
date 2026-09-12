import argparse
import asyncio
import logging
from typing import LiteralString

from neo4j import AsyncManagedTransaction

from config import settings
from content_search import ContentSearchService
from database import Database
from storage import Storage

GET_ALL_EDITION_IDS_QUERY: LiteralString = """
MATCH (m:Edition)
RETURN m.id AS edition_id
ORDER BY edition_id
"""

logger = logging.getLogger(__name__)


def _service() -> ContentSearchService:
    if not settings.opensearch_endpoint:
        raise ValueError("OPENSEARCH_ENDPOINT is required")
    return ContentSearchService(
        endpoint=settings.opensearch_endpoint,
        index_name=settings.opensearch_index,
        region=settings.aws_region,
        auth_mode=settings.opensearch_auth_mode,
        username=settings.opensearch_username,
        password=settings.opensearch_password,
    )


async def _reindex(edition_ids: list[str] | None) -> None:
    db = Database(
        neo4j_uri=settings.neo4j_uri,
        neo4j_auth=(settings.neo4j_username, settings.neo4j_password),
        neo4j_database=settings.neo4j_database,
    )
    storage = Storage(bucket_name=settings.aws_s3_bucket, region=settings.aws_region)
    search = _service()
    await db.verify_connectivity()
    await storage.connect()
    try:
        await search.connect()
        ids = edition_ids or await _get_all_edition_ids(db)
        if not edition_ids:
            logger.info("Clearing existing content search documents before full reindex")
            await search.delete_all_documents(refresh=False)
        total = len(ids)
        logger.info("Starting content search reindex for %d edition(s)", total)
        failed: list[str] = []
        for index, edition_id in enumerate(ids, start=1):
            logger.info("Reindexing edition %s (%d/%d)", edition_id, index, total)
            try:
                await search.index_edition(edition_id, db, storage, refresh=False)
            except Exception:
                failed.append(edition_id)
                logger.exception("Failed to reindex edition %s (%d/%d)", edition_id, index, total)
        logger.info("Refreshing content search index")
        await search.refresh_index()
        if failed:
            raise RuntimeError(f"Failed to reindex {len(failed)} edition(s): {', '.join(failed)}")
        logger.info("Finished content search reindex for %d edition(s)", total)
    finally:
        await search.close()
        await storage.close()
        await db.close()


async def _get_all_edition_ids(db: Database) -> list[str]:
    async def read(tx: AsyncManagedTransaction) -> list[str]:
        result = await tx.run(GET_ALL_EDITION_IDS_QUERY)
        return [record["edition_id"] for record in await result.data()]

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
        logger.warning("Deleting content search index %s", settings.opensearch_index)
        await search.delete_index()
        logger.info("Creating content search index %s", settings.opensearch_index)
        await search.setup_index()
    finally:
        await search.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage the OpenSearch content search index.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("setup-index", help="Create the content search index if it does not exist.")
    subparsers.add_parser("recreate-index", help="Delete and recreate the content search index.")
    reindex = subparsers.add_parser("reindex", help="Reindex editions into OpenSearch.")
    reindex.add_argument("edition_ids", nargs="*", help="Edition IDs to reindex. If omitted, reindex all editions.")

    args = parser.parse_args()
    if args.command == "setup-index":
        asyncio.run(_setup_index())
    elif args.command == "recreate-index":
        asyncio.run(_recreate_index())
    elif args.command == "reindex":
        asyncio.run(_reindex(args.edition_ids or None))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s - %(name)s - %(message)s")
    logging.getLogger("neo4j").setLevel(logging.WARNING)
    logging.getLogger("neo4j.notifications").setLevel(logging.ERROR)
    main()
