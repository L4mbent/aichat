"""Long-poll monitor loop for WeChat ClawBot.

Polls getUpdates in a loop, dispatches each inbound message to the
callback for LLM processing, and handles errors / backoff / session expiry.

Translated from @tencent-weixin/openclaw-weixin src/monitor/monitor.ts
"""

import asyncio
import logging
import time
from collections.abc import Callable, Coroutine

from asuna.config import settings
from asuna.ilink.api import get_config, get_updates, send_message
from asuna.ilink.state import (
    get_context_token,
    load_sync_buf,
    save_context_token,
    save_sync_buf,
)
from asuna.ilink.types import MessageItemType, MessageType, extract_text

logger = logging.getLogger(__name__)

SESSION_EXPIRED_ERRCODE = -14
MAX_CONSECUTIVE_FAILURES = 3
BACKOFF_DELAY_S = 30
RETRY_DELAY_S = 2


MessageCallback = Callable[[str, str, str], Coroutine[None, None, str]]
"""
Callback signature: async def callback(user_id: str, content: str, context_token: str) -> str
Returns the reply text that was sent.
"""


async def run_monitor(
    token: str,
    account_id: str,
    base_url: str,
    process_message: MessageCallback,
    stop_signal: asyncio.Event | None = None,
) -> None:
    """Run the long-poll monitor loop.

    Args:
        token: Bot token from QR login.
        account_id: Bot account ID (ilink_bot_id).
        base_url: iLink API base URL.
        process_message: Async callback to handle each inbound text message.
        stop_signal: Set this event to gracefully stop the monitor.
    """
    if stop_signal is None:
        stop_signal = asyncio.Event()

    # Restore previous sync buffer for resumption
    get_updates_buf = load_sync_buf(account_id)
    if get_updates_buf:
        logger.info("Resuming from previous sync buf (%d bytes)", len(get_updates_buf))
    else:
        logger.info("No previous sync buf, starting fresh")

    long_poll_timeout = settings.ILINK_LONG_POLL_TIMEOUT
    consecutive_failures = 0
    # Cache for per-user typing_ticket (keyed by user_id)
    typing_tickets: dict[str, str] = {}

    logger.info("Monitor started (account=%s, base_url=%s)", account_id, base_url)

    while not stop_signal.is_set():
        try:
            resp = await get_updates(
                base_url=base_url,
                token=token,
                get_updates_buf=get_updates_buf,
                timeout=long_poll_timeout,
            )

            # Update long-poll timeout from server hint
            if resp.longpolling_timeout_ms and resp.longpolling_timeout_ms > 0:
                long_poll_timeout = max(resp.longpolling_timeout_ms // 1000, 5)
                logger.debug("Server suggested poll timeout: %ds", long_poll_timeout)

            # Check for API-level errors
            is_api_error = resp.ret != 0 or resp.errcode != 0
            if is_api_error:
                if resp.errcode == SESSION_EXPIRED_ERRCODE or resp.ret == SESSION_EXPIRED_ERRCODE:
                    logger.error(
                        "Session expired (errcode=%d, ret=%d). Pausing for 5 minutes.",
                        resp.errcode, resp.ret,
                    )
                    consecutive_failures = 0
                    await _sleep(300, stop_signal)
                    continue

                consecutive_failures += 1
                logger.error(
                    "getUpdates failed: ret=%d errcode=%d errmsg=%s (%d/%d)",
                    resp.ret, resp.errcode, resp.errmsg,
                    consecutive_failures, MAX_CONSECUTIVE_FAILURES,
                )

                if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                    logger.error(
                        "%d consecutive failures, backing off %ds",
                        MAX_CONSECUTIVE_FAILURES, BACKOFF_DELAY_S,
                    )
                    consecutive_failures = 0
                    await _sleep(BACKOFF_DELAY_S, stop_signal)
                else:
                    await _sleep(RETRY_DELAY_S, stop_signal)
                continue

            consecutive_failures = 0

            # Save sync buffer for next request
            if resp.get_updates_buf:
                save_sync_buf(account_id, resp.get_updates_buf)
                get_updates_buf = resp.get_updates_buf

            # Process messages
            for msg in resp.msgs:
                # Skip bot's own messages to prevent echo loops
                if msg.message_type == MessageType.BOT:
                    continue

                text = extract_text(msg)
                user_id = msg.from_user_id
                context_token = msg.context_token

                if not text.strip() or not user_id:
                    continue

                logger.info("Inbound from=%s text=%.80s...", user_id, text)

                # Cache context token
                if context_token:
                    save_context_token(account_id, user_id, context_token)

                # Get or refresh typing ticket for this user
                if user_id not in typing_tickets:
                    try:
                        config_resp = await get_config(
                            base_url, token, user_id, context_token,
                        )
                        if config_resp.typing_ticket:
                            typing_tickets[user_id] = config_resp.typing_ticket
                    except Exception:
                        logger.debug("Failed to get config for %s", user_id)

                # Process the message through the callback
                try:
                    reply = await process_message(user_id, text, context_token)
                except Exception:
                    logger.exception("process_message failed for user=%s", user_id)
                    try:
                        await send_message(
                            base_url, token, user_id,
                            "Eeto...抱歉，刚才走神了一下。可以再说一次吗？",
                            context_token,
                        )
                    except Exception:
                        logger.exception("Failed to send error reply to %s", user_id)

        except asyncio.CancelledError:
            logger.info("Monitor cancelled")
            break
        except Exception:
            if stop_signal.is_set():
                break
            consecutive_failures += 1
            logger.exception(
                "getUpdates exception (%d/%d)",
                consecutive_failures, MAX_CONSECUTIVE_FAILURES,
            )
            if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                consecutive_failures = 0
                await _sleep(BACKOFF_DELAY_S, stop_signal)
            else:
                await _sleep(RETRY_DELAY_S, stop_signal)

    logger.info("Monitor stopped (account=%s)", account_id)


async def _sleep(seconds: float, stop_signal: asyncio.Event) -> None:
    """Sleep but wake early if stop_signal is set."""
    try:
        await asyncio.wait_for(stop_signal.wait(), timeout=seconds)
    except asyncio.TimeoutError:
        pass
