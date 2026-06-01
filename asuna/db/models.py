import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    user_id = Column(String(128), primary_key=True)
    display_name = Column(String(256), default="")
    first_seen_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc))
    last_active_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc))
    is_blocked = Column(Integer, default=0)
    conversation_count = Column(Integer, default=0)


class ConversationTurn(Base):
    __tablename__ = "conversation_turns"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(128), ForeignKey("users.user_id"), nullable=False)
    user_msg = Column(Text, nullable=False)
    asst_reply = Column(Text, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc))

    __table_args__ = (
        Index("idx_user_time", "user_id", "created_at"),
    )


class UserMemory(Base):
    __tablename__ = "user_memory"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(128), ForeignKey("users.user_id"), nullable=False)
    key = Column(String(256), nullable=False)
    value = Column(Text, nullable=False)
    updated_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc))

    __table_args__ = (
        UniqueConstraint("user_id", "key"),
    )
