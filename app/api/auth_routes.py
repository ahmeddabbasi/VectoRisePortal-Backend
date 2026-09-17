from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.database import get_db
from app.models.employee import Employee
from app.models.user import User
from app.schemas.hrm import LoginRequest, PasswordChange, TokenResponse, UserOut
from app.services.auth import authenticate_user, create_access_token, hash_password, verify_password
from app.services.audit import AuditService

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = authenticate_user(db, payload.email, payload.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    employee = db.get(Employee, user.employee_id) if user.employee_id else None
    AuditService(db).log("login", user)
    db.commit()
    return TokenResponse(
        access_token=create_access_token(user.email, user.role, user.employee_id),
        role=user.role,
        employee_id=user.employee_id,
        name=employee.name if employee else None,
        email=user.email,
    )


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    employee = db.get(Employee, user.employee_id) if user.employee_id else None
    return UserOut(
        id=user.id,
        email=user.email,
        role=user.role,
        employee_id=user.employee_id,
        is_active=user.is_active,
        name=employee.name if employee else None,
    )


@router.post("/change-password")
def change_password(payload: PasswordChange, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not verify_password(payload.current_password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    user.hashed_password = hash_password(payload.new_password)
    AuditService(db).log("password_changed", user)
    db.commit()
    return {"status": "ok"}
