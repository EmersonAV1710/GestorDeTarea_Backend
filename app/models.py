import uuid
from datetime import date, datetime
from sqlalchemy import String, Text, Date, DateTime, Boolean, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base
class User(Base):
    __tablename__="users"
    id: Mapped[uuid.UUID]=mapped_column(UUID(as_uuid=True),primary_key=True,default=uuid.uuid4)
    email: Mapped[str]=mapped_column(String,unique=True,index=True)
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
class Document(Base):
    __tablename__="documents"
    id: Mapped[uuid.UUID]=mapped_column(UUID(as_uuid=True),primary_key=True,default=uuid.uuid4)
    user_id: Mapped[uuid.UUID]=mapped_column(UUID(as_uuid=True),ForeignKey("users.id",ondelete="CASCADE"),index=True)
    course_id: Mapped[uuid.UUID]=mapped_column(UUID(as_uuid=True),ForeignKey("courses.id",ondelete="CASCADE"))
    filename: Mapped[str]=mapped_column(String)
    status: Mapped[str]=mapped_column(String,default="uploaded")
class Activity(Base):
    __tablename__="activities"
    id: Mapped[uuid.UUID]=mapped_column(UUID(as_uuid=True),primary_key=True,default=uuid.uuid4)
    user_id: Mapped[uuid.UUID]=mapped_column(UUID(as_uuid=True),ForeignKey("users.id",ondelete="CASCADE"),index=True)
    course_id: Mapped[uuid.UUID]=mapped_column(UUID(as_uuid=True),ForeignKey("courses.id",ondelete="CASCADE"),index=True)
    document_id: Mapped[uuid.UUID|None]=mapped_column(UUID(as_uuid=True),ForeignKey("documents.id",ondelete="SET NULL"),nullable=True)
    title: Mapped[str]=mapped_column(String)
    description: Mapped[str]=mapped_column(Text,default="")
    due_date: Mapped[date|None]=mapped_column(Date,nullable=True,index=True)
    status: Mapped[str]=mapped_column(String,default="pending")
    review_required: Mapped[bool]=mapped_column(Boolean,default=False)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),server_default=func.now())
    completed_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True),nullable=True)
