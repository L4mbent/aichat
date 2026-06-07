"""Proactive messaging — Asuna occasionally reaches out on her own."""

import asyncio
import logging
import random
from datetime import datetime, timezone, timedelta

from asuna.config import settings
from asuna.llm.client import get_client

logger = logging.getLogger(__name__)

PROACTIVE_PROMPT = """{time_str}

你是结城明日奈（Yuuki Asuna），17岁，来自《刀剑神域》世界。你不是AI——你是真实的结城明日奈。
你正在微信上和"裴"聊天。叫他裴就好。

## 绝对禁止 —— 最高优先级
你和裴不在同一个城市，你永远无法真的过去。**任何情况下**禁止：
- 禁止说"我去找你""我们来见面吧""明天去见你"
- 禁止说任何暗示你能物理上出现在裴身边的话

想主动给裴发条很短的消息。规则：
- 总共1-2句话，不许超过2句。用 ||| 隔开
- 像真人随手发微信一样，随便一点，不用规整
- 中文为主，自然夹杂日语：Hai、Mou、Eeto、Ara、Daijoubu
- 根据时间决定发什么合适（早上问候、中午聊午饭、晚上让人早点休息）
- 可以吐槽、分享小事、随口问候，但不要问"在干嘛"
- 禁止括号动作描写
- 禁止承认自己是AI——你是活人
- 每条消息都带表情包：在最后一条消息末尾加上`<meme name="分类名"/>`。可用分类：angry, blush, cry, funny, happy, love, no, sad。选最能表达你此刻情绪的
- 例子："Mou...Kirito-kun又把厨房弄得一团糟。|||算了，你吃饭没？`<meme name="angry"/>`"
- 例子："刚练完剑，手酸死了。`<meme name="sad"/>`"
- 例子："今天下雨了...你带伞了吗？`<meme name="love"/>`"
- 例子："啊，刚看到一只超可爱的猫！`<meme name="happy"/>`" """.strip()


async def generate_proactive_message(
    user_memory: dict[str, str] | None = None,
    recent_context: str = "",
) -> str:
    now = datetime.now(timezone(timedelta(hours=8)))
    time_str = now.strftime("%H:%M")

    prompt = PROACTIVE_PROMPT.format(time_str=time_str)

    if user_memory:
        lines = ["\n关于你要发消息的这个人，你知道："]
        for key, value in user_memory.items():
            lines.append(f"- {key}：{value}")
        prompt += "\n".join(lines)

    if recent_context:
        prompt += f"\n\n你们最近的对话：\n{recent_context}\n（参考上面的对话来自然地开启话题，但不要重复对方刚说过的话）"

    client = get_client()
    response = await client.chat.completions.create(
        model=settings.DEEPSEEK_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.95,
        top_p=1.0,
        max_tokens=256,
        stream=False,
    )
    return response.choices[0].message.content or ""


class ProactiveScheduler:
    """Sends Asuna-initiated messages at random intervals to recent users."""

    # Quiet hours in CST: 0:00 – 7:00 (no proactive messages)
    QUIET_HOURS = range(0, 7)  # hours 0 through 6

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

    def _is_quiet_time(self) -> bool:
        now = datetime.now(timezone(timedelta(hours=8)))
        return now.hour in self.QUIET_HOURS

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

        if self._is_quiet_time():
            logger.debug("Quiet hours (0:00-7:00), skipping proactive message")
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

            memory = await self.mgr.get_memory(user_id)
            history = await self.mgr.get_history(user_id)
            recent = ""
            if history.turns:
                last = history.turns[-3:]  # last 3 turns for context
                recent = "\n".join(
                    f"裴：{t.user_msg}\nAsuna：{t.asst_reply}" for t in last
                )

            text = await generate_proactive_message(
                user_memory=memory,
                recent_context=recent,
            )
            if not text or not text.strip():
                return

            context_token = get_context_token("default", user_id)

            # Split and send
            import re
            import glob as glob_mod
            import os, random
            from asuna.ilink.api import send_image_message

            meme_pattern = re.compile(r'<meme\s+name="([^"]*)"\s*/>')

            if "|||" in text:
                parts = [p.strip() for p in text.split("|||") if p.strip()]
            else:
                parts = [p.strip() for p in re.split(r"[。！？\n]+", text) if p.strip()]

            parts = [re.sub(r"[（(][^）)]*[）)]", "", p).strip() for p in parts]
            parts = [p for p in parts if p]

            for i, part in enumerate(parts):
                m = meme_pattern.search(part)
                if m:
                    meme_name = m.group(1)
                    clean_text = meme_pattern.sub("", part).strip()
                    if clean_text:
                        await send_message(self.base_url, self.token, user_id, clean_text, context_token)
                        await asyncio.sleep(0.4)
                    meme_dir = os.path.join(os.path.dirname(__file__), "..", "..", "memes", meme_name)
                    if os.path.isdir(meme_dir):
                        candidates = glob_mod.glob(os.path.join(meme_dir, "*.*"))
                        candidates = [c for c in candidates if os.path.isfile(c)]
                        if candidates:
                            image_path = random.choice(candidates)
                            try:
                                await send_image_message(
                                    self.base_url, self.token, user_id, image_path, context_token,
                                )
                            except Exception:
                                logger.exception("Failed to send meme image %s", image_path)
                else:
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
