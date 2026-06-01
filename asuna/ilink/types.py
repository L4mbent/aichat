"""WeChat iLink ClawBot protocol types.

Translated from @tencent-weixin/openclaw-weixin src/api/types.ts
"""

from dataclasses import dataclass, field


# -- Message type enums -------------------------------------------------------

class MessageType:
    NONE = 0
    USER = 1
    BOT = 2


class MessageItemType:
    NONE = 0
    TEXT = 1
    IMAGE = 2
    VOICE = 3
    FILE = 4
    VIDEO = 5
    TOOL_CALL_START = 11
    TOOL_CALL_RESULT = 12


class MessageState:
    NEW = 0
    GENERATING = 1
    FINISH = 2


class TypingStatus:
    TYPING = 1
    CANCEL = 2


# -- Sub-items ----------------------------------------------------------------

@dataclass
class TextItem:
    text: str = ""


@dataclass
class CDNMedia:
    encrypt_query_param: str = ""
    aes_key: str = ""
    encrypt_type: int = 0
    full_url: str = ""


@dataclass
class ImageItem:
    media: CDNMedia | None = None
    thumb_media: CDNMedia | None = None
    aeskey: str = ""
    url: str = ""
    mid_size: int = 0
    thumb_size: int = 0
    thumb_height: int = 0
    thumb_width: int = 0
    hd_size: int = 0


@dataclass
class VoiceItem:
    media: CDNMedia | None = None
    encode_type: int = 0
    bits_per_sample: int = 0
    sample_rate: int = 0
    playtime: int = 0
    text: str = ""


@dataclass
class FileItem:
    media: CDNMedia | None = None
    file_name: str = ""
    md5: str = ""
    len: str = ""


@dataclass
class VideoItem:
    media: CDNMedia | None = None
    video_size: int = 0
    play_length: int = 0
    video_md5: str = ""
    thumb_media: CDNMedia | None = None
    thumb_size: int = 0
    thumb_height: int = 0
    thumb_width: int = 0


@dataclass
class RefMessage:
    message_item: "MessageItem | None" = None
    title: str = ""


@dataclass
class ToolCallStartItem:
    tool_name: str = ""
    tool_call_id: str = ""


@dataclass
class ToolCallResultItem:
    tool_name: str = ""
    tool_call_id: str = ""
    status: str = ""


@dataclass
class MessageItem:
    type: int = 0
    create_time_ms: int = 0
    update_time_ms: int = 0
    is_completed: bool = False
    msg_id: str = ""
    ref_msg: RefMessage | None = None
    text_item: TextItem | None = None
    image_item: ImageItem | None = None
    voice_item: VoiceItem | None = None
    file_item: FileItem | None = None
    video_item: VideoItem | None = None
    tool_call_start_item: ToolCallStartItem | None = None
    tool_call_result_item: ToolCallResultItem | None = None


# -- Top-level message --------------------------------------------------------

@dataclass
class WeixinMessage:
    seq: int = 0
    message_id: int = 0
    from_user_id: str = ""
    to_user_id: str = ""
    client_id: str = ""
    create_time_ms: int = 0
    update_time_ms: int = 0
    delete_time_ms: int = 0
    session_id: str = ""
    group_id: str = ""
    message_type: int = 0
    message_state: int = 0
    item_list: list[MessageItem] = field(default_factory=list)
    context_token: str = ""
    run_id: str = ""


# -- API request / response types ---------------------------------------------

@dataclass
class GetUpdatesResp:
    ret: int = 0
    errcode: int = 0
    errmsg: str = ""
    msgs: list[WeixinMessage] = field(default_factory=list)
    get_updates_buf: str = ""
    longpolling_timeout_ms: int = 0


@dataclass
class SendMessageReq:
    msg: WeixinMessage = field(default_factory=WeixinMessage)


@dataclass
class SendTypingReq:
    ilink_user_id: str = ""
    typing_ticket: str = ""
    status: int = TypingStatus.TYPING


@dataclass
class GetConfigResp:
    ret: int = 0
    errmsg: str = ""
    typing_ticket: str = ""


@dataclass
class QRCodeStatus:
    status: str = ""          # wait | scaned | confirmed | expired | need_verifycode | ...
    bot_token: str = ""
    ilink_bot_id: str = ""
    baseurl: str = ""
    ilink_user_id: str = ""
    redirect_host: str = ""


# -- Helpers ------------------------------------------------------------------

def extract_text(msg: WeixinMessage) -> str:
    """Extract plain text content from a WeixinMessage's item_list."""
    parts: list[str] = []
    for item in msg.item_list:
        if item.type == MessageItemType.TEXT and item.text_item:
            parts.append(item.text_item.text)
    return "".join(parts)
