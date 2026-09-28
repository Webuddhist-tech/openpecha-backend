from typing import TYPE_CHECKING, LiteralString

from exceptions import DataNotFoundError, DataValidationError
from identifier import generate_id
from models.tag import TagOutput

from .nomen_database import NomenDatabase

if TYPE_CHECKING:
    from neo4j import AsyncManagedTransaction, AsyncSession

    from models.tag import TagInput

    from .database import Database


class TagDatabase:
    GET_ALL_QUERY: LiteralString = """
    MATCH (t:Tag)-[:BELONGS_TO]->(:Application {id: $application})
    RETURN {
        id: t.id,
        title: apoc.map.fromPairs([(t)-[:HAS_TITLE]->(n:Nomen)-[:HAS_LOCALIZATION]->(lt:LocalizedText)
            -[:HAS_LANGUAGE]->(l:Language) | [l.code, lt.text]]),
        description: CASE WHEN EXISTS {
            (t)-[:HAS_DESCRIPTION]->(:Nomen)-[:HAS_LOCALIZATION]->(:LocalizedText)
        } THEN apoc.map.fromPairs([(t)-[:HAS_DESCRIPTION]->(dn:Nomen)-[:HAS_LOCALIZATION]->(dlt:LocalizedText)
            -[:HAS_LANGUAGE]->(dl:Language) | [dl.code, dlt.text]]) ELSE null END
    } AS tag
    """

    CREATE_QUERY: LiteralString = """
        MATCH (n:Nomen {id: $nomen_id})
        MATCH (app:Application {id: $application})
        CREATE (t:Tag {id: $tag_id})
        CREATE (t)-[:HAS_TITLE]->(n)
        CREATE (t)-[:BELONGS_TO]->(app)
        WITH t
        OPTIONAL MATCH (desc_nomen:Nomen {id: $description_nomen_id})
        WITH t, desc_nomen
        CALL (*) { WHEN desc_nomen IS NOT NULL THEN { CREATE (t)-[:HAS_DESCRIPTION]->(desc_nomen) } }
        RETURN t.id AS tag_id
    """

    FIND_EXISTING_QUERY: LiteralString = """
        UNWIND $titles AS title
        MATCH (t:Tag)-[:BELONGS_TO]->(app:Application {id: $application})
        MATCH (t)-[:HAS_TITLE]->(:Nomen)-[:HAS_LOCALIZATION]->(lt:LocalizedText)
            -[r:HAS_LANGUAGE]->(lang:Language)
        WHERE coalesce(r.bcp47, lang.code) = title.language
          AND toLower(lt.text) = toLower(title.text)
        RETURN title.language AS language, title.text AS title_text, t.id AS tag_id
        LIMIT 1
    """

    DELETE_QUERY: LiteralString = """
        MATCH (t:Tag {id: $tag_id})-[:BELONGS_TO]->(app:Application {id: $application})
        WITH t, t.id AS deleted_tag_id
        OPTIONAL MATCH (t)-[:HAS_TITLE]->(title_nomen:Nomen)
        OPTIONAL MATCH (title_nomen)-[:HAS_LOCALIZATION]->(title_lt:LocalizedText)
        OPTIONAL MATCH (t)-[:HAS_DESCRIPTION]->(desc_nomen:Nomen)
        OPTIONAL MATCH (desc_nomen)-[:HAS_LOCALIZATION]->(desc_lt:LocalizedText)
        DETACH DELETE t, title_nomen, title_lt, desc_nomen, desc_lt
        RETURN deleted_tag_id
    """

    TAG_WORK_QUERY: LiteralString = """
        MATCH (w:Work {id: $work_id})
        MATCH (t:Tag {id: $tag_id})
        MERGE (w)-[:HAS_TAG]->(t)
        RETURN w.id AS work_id
    """

    UNTAG_WORK_QUERY: LiteralString = """
        MATCH (w:Work {id: $work_id})-[r:HAS_TAG]->(t:Tag {id: $tag_id})
        DELETE r
        RETURN w.id AS work_id
    """

    TAG_SEGMENT_QUERY: LiteralString = """
        MATCH (s:Segment {id: $segment_id})
        MATCH (t:Tag {id: $tag_id})
        MERGE (s)-[:HAS_TAG]->(t)
        RETURN s.id AS segment_id
    """

    UNTAG_SEGMENT_QUERY: LiteralString = """
        MATCH (s:Segment {id: $segment_id})-[r:HAS_TAG]->(t:Tag {id: $tag_id})
        DELETE r
        RETURN s.id AS segment_id
    """

    def __init__(self, db: Database) -> None:
        self._db = db

    @property
    def session(self) -> AsyncSession:
        return self._db.get_session()

    async def get_all(self, application: str) -> list[TagOutput]:
        async def read(tx: AsyncManagedTransaction) -> list[TagOutput]:
            result = await tx.run(TagDatabase.GET_ALL_QUERY, application=application)
            return [TagOutput.model_validate(record["tag"]) for record in await result.data()]

        async with self.session as session:
            return await session.execute_read(read)

    async def create(self, tag: TagInput, application: str) -> str:
        async def create_transaction(tx: AsyncManagedTransaction) -> str:
            await self._validate_not_exists_tx(tx, application, tag.title.root)

            tag_id = generate_id()
            nomen_id = await NomenDatabase.create_with_transaction(tx, tag.title.root, None)
            description_nomen_id = None
            if tag.description is not None:
                description_nomen_id = await NomenDatabase.create_with_transaction(tx, tag.description.root, None)

            result = await tx.run(
                TagDatabase.CREATE_QUERY,
                tag_id=tag_id,
                application=application,
                nomen_id=nomen_id,
                description_nomen_id=description_nomen_id,
            )
            record = await result.single(strict=True)
            return record["tag_id"]

        async with self.session as session:
            return str(await session.execute_write(create_transaction))

    async def delete(self, tag_id: str, application: str) -> None:
        async def write(tx: AsyncManagedTransaction) -> None:
            result = await tx.run(TagDatabase.DELETE_QUERY, tag_id=tag_id, application=application)
            record = await result.single()
            if record is None:
                raise DataNotFoundError(f"Tag with ID '{tag_id}' not found in application '{application}'")

        async with self.session as session:
            await session.execute_write(write)

    async def tag_work(self, work_id: str, tag_id: str) -> None:
        async def write(tx: AsyncManagedTransaction) -> None:
            result = await tx.run(TagDatabase.TAG_WORK_QUERY, work_id=work_id, tag_id=tag_id)
            if not await result.single():
                raise DataNotFoundError(f"Work '{work_id}' or Tag '{tag_id}' not found")

        async with self.session as session:
            await session.execute_write(write)

    async def untag_work(self, work_id: str, tag_id: str) -> None:
        async def write(tx: AsyncManagedTransaction) -> None:
            result = await tx.run(TagDatabase.UNTAG_WORK_QUERY, work_id=work_id, tag_id=tag_id)
            if not await result.single():
                raise DataNotFoundError(f"Tag '{tag_id}' is not attached to Work '{work_id}'")

        async with self.session as session:
            await session.execute_write(write)

    async def tag_segment(self, segment_id: str, tag_id: str) -> None:
        async def write(tx: AsyncManagedTransaction) -> None:
            result = await tx.run(TagDatabase.TAG_SEGMENT_QUERY, segment_id=segment_id, tag_id=tag_id)
            if not await result.single():
                raise DataNotFoundError(f"Segment '{segment_id}' or Tag '{tag_id}' not found")

        async with self.session as session:
            await session.execute_write(write)

    async def untag_segment(self, segment_id: str, tag_id: str) -> None:
        async def write(tx: AsyncManagedTransaction) -> None:
            result = await tx.run(TagDatabase.UNTAG_SEGMENT_QUERY, segment_id=segment_id, tag_id=tag_id)
            if not await result.single():
                raise DataNotFoundError(f"Tag '{tag_id}' is not attached to Segment '{segment_id}'")

        async with self.session as session:
            await session.execute_write(write)

    @staticmethod
    async def tag_work_with_transaction(tx: AsyncManagedTransaction, work_id: str, tag_id: str) -> None:
        result = await tx.run(
            TagDatabase.TAG_WORK_QUERY,
            work_id=work_id,
            tag_id=tag_id,
        )
        record = await result.single()
        if not record:
            raise DataNotFoundError(f"Work '{work_id}' or Tag '{tag_id}' not found")

    async def _validate_not_exists_tx(
        self, tx: AsyncManagedTransaction, application: str, title: dict[str, str]
    ) -> None:
        result = await tx.run(
            TagDatabase.FIND_EXISTING_QUERY,
            application=application,
            titles=[{"language": language, "text": title_text} for language, title_text in title.items()],
        )
        record = await result.single()
        if record:
            raise DataValidationError(
                f"Tag with title '{record['title_text']}' in language '{record['language']}' "
                f"already exists for application '{application}'"
            )
