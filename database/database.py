from logging import getLogger
from typing import Self

from neo4j import AsyncDriver, AsyncGraphDatabase, AsyncSession

from .alignment_database import AlignmentDatabase
from .annotation.attribute_database import AttributeDatabase
from .annotation.bibliographic_database import BibliographicDatabase
from .annotation.mark_database import MarkDatabase
from .annotation.note_database import NoteDatabase
from .annotation.pagination_database import PaginationDatabase
from .annotation.segmentation_database import SegmentationDatabase
from .annotation.table_of_contents_database import TableOfContentsDatabase
from .api_key_database import ApiKeyDatabase
from .application_database import ApplicationDatabase
from .category_database import CategoryDatabase
from .edition_database import EditionDatabase
from .language_database import LanguageDatabase
from .person_database import PersonDatabase
from .recording_database import RecordingDatabase
from .segment_database import SegmentDatabase
from .span_database import SpanDatabase
from .tag_database import TagDatabase
from .text_database import TextDatabase

logger = getLogger(__name__)


class AnnotationDatabase:
    Segmentation = SegmentationDatabase
    Pagination = PaginationDatabase
    TableOfContents = TableOfContentsDatabase
    Note = NoteDatabase
    Bibliographic = BibliographicDatabase
    Mark = MarkDatabase
    Attribute = AttributeDatabase

    def __init__(self, db: Database) -> None:
        self._db = db
        self.segmentation = SegmentationDatabase(db)
        self.pagination = PaginationDatabase(db)
        self.table_of_contents = TableOfContentsDatabase(db)
        self.note = NoteDatabase(db)
        self.bibliographic = BibliographicDatabase(db)
        self.mark = MarkDatabase(db)
        self.attributes = AttributeDatabase(db)


class Database:
    """Async database class for Neo4j operations."""

    api_key: ApiKeyDatabase
    application: ApplicationDatabase
    text: TextDatabase
    edition: EditionDatabase
    annotation: AnnotationDatabase
    alignment: AlignmentDatabase
    segment: SegmentDatabase
    recording: RecordingDatabase
    person: PersonDatabase
    language: LanguageDatabase
    category: CategoryDatabase
    tag: TagDatabase
    span: SpanDatabase

    _driver: AsyncDriver

    def __init__(self, neo4j_uri: str, neo4j_auth: tuple[str, str], neo4j_database: str = "neo4j") -> None:
        self._driver = AsyncGraphDatabase.driver(neo4j_uri, auth=neo4j_auth)
        self._database = neo4j_database

        self.api_key = ApiKeyDatabase(db=self)
        self.application = ApplicationDatabase(db=self)
        self.text = TextDatabase(db=self)
        self.edition = EditionDatabase(db=self)
        self.annotation = AnnotationDatabase(db=self)
        self.alignment = AlignmentDatabase(db=self)
        self.segment = SegmentDatabase(db=self)
        self.recording = RecordingDatabase(db=self)
        self.person = PersonDatabase(db=self)
        self.language = LanguageDatabase(db=self)
        self.category = CategoryDatabase(db=self)
        self.tag = TagDatabase(db=self)
        self.span = SpanDatabase(db=self)

    async def verify_connectivity(self) -> None:
        await self._driver.verify_connectivity()
        logger.info("Async connection to neo4j established.")

    def get_session(self) -> AsyncSession:
        return self._driver.session(database=self._database)

    async def close(self) -> None:
        await self._driver.close()

    async def __aenter__(self) -> Self:
        await self.verify_connectivity()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        await self.close()
