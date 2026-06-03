#!/usr/bin/env python
"""Asuna AI Agent — 结城明日奈

Entry point for the Asuna WeChat ClawBot. Supports three modes:

    python run.py login   — 扫码登录微信 ClawBot
    python run.py serve   — 启动服务 (health check + 长轮询 monitor)
    python run.py chat    — 终端交互测试模式
"""

import asyncio
import logging
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from asuna.utils.logger import setup_logging

setup_logging()
logger = logging.getLogger("asuna.run")


def print_banner() -> None:
    print(r"""
   ⚔️  结城明日奈  ⚔️
   Yuuki Asuna · 血盟骑士团副团长 · 闪光
   WeChat ClawBot via iLink
""")


async def cmd_login() -> None:
    """Scan QR code to log in to WeChat ClawBot."""
    from asuna.ilink.login import run_login_flow

    print_banner()
    result = await run_login_flow()

    if result["success"]:
        print("\n 登录成功！现在可以运行 serve 模式了:")
        print("   python run.py serve")
        print(f"\n  Bot ID: {result['account_id']}")
        if result["user_id"]:
            print(f"  你的微信 ID: {result['user_id']}")
    else:
        print(f"\n 登录失败: {result.get('error', '未知错误')}")
        sys.exit(1)


async def cmd_serve() -> None:
    """Start the FastAPI health server + iLink long-poll monitor."""
    import uvicorn
    from contextlib import asynccontextmanager

    from fastapi import FastAPI
    from sqlalchemy.ext.asyncio import create_async_engine

    from asuna.config import settings
    from asuna.db.session import SessionManager
    from asuna.ilink.api import send_message
    from asuna.ilink.monitor import run_monitor
    from asuna.ilink.proactive import ProactiveScheduler
    from asuna.ilink.state import load_account
    from asuna.llm.client import get_ai_response, extract_memories
    from asuna.middleware.rate_limit import RateLimiter

    print_banner()

    # -- Load account ---------------------------------------------------------
    account = load_account()
    if not account:
        logger.error("No account found. Run 'python run.py login' first.")
        sys.exit(1)

    token = account["token"]
    account_id = account["account_id"]
    base_url = account.get("base_url", settings.ILINK_BASE_URL)

    # -- DB, rate limiter -----------------------------------------------------
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    mgr = SessionManager(engine)
    await mgr.initialize()
    limiter = RateLimiter()

    # -- Cleanup task ---------------------------------------------------------
    async def periodic_cleanup() -> None:
        while True:
            await asyncio.sleep(300)
            try:
                await mgr.cleanup_stale_sessions()
            except Exception:
                logger.exception("Cleanup error")

    cleanup_task = asyncio.create_task(periodic_cleanup())

    # -- Stop signal ----------------------------------------------------------
    stop_signal = asyncio.Event()

    # -- Message processor ----------------------------------------------------
    async def process_message(user_id: str, content: str, context_token: str) -> str:
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

        reply = await get_ai_response(content, history, memory)

        await mgr.save_turn(user_id, content, reply)

        # Split and clean replies:
        # 1. Split on |||
        # 2. Strip parenthetical stage directions like (笑)(叹气)(脸红)
        import re
        if "|||" in reply:
            parts = [p.strip() for p in reply.split("|||") if p.strip()]
        else:
            parts = [p.strip() for p in re.split(r"[。！？\n]+", reply) if p.strip()]

        parts = [re.sub(r"[（(][^）)]*[）)]", "", p).strip() for p in parts]
        parts = [p for p in parts if p]  # remove empty after stripping

        for i, part in enumerate(parts):
            await send_message(base_url, token, user_id, part, context_token)
            if i < len(parts) - 1:
                await asyncio.sleep(0.8)

        # Extract new memories from this conversation turn
        try:
            new_facts = await extract_memories(memory, content, reply)
            for fact in new_facts:
                await mgr.set_memory(user_id, fact["key"], fact["value"])
        except Exception:
            logger.debug("Memory extraction failed for %s", user_id)
        return reply

    # -- FastAPI app with lifespan -------------------------------------------
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logger.info("Asuna AI Agent started — 结城明日奈 参上！")
        yield
        stop_signal.set()
        cleanup_task.cancel()
        try:
            await cleanup_task
        except asyncio.CancelledError:
            pass
        await mgr.close()
        logger.info("Asuna AI Agent stopped.")

    app = FastAPI(
        title="Asuna AI Agent",
        description="Yuuki Asuna (结城明日奈) character AI for WeChat via iLink ClawBot",
        version="2.0.0",
        lifespan=lifespan,
    )

    @app.get("/health")
    async def health_check():
        return {"status": "ok", "character": "Yuuki Asuna", "channel": "ilink"}

    # -- Launch monitor in background -----------------------------------------
    async def _run_monitor() -> None:
        try:
            await run_monitor(
                token=token,
                account_id=account_id,
                base_url=base_url,
                process_message=process_message,
                stop_signal=stop_signal,
            )
        except asyncio.CancelledError:
            pass

    monitor_task = asyncio.create_task(_run_monitor())

    # -- Start proactive messaging scheduler ----------------------------------
    proactive = ProactiveScheduler(token=token, base_url=base_url, mgr=mgr)
    proactive_task = asyncio.create_task(proactive.run(stop_signal))

    # -- Start server --------------------------------------------------------
    config = uvicorn.Config(
        app,
        host=settings.HOST,
        port=settings.PORT,
        log_config=None,
        log_level=settings.LOG_LEVEL.lower(),
    )
    server = uvicorn.Server(config)

    try:
        await server.serve()
    finally:
        stop_signal.set()
        monitor_task.cancel()
        proactive_task.cancel()
        try:
            await monitor_task
        except asyncio.CancelledError:
            pass
        try:
            await proactive_task
        except asyncio.CancelledError:
            pass


async def cmd_chat() -> None:
    """Interactive terminal chat with Asuna."""
    from asuna.llm.client import get_ai_response
    from asuna.llm.history import ConversationHistory

    print_banner()
    print("输入 /quit 退出, /clear 清除记忆")
    print("=" * 50)
    print()

    history = ConversationHistory()

    while True:
        try:
            user_input = input("你: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nOtsukaresama deshita! 再见~")
            break

        if not user_input:
            continue
        if user_input == "/quit":
            print("Asuna: 下次再见啦！Ganbatte~")
            break
        if user_input == "/clear":
            history.clear()
            print("[记忆已清除]")
            continue

        print("Asuna: ", end="", flush=True)
        reply = await get_ai_response(user_input, history)
        print(reply)
        print()


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "serve"

    if mode == "login":
        asyncio.run(cmd_login())
    elif mode == "serve":
        asyncio.run(cmd_serve())
    elif mode == "chat":
        asyncio.run(cmd_chat())
    elif mode == "web":
        import uvicorn
        from webchat import app
        uvicorn.run(app, host="0.0.0.0", port=8080)
    else:
        print(f"用法: python run.py {{login|serve|chat|web}}")
        print(f"  login  — 扫码登录微信 ClawBot")
        print(f"  serve  — 启动服务 (health check + 微信长轮询)")
        print(f"  chat   — 终端交互测试")
        print(f"  web    — Web 聊天界面")
        sys.exit(1)


if __name__ == "__main__":
    main()
