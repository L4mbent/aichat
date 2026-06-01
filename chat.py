#!/usr/bin/env python
"""Interactive test console for Asuna AI Agent."""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from asuna.llm.client import get_ai_response
from asuna.llm.history import ConversationHistory


async def main():
    history = ConversationHistory()

    print("=" * 50)
    print("  结城明日奈 (Yuuki Asuna) - 交互测试")
    print("  输入 /quit 退出, /clear 清除记忆")
    print("=" * 50)
    print()

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


if __name__ == "__main__":
    asyncio.run(main())
