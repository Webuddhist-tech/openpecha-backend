from typing import TYPE_CHECKING, LiteralString

from identifier import generate_id

from .database_validator import DatabaseValidator

if TYPE_CHECKING:
    from neo4j import AsyncManagedTransaction

    from .database import Database


class NomenDatabase:
    CREATE_QUERY: LiteralString = """
    OPTIONAL MATCH (primary:Nomen {id: $primary_nomen_id})
    CREATE (n:Nomen {id: $nomen_id})
    WITH n, primary
    CALL (*) {
        WHEN primary IS NOT NULL THEN { CREATE (n)-[:ALTERNATIVE_OF]->(primary) }
    }
    WITH n
    CALL (n) {
        UNWIND $localized_texts AS lt
        MATCH (l:Language {code: lt.base_lang_code})
        CREATE (n)-[:HAS_LOCALIZATION]->(locText:LocalizedText {text: lt.text})
            -[:HAS_LANGUAGE {bcp47: lt.bcp47_tag}]->(l)
        RETURN count(*) AS _
    }
    RETURN n.id as nomen_id
    """

    def __init__(self, db: Database) -> None:
        self._db = db

    @staticmethod
    async def create_with_transaction(
        tx: AsyncManagedTransaction, primary_text: dict[str, str], alternative_texts: list[dict[str, str]] | None = None
    ) -> str:
        base_codes = {tag.split("-")[0].lower() for tag in primary_text}
        for alt_text in alternative_texts or []:
            base_codes.update(tag.split("-")[0].lower() for tag in alt_text)
        await DatabaseValidator.validate_language_codes_exist(tx, list(base_codes))

        primary_localized_texts = [
            {
                "base_lang_code": bcp47_tag.split("-")[0].lower(),
                "bcp47_tag": bcp47_tag,
                "text": text,
            }
            for bcp47_tag, text in primary_text.items()
        ]

        primary_nomen_id = generate_id()
        result = await tx.run(
            NomenDatabase.CREATE_QUERY,
            nomen_id=primary_nomen_id,
            primary_nomen_id=None,
            localized_texts=primary_localized_texts,
        )
        record = await result.single(strict=True)
        created_primary_id = str(record["nomen_id"])

        for alt_text in alternative_texts or []:
            localized_texts = [
                {
                    "base_lang_code": bcp47_tag.split("-")[0].lower(),
                    "bcp47_tag": bcp47_tag,
                    "text": text,
                }
                for bcp47_tag, text in alt_text.items()
            ]

            alternative_result = await tx.run(
                NomenDatabase.CREATE_QUERY,
                nomen_id=generate_id(),
                primary_nomen_id=created_primary_id,
                localized_texts=localized_texts,
            )
            await alternative_result.single(strict=True)

        return created_primary_id
