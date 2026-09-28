"""Backfill Edition.content_length from the base texts stored in S3.

Editions created before content_length existed have no value for it, and span
validation requires one. Run this to completion before deploying.

Usage:
    python -m scripts.backfill_content_length [--dry-run]

Requires environment variables (via .env or shell):
    NEO4J_URI       — bolt://... or neo4j+s://...
    NEO4J_USERNAME  — default: neo4j
    NEO4J_PASSWORD
    AWS_S3_BUCKET
    AWS_REGION
"""

import argparse
import asyncio
import logging
import sys

from neo4j import AsyncGraphDatabase

from config import settings
from exceptions import DataNotFoundError
from storage import Storage

logger = logging.getLogger(__name__)

FIND_EDITIONS_QUERY = """
MATCH (m:Edition)-[:EDITION_OF]->(e:Text)
WHERE m.content_length IS NULL
RETURN m.id AS edition_id, e.id AS text_id
ORDER BY m.id
"""

SET_CONTENT_LENGTH_QUERY = """
MATCH (m:Edition {id: $edition_id})
SET m.content_length = $content_length
FINISH
"""


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Report what would change without writing")
    args = parser.parse_args()

    if not settings.neo4j_uri or not settings.neo4j_password:
        logger.error("NEO4J_URI and NEO4J_PASSWORD must be set (via .env or environment)")
        sys.exit(1)

    if not settings.aws_s3_bucket or not settings.aws_region:
        logger.error("AWS_S3_BUCKET and AWS_REGION must be set (via .env or environment)")
        sys.exit(1)

    driver = AsyncGraphDatabase.driver(settings.neo4j_uri, auth=(settings.neo4j_username, settings.neo4j_password))
    storage = Storage(bucket_name=settings.aws_s3_bucket, region=settings.aws_region)
    await storage.connect()

    missing: list[str] = []
    updated = 0

    try:
        await driver.verify_connectivity()
        logger.info("Connected to %s", settings.neo4j_uri)

        async with driver.session(database=settings.neo4j_database) as session:
            result = await session.run(FIND_EDITIONS_QUERY)
            editions = await result.data()

        logger.info("Found %d edition(s) without content_length", len(editions))

        for edition in editions:
            edition_id = edition["edition_id"]
            try:
                base_text = await storage.retrieve_base_text(text_id=edition["text_id"], edition_id=edition_id)
            except DataNotFoundError:
                logger.warning("No base text in S3 for edition %s", edition_id)
                missing.append(edition_id)
                continue

            content_length = len(base_text)
            if args.dry_run:
                logger.info("Would set %s content_length=%d", edition_id, content_length)
                continue

            async with driver.session(database=settings.neo4j_database) as session:
                await session.run(SET_CONTENT_LENGTH_QUERY, edition_id=edition_id, content_length=content_length)
            updated += 1
            logger.info("Set %s content_length=%d", edition_id, content_length)
    finally:
        await storage.close()
        await driver.close()

    if missing:
        logger.error("Backfill incomplete: %d edition(s) have no base text in S3: %s", len(missing), ", ".join(missing))
        sys.exit(1)

    logger.info("Backfill complete: %d edition(s) updated", updated)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s - %(name)s - %(message)s")
    logging.getLogger("neo4j").setLevel(logging.ERROR)
    asyncio.run(main())
