from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Depends, Path, status

from dependencies import get_api_key, get_db
from models.annotation import MarkOutput

if TYPE_CHECKING:
    from database import Database

router = APIRouter(prefix="/v2/yigchungs", tags=["Annotations"])


@router.get(
    "/{yigchung_id}",
    summary="Get yigchung annotation",
    description="Retrieve a yigchung mark annotation by ID.",
)
async def get_yigchung(
    yigchung_id: Annotated[str, Path(description="The ID of the yigchung annotation")],
    _api_key: Annotated[str, Depends(get_api_key)],
    db: Annotated[Database, Depends(get_db)],
) -> MarkOutput:
    return await db.annotation.mark.get(yigchung_id)


@router.delete(
    "/{yigchung_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete yigchung annotation",
    description="Delete a yigchung mark annotation.",
)
async def delete_yigchung(
    yigchung_id: Annotated[str, Path(description="The ID of the yigchung annotation")],
    _api_key: Annotated[str, Depends(get_api_key)],
    db: Annotated[Database, Depends(get_db)],
) -> None:
    await db.annotation.mark.delete(yigchung_id)
