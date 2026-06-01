import datetime
import logging
import time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from asuna.config import settings
from asuna.db.models import Base, ConversationTurn as DBConversationTurn, User, UserMemory
from asuna.llm.history import ConversationHistory, ConversationTurn

logger = logging.getLogger(__name__)


class SessionManager:
    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine
        self.session_factory = async_sessionmaker(engine, expire_on_commit=False)
        self._histories: dict[str, ConversationHistory] = {}
        self._last_active: dict[str, float] = {}

    async def initialize(self) -> None:
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def close(self) -> None:
        await self.engine.dispose()

    async def get_or_create_user(self, user_id: str) -> User:
        async with self.session_factory() as session:
            user = await session.get(User, user_id)
            if user is None:
                user = User(user_id=user_id)
                session.add(user)
                await session.commit()
            else:
                user.last_active_at = datetime.datetime.now(datetime.timezone.utc)
                user.conversation_count += 1
                await session.commit()
            return user

    async def get_history(self, user_id: str) -> ConversationHistory:
        now = time.time()

        # Check in-memory cache
        if user_id in self._histories:
            self._last_active[user_id] = now
            return self._histories[user_id]

        # Load from DB
        history = ConversationHistory(max_turns=settings.MAX_HISTORY_TURNS)
        async with self.session_factory() as session:
            result = await session.execute(
                select(DBConversationTurn)
                .where(DBConversationTurn.user_id == user_id)
                .order_by(DBConversationTurn.created_at.desc())
                .limit(settings.MAX_HISTORY_TURNS)
            )
            rows = result.scalars().all()
            # Reverse to get chronological order
            for row in reversed(rows):
                history.turns.append(
                    ConversationTurn(
                        user_msg=row.user_msg,
                        asst_reply=row.asst_reply,
                        timestamp=row.created_at.timestamp(),
                    )
                )

        self._histories[user_id] = history
        self._last_active[user_id] = now
        return history

    async def save_turn(self, user_id: str, user_msg: str, asst_reply: str) -> None:
        async with self.session_factory() as session:
            turn = DBConversationTurn(
                user_id=user_id,
                user_msg=user_msg,
                asst_reply=asst_reply,
            )
            session.add(turn)
            await session.commit()

    async def get_memory(self, user_id: str) -> dict[str, str]:
        async with self.session_factory() as session:
            result = await session.execute(
                select(UserMemory).where(UserMemory.user_id == user_id)
            )
            rows = result.scalars().all()
            return {row.key: row.value for row in rows}

    async def set_memory(self, user_id: str, key: str, value: str) -> None:
        async with self.session_factory() as session:
            mem = await session.get(UserMemory, (user_id, key))
            if mem is None:
                mem = UserMemory(user_id=user_id, key=key, value=value)
                session.add(mem)
            else:
                mem.value = value
                mem.updated_at = datetime.datetime.now(datetime.timezone.utc)
            await session.commit()

    def build_memory_injection(self, memory: dict[str, str]) -> str:
        if not memory:
            return ""
        lines = ["\n[用户信息]"]
        for key, value in memory.items():
            lines.append(f"- {key}：{value}")
        lines.append("[/用户信息]\n")
        return "\n".join(lines)

    async def cleanup_stale_sessions(self) -> int:
        now = time.time()
        timeout = settings.SESSION_TIMEOUT_MINUTES * 60
        stale = [
            uid for uid, last in self._last_active.items()
            if now - last > timeout
        ]
        for uid in stale:
            del self._histories[uid]
            del self._last_active[uid]
        if stale:
            logger.info("Cleaned up %d stale sessions", len(stale))
        return len(stale)
