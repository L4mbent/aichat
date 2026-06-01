"""iLink HTTP API client for WeChat ClawBot.

Translated from @tencent-weixin/openclaw-weixin src/api/api.ts
"""

import base64
import json
import os
import uuid

import httpx

from asuna.config import settings
from asuna.ilink.types import GetConfigResp, GetUpdatesResp, QRCodeStatus

# ---------------------------------------------------------------------------
# Header construction
# ---------------------------------------------------------------------------

ILINK_APP_ID = settings.ILINK_APP_ID
ILINK_CLIENT_VERSION = settings.ILINK_CLIENT_VERSION


def _random_wechat_uin() -> str:
    """X-WECHAT-UIN header: random uint32 -> decimal string -> base64."""
    raw = os.urandom(4)
    uint32 = int.from_bytes(raw, "big")
    return base64.b64encode(str(uint32).encode()).decode()


def build_headers(token: str) -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "AuthorizationType": "ilink_bot_token",
        "Authorization": f"Bearer {token}",
        "X-WECHAT-UIN": _random_wechat_uin(),
        "iLink-App-Id": ILINK_APP_ID,
        "iLink-App-ClientVersion": str(ILINK_CLIENT_VERSION),
    }


def build_common_headers() -> dict[str, str]:
    return {
        "iLink-App-Id": ILINK_APP_ID,
        "iLink-App-ClientVersion": str(ILINK_CLIENT_VERSION),
    }


def generate_client_id() -> str:
    return f"openclaw-weixin-{uuid.uuid4().hex[:12]}"


# ---------------------------------------------------------------------------
# API calls
# ---------------------------------------------------------------------------

async def get_updates(
    base_url: str,
    token: str,
    get_updates_buf: str = "",
    timeout: int = 35,
) -> GetUpdatesResp:
    """Long-poll getUpdates. Server holds the request until new messages or timeout."""
    url = f"{base_url.rstrip('/')}/ilink/bot/getupdates"
    headers = build_headers(token)
    body = {
        "get_updates_buf": get_updates_buf,
    }

    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout + 10, connect=10.0)) as client:
        resp = await client.post(url, json=body, headers=headers)
        resp.raise_for_status()
        data: dict = resp.json()

    return GetUpdatesResp(
        ret=data.get("ret", 0),
        errcode=data.get("errcode", 0),
        errmsg=data.get("errmsg", ""),
        msgs=[_parse_weixin_msg(m) for m in data.get("msgs", [])],
        get_updates_buf=data.get("get_updates_buf", ""),
        longpolling_timeout_ms=data.get("longpolling_timeout_ms", 0),
    )


async def send_message(
    base_url: str,
    token: str,
    to_user_id: str,
    text: str,
    context_token: str = "",
    run_id: str = "",
) -> None:
    """Send a text message to a user."""
    from asuna.ilink.types import MessageItem, MessageItemType, MessageState, MessageType

    url = f"{base_url.rstrip('/')}/ilink/bot/sendmessage"
    headers = build_headers(token)
    client_id = generate_client_id()

    item_list: list[dict] = []
    if text:
        item_list.append({
            "type": MessageItemType.TEXT,
            "text_item": {"text": text},
        })

    body: dict = {
        "msg": {
            "from_user_id": "",
            "to_user_id": to_user_id,
            "client_id": client_id,
            "message_type": MessageType.BOT,
            "message_state": MessageState.FINISH,
            "item_list": item_list,
        }
    }
    if context_token:
        body["msg"]["context_token"] = context_token
    if run_id:
        body["msg"]["run_id"] = run_id

    async with httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=10.0)) as client:
        resp = await client.post(url, json=body, headers=headers)
        resp.raise_for_status()


async def send_typing(
    base_url: str,
    token: str,
    to_user_id: str,
    typing_ticket: str = "",
) -> None:
    """Send a typing indicator."""
    from asuna.ilink.types import TypingStatus

    url = f"{base_url.rstrip('/')}/ilink/bot/sendtyping"
    headers = build_headers(token)
    body = {
        "ilink_user_id": to_user_id,
        "typing_ticket": typing_ticket,
        "status": TypingStatus.TYPING,
    }

    async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=5.0)) as client:
        resp = await client.post(url, json=body, headers=headers)
        resp.raise_for_status()


async def get_config(
    base_url: str,
    token: str,
    ilink_user_id: str,
    context_token: str = "",
) -> GetConfigResp:
    """Fetch bot config (includes typing_ticket) for a given user."""
    url = f"{base_url.rstrip('/')}/ilink/bot/getconfig"
    headers = build_headers(token)
    body = {
        "ilink_user_id": ilink_user_id,
        "context_token": context_token,
    }

    async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=5.0)) as client:
        resp = await client.post(url, json=body, headers=headers)
        resp.raise_for_status()
        data: dict = resp.json()

    return GetConfigResp(
        ret=data.get("ret", 0),
        errmsg=data.get("errmsg", ""),
        typing_ticket=data.get("typing_ticket", ""),
    )


# ---------------------------------------------------------------------------
# QR Code login
# ---------------------------------------------------------------------------

async def fetch_bot_qrcode(base_url: str) -> dict:
    """Fetch a QR code for login. Returns {qrcode, qrcode_img_content}."""
    url = f"{base_url.rstrip('/')}/ilink/bot/get_bot_qrcode?bot_type=3"
    headers = build_common_headers()
    body = {"local_token_list": []}

    async with httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=10.0)) as client:
        resp = await client.post(url, json=body, headers=headers)
        resp.raise_for_status()
        return resp.json()


async def poll_qrcode_status(
    base_url: str,
    qrcode: str,
    verify_code: str = "",
    timeout: int = 35,
) -> QRCodeStatus:
    """Long-poll for QR code scan status."""
    params = f"qrcode={httpx.URL(qrcode).raw_path if '%' in qrcode else qrcode}"
    if verify_code:
        params += f"&verify_code={verify_code}"

    url = f"{base_url.rstrip('/')}/ilink/bot/get_qrcode_status?{params}"
    sanitized_qrcode = qrcode.replace("%", "%25")
    url = f"{base_url.rstrip('/')}/ilink/bot/get_qrcode_status?qrcode={sanitized_qrcode}"
    if verify_code:
        url += f"&verify_code={verify_code}"

    headers = build_common_headers()

    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout + 10, connect=10.0)) as client:
        resp = await client.get(url, headers=headers)
        resp.raise_for_status()
        data: dict = resp.json()

    return QRCodeStatus(
        status=data.get("status", ""),
        bot_token=data.get("bot_token", ""),
        ilink_bot_id=data.get("ilink_bot_id", ""),
        baseurl=data.get("baseurl", ""),
        ilink_user_id=data.get("ilink_user_id", ""),
        redirect_host=data.get("redirect_host", ""),
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _parse_weixin_msg(data: dict):
    """Parse a raw dict into a WeixinMessage dataclass."""
    from asuna.ilink.types import (
        CDNMedia,
        FileItem,
        ImageItem,
        MessageItem,
        RefMessage,
        TextItem,
        ToolCallResultItem,
        ToolCallStartItem,
        VideoItem,
        VoiceItem,
        WeixinMessage,
    )

    def parse_item(item_data: dict) -> MessageItem:
        text_item = None
        if item_data.get("text_item"):
            text_item = TextItem(text=item_data["text_item"].get("text", ""))

        image_item = None
        if item_data.get("image_item"):
            img = item_data["image_item"]
            image_item = ImageItem(
                media=_parse_cdn(img.get("media")),
                thumb_media=_parse_cdn(img.get("thumb_media")),
                aeskey=img.get("aeskey", ""),
                url=img.get("url", ""),
                mid_size=img.get("mid_size", 0),
                thumb_size=img.get("thumb_size", 0),
                thumb_height=img.get("thumb_height", 0),
                thumb_width=img.get("thumb_width", 0),
                hd_size=img.get("hd_size", 0),
            )

        voice_item = None
        if item_data.get("voice_item"):
            v = item_data["voice_item"]
            voice_item = VoiceItem(
                media=_parse_cdn(v.get("media")),
                encode_type=v.get("encode_type", 0),
                bits_per_sample=v.get("bits_per_sample", 0),
                sample_rate=v.get("sample_rate", 0),
                playtime=v.get("playtime", 0),
                text=v.get("text", ""),
            )

        file_item = None
        if item_data.get("file_item"):
            f = item_data["file_item"]
            file_item = FileItem(
                media=_parse_cdn(f.get("media")),
                file_name=f.get("file_name", ""),
                md5=f.get("md5", ""),
                len=str(f.get("len", "")),
            )

        video_item = None
        if item_data.get("video_item"):
            vd = item_data["video_item"]
            video_item = VideoItem(
                media=_parse_cdn(vd.get("media")),
                video_size=vd.get("video_size", 0),
                play_length=vd.get("play_length", 0),
                video_md5=vd.get("video_md5", ""),
                thumb_media=_parse_cdn(vd.get("thumb_media")),
                thumb_size=vd.get("thumb_size", 0),
                thumb_height=vd.get("thumb_height", 0),
                thumb_width=vd.get("thumb_width", 0),
            )

        ref_msg = None
        if item_data.get("ref_msg"):
            ref = item_data["ref_msg"]
            ref_msg = RefMessage(
                message_item=parse_item(ref.get("message_item", {})) if ref.get("message_item") else None,
                title=ref.get("title", ""),
            )

        tool_call_start = None
        if item_data.get("tool_call_start_item"):
            tcs = item_data["tool_call_start_item"]
            tool_call_start = ToolCallStartItem(
                tool_name=tcs.get("tool_name", ""),
                tool_call_id=tcs.get("tool_call_id", ""),
            )

        tool_call_result = None
        if item_data.get("tool_call_result_item"):
            tcr = item_data["tool_call_result_item"]
            tool_call_result = ToolCallResultItem(
                tool_name=tcr.get("tool_name", ""),
                tool_call_id=tcr.get("tool_call_id", ""),
                status=tcr.get("status", ""),
            )

        return MessageItem(
            type=item_data.get("type", 0),
            create_time_ms=item_data.get("create_time_ms", 0),
            update_time_ms=item_data.get("update_time_ms", 0),
            is_completed=item_data.get("is_completed", False),
            msg_id=item_data.get("msg_id", ""),
            ref_msg=ref_msg,
            text_item=text_item,
            image_item=image_item,
            voice_item=voice_item,
            file_item=file_item,
            video_item=video_item,
            tool_call_start_item=tool_call_start,
            tool_call_result_item=tool_call_result,
        )

    def _parse_cdn(data: dict | None) -> CDNMedia | None:
        if not data:
            return None
        return CDNMedia(
            encrypt_query_param=data.get("encrypt_query_param", ""),
            aes_key=data.get("aes_key", ""),
            encrypt_type=data.get("encrypt_type", 0),
            full_url=data.get("full_url", ""),
        )

    return WeixinMessage(
        seq=data.get("seq", 0),
        message_id=data.get("message_id", 0),
        from_user_id=data.get("from_user_id", ""),
        to_user_id=data.get("to_user_id", ""),
        client_id=data.get("client_id", ""),
        create_time_ms=data.get("create_time_ms", 0),
        update_time_ms=data.get("update_time_ms", 0),
        delete_time_ms=data.get("delete_time_ms", 0),
        session_id=data.get("session_id", ""),
        group_id=data.get("group_id", ""),
        message_type=data.get("message_type", 0),
        message_state=data.get("message_state", 0),
        item_list=[parse_item(i) for i in data.get("item_list", [])],
        context_token=data.get("context_token", ""),
        run_id=data.get("run_id", ""),
    )
