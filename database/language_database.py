from typing import TYPE_CHECKING, LiteralString

from neo4j.exceptions import ConstraintError

from exceptions import DataConflictError, DataNotFoundError, DataValidationError
from models.responses import LanguageResponse

if TYPE_CHECKING:
    from neo4j import AsyncManagedTransaction, AsyncSession

    from .database import Database


class LanguageDatabase:
    GET_ALL_QUERY: LiteralString = """
    MATCH (l:Language)
    RETURN l.code AS code, l.name AS name
    ORDER BY l.code
    """

    GET_QUERY: LiteralString = """
    MATCH (l:Language {code: $code})
    RETURN l.code AS code, l.name AS name
    """

    CREATE_QUERY: LiteralString = """
    CREATE (l:Language {code: $code, name: $name})
    RETURN l.code AS code
    """

    DELETE_CHECK_QUERY: LiteralString = """
    MATCH (l:Language {code: $code})
    RETURN count { ()-[:HAS_LANGUAGE]->(l) } AS reference_count
    """

    DELETE_QUERY: LiteralString = """
    MATCH (l:Language {code: $code})
    DELETE l
    RETURN $code AS code
    """

    def __init__(self, db: Database) -> None:
        self._db = db

    @property
    def session(self) -> AsyncSession:
        return self._db.get_session()

    async def get_all(self) -> list[LanguageResponse]:
        async def read(tx: AsyncManagedTransaction) -> list[LanguageResponse]:
            result = await tx.run(LanguageDatabase.GET_ALL_QUERY)
            return [LanguageResponse(code=r["code"], name=r["name"]) for r in await result.data()]

        async with self.session as session:
            return await session.execute_read(read)

    async def create(self, code: str, name: str) -> str:
        async def write(tx: AsyncManagedTransaction) -> str:
            result = await tx.run(LanguageDatabase.CREATE_QUERY, code=code, name=name)
            record = await result.single(strict=True)
            return str(record["code"])

        try:
            async with self.session as session:
                return await session.execute_write(write)
        except ConstraintError as err:
            raise DataValidationError(f"Language with code '{code}' already exists") from err

    async def delete(self, code: str) -> None:
        async def write(tx: AsyncManagedTransaction) -> None:
            result = await tx.run(LanguageDatabase.DELETE_CHECK_QUERY, code=code)
            record = await result.single()
            if record is None:
                raise DataNotFoundError(f"Language with code '{code}' not found")
            if record["reference_count"] > 0:
                raise DataConflictError(
                    f"Language '{code}' is referenced by {record['reference_count']} HAS_LANGUAGE relationship(s)"
                )

            await tx.run(LanguageDatabase.DELETE_QUERY, code=code)

        async with self.session as session:
            await session.execute_write(write)
