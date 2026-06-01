import asyncio
import sys
import os
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from asuna.llm.client import get_ai_response
from asuna.llm.history import ConversationHistory

app = FastAPI()

sessions: dict[str, ConversationHistory] = {}


@app.get("/", response_class=HTMLResponse)
async def index():
    return """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>结城明日奈 - Asuna AI</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
  font-family: 'Segoe UI', 'Microsoft YaHei', sans-serif;
  background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
  min-height: 100vh;
  display: flex;
  justify-content: center;
  align-items: center;
}
.chat-container {
  width: 100%;
  max-width: 700px;
  height: 95vh;
  background: rgba(255,255,255,0.05);
  border-radius: 20px;
  backdrop-filter: blur(10px);
  border: 1px solid rgba(255,255,255,0.1);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.chat-header {
  padding: 20px;
  text-align: center;
  border-bottom: 1px solid rgba(255,255,255,0.1);
  background: rgba(255,255,255,0.03);
}
.chat-header h1 { color: #e94560; font-size: 1.5em; margin-bottom: 4px; }
.chat-header p { color: rgba(255,255,255,0.5); font-size: 0.85em; }
.chat-messages {
  flex: 1;
  overflow-y: auto;
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.message {
  max-width: 85%;
  padding: 12px 16px;
  border-radius: 16px;
  line-height: 1.6;
  font-size: 0.95em;
  animation: fadeIn 0.3s ease;
}
@keyframes fadeIn { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: translateY(0); } }
.message.user {
  align-self: flex-end;
  background: linear-gradient(135deg, #e94560, #c23152);
  color: white;
  border-bottom-right-radius: 4px;
}
.message.assistant {
  align-self: flex-start;
  background: rgba(255,255,255,0.1);
  color: #e8e8e8;
  border-bottom-left-radius: 4px;
}
.message .label {
  font-size: 0.7em;
  opacity: 0.7;
  margin-bottom: 4px;
  display: block;
}
.chat-input-area {
  padding: 16px 20px;
  border-top: 1px solid rgba(255,255,255,0.1);
  display: flex;
  gap: 10px;
  background: rgba(255,255,255,0.03);
}
.chat-input-area input {
  flex: 1;
  padding: 12px 16px;
  border-radius: 25px;
  border: 1px solid rgba(255,255,255,0.2);
  background: rgba(255,255,255,0.08);
  color: #fff;
  font-size: 0.95em;
  outline: none;
  transition: border-color 0.2s;
}
.chat-input-area input:focus { border-color: #e94560; }
.chat-input-area button {
  padding: 12px 24px;
  border-radius: 25px;
  border: none;
  background: linear-gradient(135deg, #e94560, #c23152);
  color: white;
  font-size: 0.95em;
  cursor: pointer;
  transition: transform 0.15s, opacity 0.15s;
}
.chat-input-area button:hover { transform: scale(1.03); }
.chat-input-area button:disabled { opacity: 0.5; transform: none; cursor: default; }
.typing { color: rgba(255,255,255,0.4); font-size: 0.85em; padding: 4px 12px; }
</style>
</head>
<body>
<div class="chat-container">
  <div class="chat-header">
    <h1>⚔️ 结城明日奈</h1>
    <p>Yuuki Asuna · 血盟骑士团副团长 · 闪光</p>
  </div>
  <div class="chat-messages" id="messages">
    <div class="message assistant">
      <span class="label">Asuna</span>
      Hai! 我是结城明日奈。你是通过聊天界面找到我的吗？很高兴认识你。有什么想聊的都可以跟我说哦~
    </div>
  </div>
  <div class="chat-input-area">
    <input id="userInput" placeholder="输入消息..." autofocus />
    <button id="sendBtn" onclick="sendMessage()">发送</button>
  </div>
</div>
<script>
const sessionId = 'web-' + Date.now();
const messagesDiv = document.getElementById('messages');
const input = document.getElementById('userInput');
const btn = document.getElementById('sendBtn');

input.addEventListener('keydown', e => { if (e.key === 'Enter') sendMessage(); });

async function sendMessage() {
  const text = input.value.trim();
  if (!text) return;

  addMessage('user', '你', text);
  input.value = '';
  btn.disabled = true;

  const typing = addTyping();
  messagesDiv.scrollTop = messagesDiv.scrollHeight;

  try {
    const resp = await fetch('/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: sessionId, message: text }),
    });
    const data = await resp.json();
    typing.remove();
    addMessage('assistant', 'Asuna', data.reply);
  } catch (e) {
    typing.remove();
    addMessage('assistant', 'Asuna', 'Eeto...抱歉，刚才连接断开了。可以再说一次吗？');
  } finally {
    btn.disabled = false;
    input.focus();
    messagesDiv.scrollTop = messagesDiv.scrollHeight;
  }
}

function addMessage(role, label, text) {
  const div = document.createElement('div');
  div.className = 'message ' + role;
  div.innerHTML = '<span class="label">' + label + '</span>' + text.replace(/\\n/g, '<br>');
  messagesDiv.appendChild(div);
  messagesDiv.scrollTop = messagesDiv.scrollHeight;
}

function addTyping() {
  const div = document.createElement('div');
  div.className = 'typing';
  div.textContent = 'Asuna 正在输入...';
  messagesDiv.appendChild(div);
  return div;
}
</script>
</body>
</html>"""


@app.post("/chat")
async def chat(request: Request):
    data = await request.json()
    session_id = data.get("session_id", "default")
    message = data.get("message", "").strip()

    if not message:
        return {"reply": "Eeto...你好像没有说话呢？"}

    if session_id not in sessions:
        sessions[session_id] = ConversationHistory()

    history = sessions[session_id]
    reply = await get_ai_response(message, history)
    return {"reply": reply}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
