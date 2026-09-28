from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from database.database import Database


class AttributeDatabase:
    def __init__(self, db: Database) -> None:
        self._db = db
