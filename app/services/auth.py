from datetime import datetime, timedelta

from jose import jwt
from passlib.context import CryptContext
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.core.text_guard import normalize_email
from app.models.user import User

pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")
_DUMMY_HASH = pwd_context.hash("timing-equalizer")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(subject: str, role: str, employee_id: int | None = None, token_version: int = 0) -> str:
    expire = datetime.utcnow() + timedelta(minutes=settings.jwt_expire_minutes)
    payload = {
        "sub": subject.lower(),
        "role": role,
        "employee_id": employee_id,
        "tv": int(token_version or 0),
        "typ": "access",
        "iat": datetime.utcnow(),
        "exp": expire,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def authenticate_user(db: Session, email: str, password: str) -> User | None:
    normalized = normalize_email(email)
    user = (
        db.query(User)
        .filter(func.lower(User.email) == normalized, User.is_active.is_(True))
        .first()
    )
    if not user:
        verify_password(password, _DUMMY_HASH)
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user
