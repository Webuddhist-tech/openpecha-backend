"""Run all structural audit queries against the active Neo4j database.

Usage:
    python -m scripts.audit

Requires environment variables (via .env or shell):
    NEO4J_URI       — bolt://... or neo4j+s://...
    NEO4J_USERNAME  — default: neo4j
    NEO4J_PASSWORD
"""

import asyncio
import logging
import sys

from neo4j import AsyncGraphDatabase

from config import settings
from database.neo4j_triggers import audit_triggers

logger = logging.getLogger(__name__)


async def main() -> None:
    uri = settings.neo4j_uri
    username = settings.neo4j_username
    password = settings.neo4j_password

    if not uri or not password:
        logger.error("NEO4J_URI and NEO4J_PASSWORD must be set (via .env or environment)")
        sys.exit(1)

    driver = AsyncGraphDatabase.driver(uri, auth=(username, password))
    try:
        await driver.verify_connectivity()
        logger.info("Connected to %s", uri)

        violations = await audit_triggers(driver)

        if violations:
            logger.warning("Audit found %d violation(s):", len(violations))
            for trigger_name, ids in violations.items():
                preview = ", ".join(ids[:5])
                suffix = "…" if len(ids) > 5 else ""
                logger.warning("  %s: %d nodes — %s%s", trigger_name, len(ids), preview, suffix)
            sys.exit(1)
        else:
            logger.info("All audits passed — no violations found.")
    finally:
        await driver.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s - %(name)s - %(message)s")
    logging.getLogger("neo4j").setLevel(logging.ERROR)
    asyncio.run(main())
