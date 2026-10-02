"""Name activation.

FRIDAY hears everything the microphone picks up, so she only answers speech that
is addressed to her by name ("Friday, what's the news?"). Anything else — people
talking nearby, a video, her own voice coming back through the speakers — is ignored.

Optionally she keeps listening for a few seconds after each answer, so a follow-up
question does not need her name again (FRIDAY_FOLLOW_UP_SECONDS).
"""

import re
import time
from collections.abc import Callable, Iterable
from enum import Enum

# Said to her by name (or during a follow-up window), these end the exchange.
DISMISS_RE = re.compile(
    r"\b(go to sleep|sleep mode|stand ?by|stop listening|stop talking|that'?s all|"
    r"never ?mind|be quiet|shut up)\b",
    re.IGNORECASE,
)
# On their own after her name ("Friday, stop"), these mean the same.
DISMISS_WORDS = {"stop", "enough", "cancel", "quiet", "thanks", "thank you"}


class Heard(Enum):
    RESPOND = "respond"  # addressed to her: answer
    IGNORED = "ignored"  # not addressed to her: say nothing
    DISMISSED = "dismissed"  # told to stop: acknowledge briefly, then go quiet


class WakeGate:
    def __init__(
        self,
        wake_words: Iterable[str] = ("friday",),
        follow_up_seconds: float = 0.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        words = "|".join(re.escape(w.strip()) for w in wake_words if w.strip())
        self._wake_re = re.compile(rf"\b(?:hey\s+|ok(?:ay)?\s+)?(?:{words})\b", re.IGNORECASE)
        self._follow_up_seconds = follow_up_seconds
        self._clock = clock
        self._listening_until = 0.0
        self._dismissed = False

    @property
    def in_follow_up(self) -> bool:
        """True while she is still listening after her last answer."""
        return self._clock() < self._listening_until

    def hear(self, text: str) -> Heard:
        """Decide how to treat one thing the user said."""
        addressed = bool(self._wake_re.search(text))
        if not addressed and not self.in_follow_up:
            return Heard.IGNORED

        remainder = re.sub(r"[^\w\s']", " ", self._wake_re.sub(" ", text)).strip().lower()
        if DISMISS_RE.search(text) or " ".join(remainder.split()) in DISMISS_WORDS:
            self._listening_until = 0.0
            self._dismissed = True
            return Heard.DISMISSED
        return Heard.RESPOND

    def answered(self) -> None:
        """Call when she finishes speaking: opens the follow-up window, if one is configured."""
        if self._dismissed:
            self._dismissed = False  # that was her "standing by", not an answer
        elif self._follow_up_seconds > 0:
            self._listening_until = self._clock() + self._follow_up_seconds
