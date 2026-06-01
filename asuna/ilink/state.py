"""State persistence for iLink accounts and sync buffers.

Translated from @tencent-weixin/openclaw-weixin src/auth/accounts.ts + src/storage/sync-buf.ts
"""

import json
import os
from pathlib import Path

DATA_DIR = Path("data")


def _ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


# -- Account credentials ------------------------------------------------------

def save_account(token: str, account_id: str, base_url: str = "", user_id: str = "") -> None:
    _ensure_data_dir()
    data = {
        "token": token,
        "account_id": account_id,
        "base_url": base_url or "https://ilinkai.weixin.qq.com",
        "user_id": user_id,
    }
    with open(DATA_DIR / "account.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_account() -> dict | None:
    path = DATA_DIR / "account.json"
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def delete_account() -> None:
    path = DATA_DIR / "account.json"
    if path.exists():
        path.unlink()


# -- Sync buffer (get_updates_buf) --------------------------------------------

def save_sync_buf(account_id: str, buf: str) -> None:
    _ensure_data_dir()
    data = {}
    path = DATA_DIR / "sync_buf.json"
    if path.exists():
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    data[account_id] = buf
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


def load_sync_buf(account_id: str) -> str:
    path = DATA_DIR / "sync_buf.json"
    if not path.exists():
        return ""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data.get(account_id, "")
    except (json.JSONDecodeError, OSError):
        return ""


# -- Context tokens (per-user session identifiers) ----------------------------

def save_context_token(account_id: str, user_id: str, token: str) -> None:
    _ensure_data_dir()
    path = DATA_DIR / "context_tokens.json"
    data: dict = {}
    if path.exists():
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    key = f"{account_id}:{user_id}"
    data[key] = token
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


def get_context_token(account_id: str, user_id: str) -> str:
    path = DATA_DIR / "context_tokens.json"
    if not path.exists():
        return ""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data.get(f"{account_id}:{user_id}", "")
    except (json.JSONDecodeError, OSError):
        return ""


def clear_context_tokens(account_id: str) -> None:
    path = DATA_DIR / "context_tokens.json"
    if not path.exists():
        return
    try:
        with open(path, encoding="utf-8") as f:
            data: dict = json.load(f)
        data = {k: v for k, v in data.items() if not k.startswith(f"{account_id}:")}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    except (json.JSONDecodeError, OSError):
        pass
