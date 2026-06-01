"""QR code login flow for WeChat ClawBot.

Starts a temporary HTTP server to display the QR code image, polls for
scan confirmation, then saves the bot token and account info.

Translated from @tencent-weixin/openclaw-weixin src/auth/login-qr.ts
"""

import asyncio
import logging
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

from asuna.config import settings
from asuna.ilink.api import fetch_bot_qrcode, poll_qrcode_status
from asuna.ilink.state import delete_account, save_account

logger = logging.getLogger(__name__)

LOGIN_PORT = 8787
LOGIN_TIMEOUT_MS = 480_000  # 8 minutes
POLL_INTERVAL_S = 1

_LOGIN_PAGE_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Asuna - 微信登录</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
  font-family: 'Segoe UI', 'Microsoft YaHei', sans-serif;
  background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
  min-height: 100vh;
  display: flex; justify-content: center; align-items: center;
  color: #e8e8e8;
}
.card {
  background: rgba(255,255,255,0.06);
  border-radius: 20px;
  padding: 40px;
  text-align: center;
  border: 1px solid rgba(255,255,255,0.1);
  backdrop-filter: blur(10px);
  max-width: 420px;
  width: 90%;
}
h1 { color: #e94560; font-size: 1.6em; margin-bottom: 8px; }
p.sub { color: rgba(255,255,255,0.5); font-size: 0.9em; margin-bottom: 24px; }
.qr-box {
  background: #fff;
  border-radius: 12px;
  padding: 16px;
  display: inline-block;
  margin-bottom: 20px;
}
.qr-box img { width: 200px; height: 200px; }
.status {
  font-size: 0.95em;
  padding: 10px 20px;
  border-radius: 25px;
  display: inline-block;
}
.status.waiting { background: rgba(255,255,255,0.08); color: #aaa; }
.status.scanned { background: rgba(233, 196, 106, 0.2); color: #e9c46a; }
.status.confirmed { background: rgba(42, 157, 143, 0.2); color: #2a9d8f; }
.status.expired { background: rgba(231, 111, 81, 0.2); color: #e76f51; }
</style>
</head>
<body>
<div class="card">
  <h1>Asuna</h1>
  <p class="sub">结城明日奈 · Yuuki Asuna</p>
  <div class="qr-box">
    <img id="qrImg" src="" alt="QR Code" />
  </div>
  <div id="statusEl" class="status waiting">请用微信扫描二维码</div>
</div>
<script>
const STATUS_URL = "/status";
let lastStatus = "";
async function poll() {
  try {
    const resp = await fetch(STATUS_URL);
    const data = await resp.json();
    if (data.status !== lastStatus) {
      lastStatus = data.status;
      const el = document.getElementById("statusEl");
      switch (data.status) {
        case "wait":
          el.className = "status waiting";
          el.textContent = "请用微信扫描二维码";
          break;
        case "scaned":
          el.className = "status scanned";
          el.textContent = "已扫描，请在手机上确认...";
          break;
        case "confirmed":
          el.className = "status confirmed";
          el.textContent = "登录成功！Asuna 已连接到微信";
          clearInterval(timer);
          return;
        case "expired":
          el.className = "status expired";
          el.textContent = "二维码已过期，请刷新页面重试";
          clearInterval(timer);
          return;
      }
    }
  } catch (e) {}
}
const timer = setInterval(poll, 1500);
</script>
</body>
</html>"""


class _LoginState:
    def __init__(self) -> None:
        self.qrcode_url: str = ""
        self.qrcode: str = ""
        self.status: str = "wait"
        self.bot_token: str = ""
        self.account_id: str = ""
        self.base_url: str = ""
        self.user_id: str = ""
        self.error: str = ""


class _LoginHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/" or self.path == "/index.html":
            html = _LOGIN_PAGE_HTML.replace('src=""', f'src="{self.server.login_state.qrcode_url}"')
            self._send_html(html)
        elif self.path == "/status":
            state = self.server.login_state
            self._send_json({
                "status": state.status,
                "error": state.error,
            })
        else:
            self.send_response(404)
            self.end_headers()

    def _send_html(self, content: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(content.encode("utf-8"))

    def _send_json(self, data: dict) -> None:
        import json
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode("utf-8"))

    def log_message(self, format, *args):
        pass  # Suppress HTTP server logs


def _run_temp_server(login_state: _LoginState, stop_event: threading.Event) -> None:
    server = HTTPServer(("0.0.0.0", LOGIN_PORT), _LoginHandler)
    server.login_state = login_state
    server.timeout = 1

    while not stop_event.is_set():
        server.handle_request()


async def run_login_flow(api_base_url: str = "") -> dict:
    """Run the complete QR code login flow.

    1. Fetch QR code from iLink
    2. Start a temporary HTTP server showing the QR image
    3. Poll for scan confirmation
    4. Save credentials and return account info
    """
    base_url = api_base_url or settings.ILINK_BASE_URL

    # Step 1: Fetch QR code
    logger.info("Fetching QR code from %s ...", base_url)
    qr_data = await fetch_bot_qrcode(base_url)
    qrcode = qr_data.get("qrcode", "")
    qrcode_url = qr_data.get("qrcode_img_content", "")

    if not qrcode or not qrcode_url:
        raise RuntimeError(f"Failed to get QR code: {qr_data}")

    logger.info("QR code obtained, starting login server on port %d", LOGIN_PORT)

    # Step 2: Start temporary HTTP server
    login_state = _LoginState()
    login_state.qrcode = qrcode
    login_state.qrcode_url = qrcode_url

    stop_event = threading.Event()
    server_thread = threading.Thread(
        target=_run_temp_server,
        args=(login_state, stop_event),
        daemon=True,
    )
    server_thread.start()

    print(f"\n{'=' * 55}")
    print(f"  打开浏览器访问: http://localhost:{LOGIN_PORT}")
    print(f"  用手机微信扫描页面上的二维码")
    print(f"{'=' * 55}\n")

    # Step 3: Poll for scan confirmation
    deadline = time.time() + (LOGIN_TIMEOUT_MS / 1000)
    scanned_printed = False

    try:
        while time.time() < deadline:
            status_resp = await poll_qrcode_status(base_url, qrcode, timeout=35)
            login_state.status = status_resp.status

            if status_resp.status == "scaned":
                if not scanned_printed:
                    print("  -> 已扫描，请在手机上确认...")
                    scanned_printed = True

            elif status_resp.status == "confirmed":
                login_state.bot_token = status_resp.bot_token
                login_state.account_id = status_resp.ilink_bot_id
                login_state.base_url = status_resp.baseurl or base_url
                login_state.user_id = status_resp.ilink_user_id

                if not status_resp.ilink_bot_id:
                    login_state.status = "error"
                    login_state.error = "登录失败：服务器未返回 bot ID"
                    break

                # Save credentials
                save_account(
                    token=status_resp.bot_token,
                    account_id=status_resp.ilink_bot_id,
                    base_url=status_resp.baseurl or base_url,
                    user_id=status_resp.ilink_user_id,
                )

                print("  -> 登录成功!")
                print(f"     Bot ID: {status_resp.ilink_bot_id}")
                print(f"     User ID: {status_resp.ilink_user_id}")

                # Brief pause so the browser can see the confirmed state
                await asyncio.sleep(2)
                break

            elif status_resp.status == "expired":
                login_state.status = "expired"
                print("  -> 二维码已过期，请重新运行 login")
                break

            elif status_resp.status == "scaned_but_redirect":
                if status_resp.redirect_host:
                    new_base = f"https://{status_resp.redirect_host}"
                    logger.info("IDC redirect to %s", new_base)
                    base_url = new_base

            elif status_resp.status == "binded_redirect":
                print("  -> 已连接过此 OpenClaw，无需重复连接")
                login_state.status = "confirmed"
                break

            await asyncio.sleep(POLL_INTERVAL_S)

    finally:
        stop_event.set()
        await asyncio.sleep(0.3)  # Let server thread exit

    if login_state.status == "confirmed":
        return {
            "success": True,
            "bot_token": login_state.bot_token,
            "account_id": login_state.account_id,
            "base_url": login_state.base_url,
            "user_id": login_state.user_id,
        }
    else:
        return {
            "success": False,
            "error": login_state.error or f"登录未完成 (状态: {login_state.status})",
        }
