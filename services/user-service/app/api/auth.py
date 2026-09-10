import structlog
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import verify_password, create_access_token
from app.core.exceptions import InvalidCredentialsException
from app.models.user import User

log = structlog.get_logger()
router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    email: str
    password: str


@router.post("/login")
def login(data: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == data.email, User.is_active == True).first()
    if not user or not verify_password(data.password, user.password_hash):
        log.warning("login_failed", email=data.email)
        raise InvalidCredentialsException("Invalid email or password")

    token = create_access_token(subject=user.user_id)
    log.info("login_success", user_id=user.user_id)
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {"user_id": user.user_id, "name": user.name, "email": user.email},
    }
