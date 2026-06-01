import asyncio
import logging

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import create_async_engine

from asuna.config import settings
from asuna.db.session import SessionManager
from asuna.llm.client import get_ai_response
from asuna.middleware.rate_limit import RateLimiter
from asuna.utils.logger import setup_logging

setup_logging()
logger = logging.getLogger(__name__)

session_manager: SessionManager | None = None
rate_limiter: RateLimiter | None = None


def create_app() -> FastAPI:
    app = FastAPI(
        title="Asuna AI Agent",
        description="Yuuki Asuna (结城明日奈) character AI for WeChat via iLink ClawBot",
        version="2.0.0",
    )

    @app.get("/health")
    async def health_check():
        return {"status": "ok", "character": "Yuuki Asuna", "channel": "ilink"}

    return app


async def _periodic_cleanup(mgr: SessionManager) -> None:
    while True:
        await asyncio.sleep(300)
        try:
            await mgr.cleanup_stale_sessions()
        except Exception:
            logger.exception("Cleanup error")


async def start_monitor(
    mgr: SessionManager,
    limiter: RateLimiter,
    stop_signal: asyncio.Event,
) -> None:
    """Initialize DB and start the iLink long-poll monitor."""
    from asuna.ilink.api import send_message
    from asuna.ilink.monitor import run_monitor
    from asuna.ilink.state import load_account

    global session_manager, rate_limiter
    session_manager = mgr
    rate_limiter = limiter

    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    await mgr.initialize()

    # Cleanup task
    cleanup_task = asyncio.create_task(_periodic_cleanup(mgr))

    # Load account credentials
    account = load_account()
    if not account:
        logger.error(
            "No account found. Please run 'python run.py login' first."
        )
        return

    token = account.get("token", "")
    account_id = account.get("account_id", "")
    base_url = account.get("base_url", settings.ILINK_BASE_URL)

    async def process_message(user_id: str, content: str, context_token: str) -> str:
        """Process a user message and send reply via iLink."""
        if not limiter.check_and_acquire(user_id):
            await send_message(
                base_url, token, user_id,
                "Gomen nasai...消息太快了，请稍微慢一点和我说话哦~",
                context_token,
            )
            return ""

        await mgr.get_or_create_user(user_id)
        history = await mgr.get_history(user_id)
        memory = await mgr.get_memory(user_id)
        memory_text = mgr.build_memory_injection(memory)

        reply = await get_ai_response(content, history)

        if memory_text:
            full_reply = memory_text + reply
        else:
            full_reply = reply

        await mgr.save_turn(user_id, content, reply)
        await send_message(base_url, token, user_id, full_reply, context_token)
        return full_reply

    try:
        await run_monitor(
            token=token,
            account_id=account_id,
            base_url=base_url,
            process_message=process_message,
            stop_signal=stop_signal,
        )
    finally:
        cleanup_task.cancel()
        await mgr.close()


# Alias for the old webhook-based process_user_message (kept for webchat.py compatibility)
async def process_user_message_legacy(user_id: str, content: str, timestamp: float) -> None:
    """Legacy handler for webchat compatibility."""
    if session_manager is None:
        return
    await session_manager.get_or_create_user(user_id)
    history = await session_manager.get_history(user_id)
    await get_ai_response(content, history)
