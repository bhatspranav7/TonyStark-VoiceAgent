"""Sleep / wake handling.

FRIDAY starts awake. Telling her to go to sleep makes her ignore everything she
hears until someone says her name or "wake up".
"""

import re
from enum import Enum

WAKE_RE = re.compile(r"\b(friday|wake up)\b", re.IGNORECASE)
SLEEP_RE = re.compile(
    r"\b(go to sleep|sleep mode|stand ?by|stop listening|that'?s all for now)\b",
    re.IGNORECASE,
)


class Heard(Enum):
    RESPOND = "respond"  # awake, answer normally
    IGNORED = "ignored"  # asleep and no wake word: say nothing
    WOKE = "woke"  # asleep and heard the wake word: answer
    SLEPT = "slept"  # just told to sleep: acknowledge, then go quiet


class WakeGate:
    def __init__(self) -> None:
        self.asleep = False

    def hear(self, text: str) -> Heard:
        """Update the sleep state from one user utterance and say how to treat it."""
        if self.asleep:
            if WAKE_RE.search(text):
                self.asleep = False
                return Heard.WOKE
            return Heard.IGNORED
        if SLEEP_RE.search(text):
            self.asleep = True
            return Heard.SLEPT
        return Heard.RESPOND
