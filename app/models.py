import uuid
from datetime import date, datetime
from sqlalchemy import String, Text, Date, DateTime, Boolean, ForeignKey, func, UniqueConstraint, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base
class User(Base):
    __tablename__="users"
    id: Mapped[uuid.UUID]=mapped_column(UUID(as_uuid=True),primary_key=True,default=uuid.uuid4)
    email: Mapped[str]=mapped_column(String,unique=True,index=True)
    username: Mapped[str]=mapped_column(String(30),unique=True,index=True)
    password_hash: Mapped[str]=mapped_column(String)
    failed_login_attempts: Mapped[int]=mapped_column(default=0, server_default="0", nullable=False)
    locked_until: Mapped[datetime|None]=mapped_column(DateTime(timezone=True), nullable=True)
class Course(Base):
    __tablename__="courses"
    id: Mapped[uuid.UUID]=mapped_column(UUID(as_uuid=True),primary_key=True,default=uuid.uuid4)
    user_id: Mapped[uuid.UUID]=mapped_column(UUID(as_uuid=True),ForeignKey("users.id",ondelete="CASCADE"),index=True)
    name: Mapped[str]=mapped_column(String)
    code: Mapped[str|None]=mapped_column(String,nullable=True)
    term: Mapped[str|None]=mapped_column(String,nullable=True)
    is_active: Mapped[bool]=mapped_column(Boolean,default=True,server_default="true",nullable=False)
class Document(Base):
    __tablename__="documents"
    __table_args__ = (UniqueConstraint("user_id", "content_hash", name="uq_documents_user_content_hash"),)
    id: Mapped[uuid.UUID]=mapped_column(UUID(as_uuid=True),primary_key=True,default=uuid.uuid4)
    user_id: Mapped[uuid.UUID]=mapped_column(UUID(as_uuid=True),ForeignKey("users.id",ondelete="CASCADE"),index=True)
    course_id: Mapped[uuid.UUID]=mapped_column(UUID(as_uuid=True),ForeignKey("courses.id",ondelete="CASCADE"))
    is_confirmed: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    draft_proposals: Mapped[list[dict] | None] = mapped_column(JSON, nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    filename: Mapped[str]=mapped_column(String)
    status: Mapped[str]=mapped_column(String,default="uploaded")
class Activity(Base):
    __tablename__="activities"
    id: Mapped[uuid.UUID]=mapped_column(UUID(as_uuid=True),primary_key=True,default=uuid.uuid4)
    user_id: Mapped[uuid.UUID]=mapped_column(UUID(as_uuid=True),ForeignKey("users.id",ondelete="CASCADE"),index=True)
    course_id: Mapped[uuid.UUID]=mapped_column(UUID(as_uuid=True),ForeignKey("courses.id",ondelete="CASCADE"),index=True)
    document_id: Mapped[uuid.UUID|None]=mapped_column(UUID(as_uuid=True),ForeignKey("documents.id",ondelete="SET NULL"),nullable=True)
    activity_type: Mapped[str]=mapped_column(String(20),default="otro",server_default="otro",nullable=False)
    title: Mapped[str]=mapped_column(String)
    description: Mapped[str]=mapped_column(Text,default="")
    due_date: Mapped[date|None]=mapped_column(Date,nullable=True,index=True)
    status: Mapped[str]=mapped_column(String,default="pending")
    review_required: Mapped[bool]=mapped_column(Boolean,default=False)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),server_default=func.now())
    completed_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True),nullable=True)


class RevokedToken(Base):
    __tablename__ = "revoked_tokens"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class RequestLimit(Base):
    __tablename__ = "request_limits"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    requests: Mapped[int] = mapped_column(default=1)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
