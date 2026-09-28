import logging
from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Path, Query, status

from catalog_search import CatalogSearchService
from dependencies import get_api_key, get_catalog_search, get_db
from exceptions import ServiceUnavailableError
from models.person import PersonInput, PersonOutput, PersonPatch
from models.requests import PersonsQueryParams
from models.responses import IdResponse, PaginatedResponse

if TYPE_CHECKING:
    from database import Database

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v2/persons", tags=["Persons"])


@router.get(
    "/{person_id}",
    summary="Get a person",
    description="Retrieve a person by their ID.",
)
async def get_person(
    person_id: Annotated[str, Path(description="The ID of the person")],
    _api_key: Annotated[str, Depends(get_api_key)],
    db: Annotated[Database, Depends(get_db)],
) -> PersonOutput:
    """Fetch a person by ID."""
    return await db.person.get(person_id)


@router.get(
    "",
    summary="List all persons",
    description="Retrieve a paginated list of persons.",
)
async def get_all_persons(
    params: Annotated[PersonsQueryParams, Query()],
    _api_key: Annotated[str, Depends(get_api_key)],
    db: Annotated[Database, Depends(get_db)],
    catalog_search: Annotated[CatalogSearchService, Depends(get_catalog_search)],
) -> PaginatedResponse[PersonOutput]:
    """List all persons with optional filtering."""
    if params.name:
        if not catalog_search.available:
            raise ServiceUnavailableError("Catalog search is required for person name search")
        person_ids = await catalog_search.search_person_ids(
            query=params.name,
            filters=params,
            offset=params.offset,
            limit=params.limit + 1,
        )
        persons = await db.person.get_by_ids(person_ids)
        return PaginatedResponse.from_items(persons, offset=params.offset, limit=params.limit)

    persons = await db.person.get_all(offset=params.offset, limit=params.limit + 1, filters=params)
    return PaginatedResponse.from_items(persons, offset=params.offset, limit=params.limit)


@router.post(
    "",
    status_code=201,
    summary="Create a person",
    description="Create a new person.",
)
async def create_person(
    data: PersonInput,
    background_tasks: BackgroundTasks,
    _api_key: Annotated[str, Depends(get_api_key)],
    db: Annotated[Database, Depends(get_db)],
    catalog_search: Annotated[CatalogSearchService, Depends(get_catalog_search)],
) -> IdResponse:
    """Create a new person."""
    logger.info("Creating person: %s", data.model_dump_json())
    person_id = await db.person.create(data)
    if catalog_search.available:
        background_tasks.add_task(catalog_search.index_person, person_id, db)
    return IdResponse(id=person_id)


@router.patch(
    "/{person_id}",
    summary="Update a person",
    description="Partially update a person.",
)
async def update_person(
    person_id: Annotated[str, Path(description="The ID of the person")],
    data: PersonPatch,
    background_tasks: BackgroundTasks,
    _api_key: Annotated[str, Depends(get_api_key)],
    db: Annotated[Database, Depends(get_db)],
    catalog_search: Annotated[CatalogSearchService, Depends(get_catalog_search)],
) -> PersonOutput:
    """Update a person."""
    logger.info("Updating person %s with: %s", person_id, data.model_dump_json())
    person = await db.person.update(person_id, data)
    if catalog_search.available:
        background_tasks.add_task(catalog_search.index_person, person_id, db)
    return person


@router.delete(
    "/{person_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete person",
    description="Delete a person if they are not referenced by contributions.",
)
async def delete_person(
    person_id: Annotated[str, Path(description="The ID of the person")],
    background_tasks: BackgroundTasks,
    _api_key: Annotated[str, Depends(get_api_key)],
    db: Annotated[Database, Depends(get_db)],
    catalog_search: Annotated[CatalogSearchService, Depends(get_catalog_search)],
) -> None:
    """Delete a person."""
    await db.person.delete(person_id)
    if catalog_search.available:
        background_tasks.add_task(catalog_search.delete_person, person_id)
