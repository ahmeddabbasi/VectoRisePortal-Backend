from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.database import get_db
from app.models.user import User
from app.services.chat import ChatService

router = APIRouter(prefix="/api/chat", tags=["chat"])


class ConversationCreate(BaseModel):
    participant_user_ids: list[int] = Field(min_length=1)
    title: str | None = None


class DirectChatCreate(BaseModel):
    employee_id: int | None = None
    user_id: int | None = None


class MessageCreate(BaseModel):
    body: str = Field(min_length=1, max_length=5000)


@router.get("/conversations")
def list_conversations(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return ChatService(db).list_conversations(user.id)


@router.get("/unread-count")
def chat_unread_count(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return {"count": ChatService(db).unread_total(user.id)}


@router.post("/conversations")
def create_conversation(payload: ConversationCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    conv = ChatService(db).create_conversation(user, payload.participant_user_ids, payload.title)
    db.commit()
    return {"id": conv.id, "title": conv.title}


@router.post("/conversations/direct")
def start_direct_chat(payload: DirectChatCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    svc = ChatService(db)
    target_user_id = payload.user_id
    if payload.employee_id:
        target_user_id = svc.resolve_user_id_for_employee(payload.employee_id)
        if not target_user_id:
            raise HTTPException(status_code=404, detail="No user account linked to that employee")
    if not target_user_id:
        raise HTTPException(status_code=400, detail="user_id or employee_id required")
    conv = svc.find_or_create_direct(user.id, target_user_id)
    db.commit()
    return {"id": conv.id}


@router.get("/conversations/{conversation_id}/messages")
def get_messages(conversation_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    svc = ChatService(db)
    messages = svc.list_messages(conversation_id, user.id)
    svc.mark_read(conversation_id, user.id)
    db.commit()
    return messages


@router.post("/conversations/{conversation_id}/messages")
def send_message(conversation_id: int, payload: MessageCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    msg = ChatService(db).send_message(conversation_id, user, payload.body)
    db.commit()
    return {"id": msg.id, "created_at": msg.created_at.isoformat()}


@router.get("/users")
def list_chat_users(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.models.employee import Employee

    rows = db.query(User).filter(User.is_active.is_(True), User.id != user.id).all()
    employees = {e.id: e.name for e in db.query(Employee).all()}
    return [
        {
            "user_id": u.id,
            "email": u.email,
            "role": u.role,
            "name": employees.get(u.employee_id) if u.employee_id else u.email,
            "employee_id": u.employee_id,
        }
        for u in rows
    ]
