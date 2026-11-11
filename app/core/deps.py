from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models.enums import UserRole
from app.models.user import User

bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    if not credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    try:
        payload = jwt.decode(credentials.credentials, settings.jwt_secret, algorithms=["HS256"])
        email = payload.get("sub")
        if not email or payload.get("typ") != "access":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
        token_version = int(payload.get("tv"))
    except (JWTError, TypeError, ValueError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    user = (
        db.query(User)
        .filter(func.lower(User.email) == str(email).lower(), User.is_active.is_(True))
        .first()
    )
    if not user or int(user.token_version or 0) != token_version:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != UserRole.ADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return user


def require_sales_access(user: User = Depends(get_current_user)) -> User:
    if user.role == UserRole.ADMIN or user.sales_access:
        return user
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Sales access required")


def require_task_review(user: User = Depends(get_current_user)) -> User:
    if user.role == UserRole.ADMIN or user.can_review_tasks:
        return user
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Task review access required")


def require_employee(user: User = Depends(get_current_user)) -> User:
    if user.role not in {UserRole.ADMIN, UserRole.EMPLOYEE}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    return user


def get_employee_scope(user: User) -> int | None:
    if user.role == UserRole.ADMIN:
        return None
    if not user.employee_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Employee profile not linked")
    return user.employee_id
