"""Sleep / wake gate."""

import pytest

from friday.wake import Heard, WakeGate


def test_starts_awake_and_responds():
    gate = WakeGate()
    assert gate.hear("What's the news?") is Heard.RESPOND
    assert not gate.asleep


@pytest.mark.parametrize(
    "phrase",
    ["Go to sleep", "friday, stand by", "Standby please", "Stop listening.", "That's all for now"],
)
def test_sleep_phrases_put_her_to_sleep(phrase):
    gate = WakeGate()
    assert gate.hear(phrase) is Heard.SLEPT
    assert gate.asleep


def test_ignores_everything_while_asleep_until_wake_word():
    gate = WakeGate()
    gate.hear("go to sleep")
    assert gate.hear("what time is it") is Heard.IGNORED
    assert gate.hear("go to sleep") is Heard.IGNORED
    assert gate.asleep
    assert gate.hear("Hey Friday, what time is it?") is Heard.WOKE
    assert not gate.asleep
    assert gate.hear("and the news?") is Heard.RESPOND


def test_wake_up_phrase_also_wakes():
    gate = WakeGate()
    gate.hear("sleep mode")
    assert gate.hear("Wake up!") is Heard.WOKE


def test_wake_word_must_be_a_whole_word():
    gate = WakeGate()
    gate.hear("go to sleep")
    assert gate.hear("fridays are great") is Heard.IGNORED
