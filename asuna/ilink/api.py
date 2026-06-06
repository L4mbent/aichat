"""iLink HTTP API client for WeChat ClawBot.

Translated from @tencent-weixin/openclaw-weixin src/api/api.ts
"""

import base64
import hashlib
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
    image_item: dict | None = None,
) -> str:
    """Send a message to a user. Returns the client_id (message ID).

    When `image_item` is provided, it is sent as a standalone IMAGE message
    (text is ignored). Otherwise, this sends a plain TEXT message.
    """
    from asuna.ilink.types import MessageItemType, MessageState, MessageType

    url = f"{base_url.rstrip('/')}/ilink/bot/sendmessage"
    headers = build_headers(token)
    client_id = generate_client_id()

    if image_item:
        item_list = [image_item]
    else:
        item_list = []
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

    return client_id


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


# ---------------------------------------------------------------------------
# CDN Image Upload & Send
# ---------------------------------------------------------------------------

AES_BLOCK_SIZE = 16
UPLOAD_MEDIA_TYPE_IMAGE = 1
CDN_UPLOAD_MAX_RETRIES = 3


def _aes_ecb_padded_size(plaintext_size: int) -> int:
    """AES-128-ECB ciphertext size with PKCS7 padding."""
    return ((plaintext_size + AES_BLOCK_SIZE) // AES_BLOCK_SIZE) * AES_BLOCK_SIZE


def _aes_ecb_encrypt(plaintext: bytes, key: bytes) -> bytes:
    """Encrypt with AES-128-ECB (PKCS7 padding).

    Uses the standard library's PEP 272 interface when available.
    Falls back to the `cryptography` package.
    """
    try:
        from Crypto.Cipher import AES as PyAES
        cipher = PyAES.new(key, PyAES.MODE_ECB)
        # Manual PKCS7 padding
        pad_len = AES_BLOCK_SIZE - (len(plaintext) % AES_BLOCK_SIZE)
        padded = plaintext + bytes([pad_len] * pad_len)
        return cipher.encrypt(padded)
    except ImportError:
        pass

    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        from cryptography.hazmat.backends import default_backend
        backend = default_backend()
        cipher = Cipher(algorithms.AES(key), modes.ECB(), backend=backend)
        encryptor = cipher.encryptor()
        # PKCS7 padding
        pad_len = AES_BLOCK_SIZE - (len(plaintext) % AES_BLOCK_SIZE)
        padded = plaintext + bytes([pad_len] * pad_len)
        return encryptor.update(padded) + encryptor.finalize()
    except ImportError:
        raise ImportError(
            "AES encryption requires either `pycryptodome` or `cryptography` package. "
            "Install with: pip install pycryptodome"
        )


async def get_upload_url(
    base_url: str,
    token: str,
    filekey: str,
    to_user_id: str,
    rawsize: int,
    rawfilemd5: str,
    filesize: int,
    aeskey_hex: str,
    media_type: int = UPLOAD_MEDIA_TYPE_IMAGE,
) -> dict:
    """Get a pre-signed CDN upload URL from the iLink API.

    Returns the parsed JSON response containing upload_full_url and/or upload_param.
    """
    url = f"{base_url.rstrip('/')}/ilink/bot/getuploadurl"
    headers = build_headers(token)
    body = {
        "filekey": filekey,
        "media_type": media_type,
        "to_user_id": to_user_id,
        "rawsize": rawsize,
        "rawfilemd5": rawfilemd5,
        "filesize": filesize,
        "no_need_thumb": True,
        "aeskey": aeskey_hex,
    }

    async with httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=10.0)) as client:
        resp = await client.post(url, json=body, headers=headers)
        resp.raise_for_status()
        return resp.json()


async def upload_to_cdn(
    plaintext: bytes,
    upload_full_url: str | None,
    upload_param: str | None,
    cdn_base_url: str,
    filekey: str,
    aeskey: bytes,
) -> str:
    """Upload encrypted file to the Weixin CDN.

    Encrypts the plaintext with AES-128-ECB, then POSTs to the CDN.
    Returns the download encrypted_query_param from the x-encrypted-param header.
    Retries up to CDN_UPLOAD_MAX_RETRIES on server errors.
    """
    import logging
    logger = logging.getLogger(__name__)

    ciphertext = _aes_ecb_encrypt(plaintext, aeskey)

    # Determine CDN upload URL
    trimmed_full = upload_full_url.strip() if upload_full_url else ""
    if trimmed_full:
        upload_url = trimmed_full
    elif upload_param:
        upload_url = (
            f"{cdn_base_url.rstrip('/')}/upload"
            f"?encrypted_query_param={upload_param}&filekey={filekey}"
        )
    else:
        raise ValueError("CDN upload URL missing (need upload_full_url or upload_param)")

    logger.debug("CDN POST url=%s... ciphertextSize=%d", upload_url[:80], len(ciphertext))
    if len(ciphertext) > 1024 * 1024:
        logger.debug("CDN POST url=%s ciphertextSize=%d", upload_url[:80], len(ciphertext))

    download_param: str | None = None
    last_error: Exception | None = None

    for attempt in range(1, CDN_UPLOAD_MAX_RETRIES + 1):
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0)) as client:
                resp = await client.post(
                    upload_url,
                    content=ciphertext,
                    headers={"Content-Type": "application/octet-stream"},
                )

            if 400 <= resp.status_code < 500:
                err_msg = resp.headers.get("x-error-message", resp.text)
                logger.error(
                    "CDN client error attempt=%d status=%d err=%s",
                    attempt, resp.status_code, err_msg,
                )
                raise RuntimeError(f"CDN upload client error {resp.status_code}: {err_msg}")

            if resp.status_code != 200:
                err_msg = resp.headers.get("x-error-message", f"status {resp.status_code}")
                logger.error(
                    "CDN server error attempt=%d status=%d err=%s",
                    attempt, resp.status_code, err_msg,
                )
                raise RuntimeError(f"CDN upload server error: {err_msg}")

            download_param = resp.headers.get("x-encrypted-param")
            if not download_param:
                logger.error("CDN response missing x-encrypted-param header attempt=%d", attempt)
                raise RuntimeError("CDN upload response missing x-encrypted-param header")

            logger.debug("CDN upload success attempt=%d", attempt)
            break

        except RuntimeError:
            raise
        except Exception as exc:
            last_error = exc
            if attempt < CDN_UPLOAD_MAX_RETRIES:
                logger.error("CDN attempt %d failed, retrying... err=%s", attempt, exc)
            else:
                logger.error("CDN all %d attempts failed err=%s", CDN_UPLOAD_MAX_RETRIES, exc)

    if not download_param:
        if last_error:
            raise last_error
        raise RuntimeError(f"CDN upload failed after {CDN_UPLOAD_MAX_RETRIES} attempts")

    return download_param


async def send_image_message(
    base_url: str,
    token: str,
    to_user_id: str,
    image_path: str,
    context_token: str = "",
    cdn_base_url: str = "",
) -> str:
    """Upload a local image file to the Weixin CDN and send it as a message.

    Full pipeline: hash → getUploadUrl → AES encrypt → CDN upload → sendMessage.
    Returns the message client_id.
    """
    import logging
    logger = logging.getLogger(__name__)

    from asuna.ilink.types import MessageItemType

    # 1. Read and hash the file
    with open(image_path, "rb") as f:
        plaintext = f.read()

    rawsize = len(plaintext)
    rawfilemd5 = hashlib.md5(plaintext).hexdigest()
    filesize = _aes_ecb_padded_size(rawsize)
    filekey = os.urandom(16).hex()
    aeskey = os.urandom(16)
    aeskey_hex = aeskey.hex()

    logger.debug(
        "send_image_message: %s rawsize=%d filesize=%d md5=%s filekey=%s",
        image_path, rawsize, filesize, rawfilemd5, filekey,
    )

    # 2. Get pre-signed CDN upload URL
    upload_resp = await get_upload_url(
        base_url=base_url,
        token=token,
        filekey=filekey,
        to_user_id=to_user_id,
        rawsize=rawsize,
        rawfilemd5=rawfilemd5,
        filesize=filesize,
        aeskey_hex=aeskey_hex,
    )

    # 3. Upload to CDN (encrypts internally)
    if not cdn_base_url:
        cdn_base_url = base_url

    download_param = await upload_to_cdn(
        plaintext=plaintext,
        upload_full_url=upload_resp.get("upload_full_url", ""),
        upload_param=upload_resp.get("upload_param", ""),
        cdn_base_url=cdn_base_url,
        filekey=filekey,
        aeskey=aeskey,
    )

    # 4. Build IMAGE MessageItem and send
    import base64 as b64
    image_item = {
        "type": MessageItemType.IMAGE,
        "image_item": {
            "media": {
                "encrypt_query_param": download_param,
                "aes_key": b64.b64encode(aeskey).decode(),
                "encrypt_type": 1,
            },
            "mid_size": filesize,
        },
    }

    logger.info("send_image_message: sending to %s file=%s", to_user_id[:20], image_path)
    return await send_message(
        base_url=base_url,
        token=token,
        to_user_id=to_user_id,
        text="",
        context_token=context_token,
        image_item=image_item,
    )
