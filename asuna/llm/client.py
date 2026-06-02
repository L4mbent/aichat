from datetime import datetime, timezone, timedelta

from openai import AsyncOpenAI
import httpx

from asuna.config import settings
from asuna.character.system_prompt import ASUNA_SYSTEM_PROMPT
from asuna.llm.history import ConversationHistory


def _build_system_prompt(memories: dict[str, str] | None = None) -> str:
    """Inject current datetime and user memories into the system prompt."""
    now = datetime.now(timezone(timedelta(hours=8)))  # CST / JST
    time_str = now.strftime("%Y年%m月%d日 %H:%M，星期%w").replace("星期0", "星期日").replace("星期1", "星期一").replace("星期2", "星期二").replace("星期3", "星期三").replace("星期4", "星期四").replace("星期5", "星期五").replace("星期6", "星期六")

    prompt = f"当前时间：{time_str}\n\n" + ASUNA_SYSTEM_PROMPT

    if memories:
        lines = ["\n## 关于当前对话对象，你知道："]
        for key, value in memories.items():
            lines.append(f"- {key}：{value}")
        lines.append("（以上信息可能不完整，根据对话自然使用）")
        prompt += "\n".join(lines)

    return prompt

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


def build_messages(user_message: str, history: ConversationHistory, memories: dict[str, str] | None = None) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = [
        {"role": "system", "content": _build_system_prompt(memories)}
    ]
    messages.extend(history.get_messages())
    messages.append({"role": "user", "content": user_message})
    return messages


async def get_ai_response(
    user_message: str,
    history: ConversationHistory,
    memories: dict[str, str] | None = None,
) -> str:
    client = get_client()
    messages = build_messages(user_message, history, memories)

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


MEMORY_EXTRACT_PROMPT = """从下面这段对话中提取关于用户的值得记住的信息。

上一次已知的用户信息（可能为空）：
{existing}

本次对话：
用户：{user_msg}
Asuna：{asst_reply}

只返回JSON数组，每个元素是{"key": "事实名称", "value": "事实内容"}。
只提取**新增**或**变化**的信息，不要重复已有的。
如果没有任何值得记住的新信息，返回空数组 []。

例：[{"key": "名字", "value": "小明"}, {"key": "喜欢的食物", "value": "拉面"}]"""


async def extract_memories(
    existing: dict[str, str],
    user_msg: str,
    asst_reply: str,
) -> list[dict[str, str]]:
    """Extract new facts about the user from the latest conversation turn."""
    client = get_client()

    existing_text = "\n".join(f"- {k}：{v}" for k, v in existing.items()) if existing else "（无）"
    prompt = MEMORY_EXTRACT_PROMPT.format(
        existing=existing_text,
        user_msg=user_msg,
        asst_reply=asst_reply,
    )

    response = await client.chat.completions.create(
        model=settings.DEEPSEEK_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
        top_p=1.0,
        max_tokens=1024,
        stream=False,
    )

    raw = response.choices[0].message.content or "[]"
    # Strip markdown code fences if present
    raw = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()

    try:
        import json
        items = json.loads(raw)
        if isinstance(items, list):
            return items
    except json.JSONDecodeError:
        pass
    return []


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
