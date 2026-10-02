"""The voice agent's handling of what the microphone hears."""

import pytest
from livekit.agents import StopResponse, llm

from friday.agent import DISMISSED_LINE, Friday


class FakeSession:
    def __init__(self) -> None:
        self.said: list[str] = []

    def say(self, text: str) -> None:
        self.said.append(text)


class FridayUnderTest(Friday):
    """Friday with the live session swapped for a recorder."""

    def __init__(self) -> None:
        self.dismissals = 0
        self.fake_session = FakeSession()
        super().__init__(on_dismissed=self._count_dismissal)

    def _count_dismissal(self) -> None:
        self.dismissals += 1

    session = property(lambda self: self.fake_session)


async def hears(agent: Friday, speech: str) -> None:
    message = llm.ChatMessage(role="user", content=[speech])
    await agent.on_user_turn_completed(llm.ChatContext.empty(), message)


async def test_speech_addressed_to_friday_goes_on_to_the_llm():
    agent = FridayUnderTest()
    await hears(agent, "Friday, what's the news?")  # no StopResponse: the reply proceeds
    assert agent.fake_session.said == []


@pytest.mark.parametrize("speech", ["what's the news?", "so anyway I said no", ""])
async def test_background_speech_gets_no_reply_at_all(speech):
    agent = FridayUnderTest()
    with pytest.raises(StopResponse):
        await hears(agent, speech)
    assert agent.fake_session.said == []
    assert agent.dismissals == 0


async def test_being_told_to_stop_gets_a_short_acknowledgement_only():
    agent = FridayUnderTest()
    with pytest.raises(StopResponse):
        await hears(agent, "Friday, stop")
    assert agent.fake_session.said == [DISMISSED_LINE]
    assert agent.dismissals == 1
