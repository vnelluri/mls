from fastapi import APIRouter, Depends

from app.auth.dependencies import get_current_user
from app.schemas.common import CurrentUser

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/me", response_model=CurrentUser)
def read_me(current_user: CurrentUser = Depends(get_current_user)):
    return current_user
