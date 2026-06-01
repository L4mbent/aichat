import time
from dataclasses import dataclass, field


@dataclass
class ConversationTurn:
    user_msg: str
    asst_reply: str
    timestamp: float = field(default_factory=time.time)


class ConversationHistory:
    def __init__(self, max_turns: int = 30, max_token_estimate: int = 32_000) -> None:
        self.turns: list[ConversationTurn] = []
        self.max_turns = max_turns
        self.max_token_estimate = max_token_estimate

    def add(self, user_msg: str, asst_reply: str) -> None:
        self.turns.append(ConversationTurn(user_msg=user_msg, asst_reply=asst_reply))
        self._trim()

    def _trim(self) -> None:
        while len(self.turns) > self.max_turns:
            self.turns.pop(0)

        total_est = sum(len(t.user_msg) + len(t.asst_reply) for t in self.turns) // 4
        while total_est > self.max_token_estimate and len(self.turns) > 10:
            self.turns.pop(0)
            total_est = sum(len(t.user_msg) + len(t.asst_reply) for t in self.turns) // 4

    def get_messages(self) -> list[dict[str, str]]:
        msgs: list[dict[str, str]] = []
        for t in self.turns:
            msgs.append({"role": "user", "content": t.user_msg})
            msgs.append({"role": "assistant", "content": t.asst_reply})
        return msgs

    def get_recent_turns(self, n: int) -> list[ConversationTurn]:
        return self.turns[-n:] if n > 0 else []

    @property
    def turn_count(self) -> int:
        return len(self.turns)

    def clear(self) -> None:
        self.turns.clear()
