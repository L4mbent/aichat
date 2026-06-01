from datetime import datetime, timezone, timedelta

from openai import AsyncOpenAI
import httpx

from asuna.config import settings
from asuna.character.system_prompt import ASUNA_SYSTEM_PROMPT
from asuna.llm.history import ConversationHistory


def _build_system_prompt() -> str:
    """Inject current datetime into the system prompt."""
    now = datetime.now(timezone(timedelta(hours=8)))  # CST / JST
    time_str = now.strftime("%Y年%m月%d日 %H:%M，星期%w").replace("星期0", "星期日").replace("星期1", "星期一").replace("星期2", "星期二").replace("星期3", "星期三").replace("星期4", "星期四").replace("星期5", "星期五").replace("星期6", "星期六")
    return f"当前时间：{time_str}\n\n" + ASUNA_SYSTEM_PROMPT

_client: AsyncOpenAI | None = None


def get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(
            api_key=settings.DEEPSEEK_API_KEY,
            base_url=settings.DEEPSEEK_BASE_URL,
            timeout=httpx.Timeout(60.0, connect=10.0),
            max_retries=2,
        )
    return _client


def build_messages(user_message: str, history: ConversationHistory) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = [
        {"role": "system", "content": _build_system_prompt()}
    ]
    messages.extend(history.get_messages())
    messages.append({"role": "user", "content": user_message})
    return messages


async def get_ai_response(
    user_message: str,
    history: ConversationHistory,
) -> str:
    client = get_client()
    messages = build_messages(user_message, history)

    response = await client.chat.completions.create(
        model=settings.DEEPSEEK_MODEL,
        messages=messages,
        temperature=0.85,
        top_p=1.0,
        max_tokens=2048,
        stream=False,
    )

    reply = response.choices[0].message.content or ""
    history.add(user_message, reply)
    return reply


async def get_ai_response_stream(
    user_message: str,
    history: ConversationHistory,
):
    client = get_client()
    messages = build_messages(user_message, history)

    stream = await client.chat.completions.create(
        model=settings.DEEPSEEK_MODEL,
        messages=messages,
        temperature=0.85,
        top_p=1.0,
        max_tokens=2048,
        stream=True,
    )

    full_reply: list[str] = []
    async for chunk in stream:
        delta = chunk.choices[0].delta.content
        if delta:
            full_reply.append(delta)
            yield delta

    history.add(user_message, "".join(full_reply))
