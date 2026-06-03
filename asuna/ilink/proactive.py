"""Proactive messaging — Asuna occasionally reaches out on her own."""

import asyncio
import logging
import random
from datetime import datetime, timezone, timedelta

from asuna.config import settings
from asuna.llm.client import get_client

logger = logging.getLogger(__name__)

PROACTIVE_PROMPT = """{time_str}

你是Asuna，想主动给你微信上的朋友发条很短的消息。规则：
- 总共1-2句话，不许超过2句。用 ||| 隔开
- 像真人随手发微信一样，随便一点，不用规整
- 根据时间决定发什么合适（早上问候、中午聊午饭、晚上让人早点休息）
- 可以吐槽、分享小事、随口问候，但不要问"在干嘛"
- 不要括号动作描写
- 比如："Mou...Kirito-kun又把厨房弄得一团糟。|||算了，你吃饭没？"
- 再比如："刚练完剑，手酸死了。" """.strip()


async def generate_proactive_message() -> str:
    now = datetime.now(timezone(timedelta(hours=8)))
    time_str = now.strftime("%H:%M")

    client = get_client()
    response = await client.chat.completions.create(
        model=settings.DEEPSEEK_MODEL,
        messages=[{"role": "user", "content": PROACTIVE_PROMPT.format(time_str=time_str)}],
        temperature=0.95,
        top_p=1.0,
        max_tokens=120,
        stream=False,
    )
    return response.choices[0].message.content or ""


class ProactiveScheduler:
    """Sends Asuna-initiated messages at random intervals to recent users."""

    def __init__(
        self,
        token: str,
        base_url: str,
        mgr,  # SessionManager
    ) -> None:
        self.token = token
        self.base_url = base_url
        self.mgr = mgr
        self._last_user_index = 0

    async def _get_recent_users(self) -> list[str]:
        """Get users who've chatted with Asuna recently."""
        from sqlalchemy import select, func
        from asuna.db.models import User
        import datetime

        async with self.mgr.session_factory() as session:
            cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=7)
            result = await session.execute(
                select(User.user_id)
                .where(User.last_active_at >= cutoff, User.is_blocked == 0)
                .order_by(func.random())
                .limit(5)
            )
            return [row[0] for row in result.all()]

    async def tick(self, stop_signal: asyncio.Event) -> None:
        """One proactive cycle: pick a user, generate a message, send it."""
        if stop_signal.is_set():
            return

        users = await self._get_recent_users()
        if not users:
            logger.debug("No recent users to message proactively")
            return

        user_id = random.choice(users)
        logger.info("Proactive message to %s", user_id[:20])

        try:
            from asuna.ilink.api import send_message
            from asuna.ilink.state import get_context_token

            text = await generate_proactive_message()
            if not text or not text.strip():
                return

            context_token = get_context_token("default", user_id)

            # Split and send
            import re
            if "|||" in text:
                parts = [p.strip() for p in text.split("|||") if p.strip()]
            else:
                parts = [p.strip() for p in re.split(r"[。！？\n]+", text) if p.strip()]

            parts = [re.sub(r"[（(][^）)]*[）)]", "", p).strip() for p in parts]
            parts = [p for p in parts if p]

            for i, part in enumerate(parts):
                await send_message(self.base_url, self.token, user_id, part, context_token)
                if i < len(parts) - 1:
                    await asyncio.sleep(0.8)

        except Exception:
            logger.exception("Proactive message failed for %s", user_id)

    async def run(self, stop_signal: asyncio.Event) -> None:
        """Main loop: wait random interval, then send a proactive message."""
        while not stop_signal.is_set():
            # Random interval: 2-4 hours in seconds
            interval = random.randint(7200, 14400)  # 2h to 4h
            logger.info("Next proactive message in %d minutes", interval // 60)

            # Wait in 60s chunks so we can respond to stop signal
            for _ in range(interval // 60):
                if stop_signal.is_set():
                    return
                await asyncio.sleep(60)

            if stop_signal.is_set():
                return

            await self.tick(stop_signal)
