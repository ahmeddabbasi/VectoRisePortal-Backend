from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.chat import ChatConversation, ChatMessage, ChatParticipant
from app.models.employee import Employee
from app.models.user import User


class ChatService:
    def __init__(self, db: Session):
        self.db = db

    def _participant_ids(self, conversation_id: int) -> set[int]:
        rows = self.db.query(ChatParticipant.user_id).filter(ChatParticipant.conversation_id == conversation_id).all()
        return {r[0] for r in rows}

    def _ensure_member(self, conversation_id: int, user_id: int):
        if user_id not in self._participant_ids(conversation_id):
            raise HTTPException(status_code=403, detail="Not a conversation member")

    def list_conversations(self, user_id: int) -> list[dict]:
        conv_ids = [
            p.conversation_id
            for p in self.db.query(ChatParticipant).filter(ChatParticipant.user_id == user_id).all()
        ]
        if not conv_ids:
            return []

        conversations = (
            self.db.query(ChatConversation)
            .filter(ChatConversation.id.in_(conv_ids))
            .order_by(ChatConversation.updated_at.desc())
            .all()
        )

        participants = (
            self.db.query(ChatParticipant.conversation_id, ChatParticipant.user_id)
            .filter(ChatParticipant.conversation_id.in_(conv_ids))
            .all()
        )
        participants_by_conv: dict[int, set[int]] = {}
        user_ids: set[int] = set()
        for conv_id, uid in participants:
            participants_by_conv.setdefault(conv_id, set()).add(uid)
            user_ids.add(uid)

        users = {u.id: u for u in self.db.query(User).filter(User.id.in_(user_ids)).all()}
        employee_ids = {u.employee_id for u in users.values() if u.employee_id}
        employees = (
            {e.id: e.name for e in self.db.query(Employee).filter(Employee.id.in_(employee_ids)).all()}
            if employee_ids
            else {}
        )

        recent_msgs = (
            self.db.query(ChatMessage)
            .filter(ChatMessage.conversation_id.in_(conv_ids))
            .order_by(ChatMessage.conversation_id, ChatMessage.created_at.desc())
            .all()
        )
        last_msg_map: dict[int, ChatMessage] = {}
        for msg in recent_msgs:
            if msg.conversation_id not in last_msg_map:
                last_msg_map[msg.conversation_id] = msg

        unread_rows = (
            self.db.query(ChatMessage.conversation_id, func.count(ChatMessage.id))
            .filter(
                ChatMessage.conversation_id.in_(conv_ids),
                ChatMessage.sender_id != user_id,
                ChatMessage.read_at.is_(None),
            )
            .group_by(ChatMessage.conversation_id)
            .all()
        )
        unread_map = {cid: count for cid, count in unread_rows}

        result = []
        for conv in conversations:
            participant_ids = participants_by_conv.get(conv.id, set())
            last_msg = last_msg_map.get(conv.id)
            members = []
            for uid in participant_ids:
                u = users.get(uid)
                if not u:
                    continue
                name = employees.get(u.employee_id) if u.employee_id else u.email
                members.append({"user_id": uid, "name": name, "role": u.role})
            result.append(
                {
                    "id": conv.id,
                    "title": conv.title or self._direct_title(participant_ids, user_id, users, employees),
                    "participants": members,
                    "last_message": last_msg.body if last_msg else None,
                    "last_message_at": last_msg.created_at.isoformat() if last_msg else None,
                    "unread_count": unread_map.get(conv.id, 0),
                }
            )
        return result

    def _direct_title(self, participant_ids: set[int], current_user_id: int, users: dict, employees: dict) -> str:
        others = [uid for uid in participant_ids if uid != current_user_id]
        if len(others) == 1:
            u = users.get(others[0])
            if u and u.employee_id:
                return employees.get(u.employee_id, u.email)
            return u.email if u else "Conversation"
        return "Group chat"

    def create_conversation(self, creator: User, participant_user_ids: list[int], title: str | None = None) -> ChatConversation:
        unique_ids = sorted(set(participant_user_ids + [creator.id]))
        if len(unique_ids) < 2:
            raise HTTPException(status_code=400, detail="At least one other participant is required")
        for uid in unique_ids:
            if not self.db.get(User, uid):
                raise HTTPException(status_code=400, detail=f"User {uid} not found")
        conv = ChatConversation(title=title)
        self.db.add(conv)
        self.db.flush()
        for uid in unique_ids:
            self.db.add(ChatParticipant(conversation_id=conv.id, user_id=uid))
        return conv

    def find_or_create_direct(self, user_a: int, user_b: int) -> ChatConversation:
        if user_a == user_b:
            raise HTTPException(status_code=400, detail="Cannot chat with yourself")
        convs_a = {p.conversation_id for p in self.db.query(ChatParticipant).filter(ChatParticipant.user_id == user_a)}
        convs_b = {p.conversation_id for p in self.db.query(ChatParticipant).filter(ChatParticipant.user_id == user_b)}
        shared = convs_a & convs_b
        for cid in shared:
            participants = self._participant_ids(cid)
            if participants == {user_a, user_b}:
                conv = self.db.get(ChatConversation, cid)
                if conv:
                    return conv
        creator = self.db.get(User, user_a)
        if not creator:
            raise HTTPException(status_code=404, detail="User not found")
        return self.create_conversation(creator, [user_b])

    def list_messages(self, conversation_id: int, user_id: int, limit: int = 100) -> list[dict]:
        self._ensure_member(conversation_id, user_id)
        rows = (
            self.db.query(ChatMessage)
            .filter(ChatMessage.conversation_id == conversation_id)
            .order_by(ChatMessage.created_at.asc())
            .limit(limit)
            .all()
        )
        sender_ids = {m.sender_id for m in rows}
        users = {u.id: u for u in self.db.query(User).filter(User.id.in_(sender_ids)).all()}
        employee_ids = {u.employee_id for u in users.values() if u.employee_id}
        employees = (
            {e.id: e.name for e in self.db.query(Employee).filter(Employee.id.in_(employee_ids)).all()}
            if employee_ids
            else {}
        )
        return [
            {
                "id": m.id,
                "sender_id": m.sender_id,
                "sender_name": employees.get(users[m.sender_id].employee_id)
                if m.sender_id in users and users[m.sender_id].employee_id
                else (users[m.sender_id].email if m.sender_id in users else "Unknown"),
                "body": m.body,
                "created_at": m.created_at.isoformat(),
                "is_mine": m.sender_id == user_id,
            }
            for m in rows
        ]

    def send_message(self, conversation_id: int, sender: User, body: str) -> ChatMessage:
        self._ensure_member(conversation_id, sender.id)
        msg = ChatMessage(conversation_id=conversation_id, sender_id=sender.id, body=body.strip())
        self.db.add(msg)
        conv = self.db.get(ChatConversation, conversation_id)
        if conv:
            conv.updated_at = datetime.utcnow()
        return msg

    def mark_read(self, conversation_id: int, user_id: int):
        self._ensure_member(conversation_id, user_id)
        (
            self.db.query(ChatMessage)
            .filter(
                ChatMessage.conversation_id == conversation_id,
                ChatMessage.sender_id != user_id,
                ChatMessage.read_at.is_(None),
            )
            .update({ChatMessage.read_at: datetime.utcnow()}, synchronize_session=False)
        )

    def resolve_user_id_for_employee(self, employee_id: int) -> int | None:
        user = self.db.query(User).filter(User.employee_id == employee_id).first()
        return user.id if user else None

    def unread_total(self, user_id: int) -> int:
        conv_ids = [
            p.conversation_id
            for p in self.db.query(ChatParticipant).filter(ChatParticipant.user_id == user_id).all()
        ]
        if not conv_ids:
            return 0
        return int(
            self.db.query(func.count(ChatMessage.id))
            .filter(
                ChatMessage.conversation_id.in_(conv_ids),
                ChatMessage.sender_id != user_id,
                ChatMessage.read_at.is_(None),
            )
            .scalar()
            or 0
        )
