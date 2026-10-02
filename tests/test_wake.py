"""Name activation: FRIDAY answers only when addressed."""

import pytest

from friday.wake import Heard, WakeGate


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.mark.parametrize(
    "speech",
    [
        "What's the news?",
        "so I told him it was fine",
        "go to sleep",
        "fridays are the best day of the week",
        "",
    ],
)
def test_speech_without_her_name_is_ignored(speech):
    assert WakeGate().hear(speech) is Heard.IGNORED


@pytest.mark.parametrize(
    "speech",
    [
        "Friday, what's the news?",
        "hey friday what time is it",
        "What's the weather like, Friday?",
        "FRIDAY.",
        "Okay Friday, search for Python.",
    ],
)
def test_speech_with_her_name_is_answered(speech):
    assert WakeGate().hear(speech) is Heard.RESPOND


def test_she_needs_her_name_every_time_by_default():
    gate = WakeGate()
    assert gate.hear("Friday, catch me up") is Heard.RESPOND
    gate.answered()
    assert gate.hear("tell me more about the first one") is Heard.IGNORED


@pytest.mark.parametrize(
    "speech",
    [
        "Friday, go to sleep",
        "Friday stop",
        "Friday, stop talking.",
        "Friday, that's all for now",
        "never mind, Friday",
        "Thanks, Friday.",
        "Friday, stand by",
    ],
)
def test_dismissals_addressed_to_her(speech):
    assert WakeGate().hear(speech) is Heard.DISMISSED


def test_a_request_that_merely_contains_stop_is_still_answered():
    assert WakeGate().hear("Friday, when does the bus stop running?") is Heard.RESPOND


def test_custom_wake_words_and_stt_spellings():
    gate = WakeGate(wake_words=["friday", "fri day", "jarvis"])
    assert gate.hear("Fri day, hello") is Heard.RESPOND
    assert gate.hear("Jarvis, hello") is Heard.RESPOND
    assert gate.hear("Monday, hello") is Heard.IGNORED


def test_follow_up_window_lets_her_answer_without_the_name_for_a_while():
    clock = FakeClock()
    gate = WakeGate(follow_up_seconds=10, clock=clock)

    assert gate.hear("tell me more") is Heard.IGNORED  # nothing asked yet
    assert gate.hear("Friday, catch me up") is Heard.RESPOND
    assert not gate.in_follow_up  # the window opens when she finishes speaking
    gate.answered()

    clock.now += 9
    assert gate.hear("tell me more about the first one") is Heard.RESPOND
    gate.answered()
    clock.now += 11
    assert gate.hear("and the second one") is Heard.IGNORED


def test_dismissal_closes_the_follow_up_window():
    clock = FakeClock()
    gate = WakeGate(follow_up_seconds=30, clock=clock)
    gate.hear("Friday, catch me up")
    gate.answered()

    assert gate.hear("that's all") is Heard.DISMISSED
    gate.answered()  # she finishes saying "Standing by": must not reopen the window
    assert gate.hear("actually one more thing") is Heard.IGNORED

    assert gate.hear("Friday, one more thing") is Heard.RESPOND
    gate.answered()
    assert gate.in_follow_up
