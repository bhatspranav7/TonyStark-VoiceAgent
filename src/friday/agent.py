"""F.R.I.D.A.Y. voice agent.

Pipeline: microphone -> Sarvam STT -> Gemini -> Sarvam TTS -> speaker, with tools
pulled from the local MCP server (start `uv run friday-server` first).

Run with: uv run friday-voice
"""

import asyncio
import json
import math
import sys
from collections.abc import Callable

from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    JobContext,
    JobProcess,
    StopResponse,
    cli,
    llm,
    mcp,
)
from livekit.agents.voice.events import (
    AgentStateChangedEvent,
    ErrorEvent,
    FunctionToolsExecutedEvent,
    ToolExecutionUpdatedEvent,
)
from livekit.plugins import google, sarvam, silero

from .config import settings
from .prompts import build_instructions, greeting_instructions
from .wake import Heard, WakeGate

# Text-stream topic the HUD listens on for tool activity and result cards.
HUD_TOPIC = "friday.hud"

REQUIRED_ENV = (
    "LIVEKIT_URL",
    "LIVEKIT_API_KEY",
    "LIVEKIT_API_SECRET",
    "GOOGLE_API_KEY",
    "SARVAM_API_KEY",
)


DISMISSED_LINE = "Standing by."


class Friday(Agent):
    def __init__(self, on_dismissed: Callable[[], None] | None = None) -> None:
        super().__init__(instructions=build_instructions(settings.user_title))
        self.gate = WakeGate(settings.wake_words, settings.follow_up_seconds)
        self._on_dismissed = on_dismissed

    async def on_user_turn_completed(
        self, turn_ctx: llm.ChatContext, new_message: llm.ChatMessage
    ) -> None:
        # Runs for everything the microphone hears; only speech addressed to her gets a reply.
        heard = self.gate.hear(new_message.text_content or "")
        if heard is Heard.RESPOND:
            return
        if heard is Heard.DISMISSED:
            self.session.say(DISMISSED_LINE)
            if self._on_dismissed:
                self._on_dismissed()
        raise StopResponse()


def build_llm() -> llm.LLM:
    models = [google.LLM(model=name) for name in settings.llm_models]
    if len(models) == 1:
        return models[0]
    # When one model's quota runs out (or it is overloaded), move on to the next.
    return llm.FallbackAdapter(models, attempt_timeout=15)


def mcp_tools() -> mcp.MCPServerHTTP:
    return mcp.MCPServerHTTP(
        url=settings.mcp_url,
        transport_type="streamable_http",
        timeout=10,
        # Web search can take several seconds; the default of 5 is too tight.
        client_session_timeout_seconds=30,
    )


def prewarm(proc: JobProcess) -> None:
    proc.userdata["vad"] = silero.VAD.load()


# Sized for one person on their own machine: keep a single warm process and never
# refuse a session because the desktop happens to be busy.
server = AgentServer(
    setup_fnc=prewarm,
    num_idle_processes=1,
    load_threshold=math.inf,
    # Loading the speech models on a cold start can take longer than the 10 s default.
    initialize_process_timeout=60,
)


@server.rtc_session()
async def entrypoint(ctx: JobContext) -> None:
    await ctx.connect()

    session = AgentSession(
        vad=ctx.proc.userdata["vad"],
        stt=sarvam.STT(language=settings.stt_language, model=settings.stt_model),
        llm=build_llm(),
        tts=sarvam.TTS(
            target_language_code=settings.tts_language,
            model=settings.tts_model,
            speaker=settings.tts_voice,
            pace=settings.tts_pace,
        ),
        tools=[mcp.MCPToolset(id="friday", mcp_server=mcp_tools())],
        max_tool_steps=5,
    )

    background: set[asyncio.Task] = set()

    def send_to_hud(payload: dict) -> None:
        task = asyncio.create_task(
            ctx.room.local_participant.send_text(json.dumps(payload), topic=HUD_TOPIC)
        )
        background.add(task)
        task.add_done_callback(background.discard)

    @session.on("tool_execution_updated")
    def on_tool_update(event: ToolExecutionUpdatedEvent) -> None:
        if event.update.type == "tool_call_started":
            call = event.update.function_call
            send_to_hud({"type": "tool_start", "name": call.name, "arguments": call.arguments})

    @session.on("function_tools_executed")
    def on_tools_executed(event: FunctionToolsExecutedEvent) -> None:
        for call, output in zip(event.function_calls, event.function_call_outputs, strict=True):
            send_to_hud(
                {
                    "type": "tool_result",
                    "name": call.name,
                    "is_error": bool(output and output.is_error),
                    "output": output.output if output else "",
                }
            )

    @session.on("error")
    def on_error(event: ErrorEvent) -> None:
        # Surface provider failures (bad key, unknown voice, quota) instead of going silent.
        label = getattr(event.error, "label", type(event.source).__name__)
        detail = getattr(event.error, "error", event.error)
        send_to_hud({"type": "error", "message": f"{label}: {detail}"[:400]})

    def send_listening_mode(follow_up_seconds: float) -> None:
        # Tells the HUD whether she needs her name next, or is still listening for a follow-up.
        send_to_hud({"type": "mode", "follow_up": follow_up_seconds})

    friday = Friday(on_dismissed=lambda: send_listening_mode(0))

    @session.on("agent_state_changed")
    def on_agent_state(event: AgentStateChangedEvent) -> None:
        if event.old_state == "speaking" and event.new_state == "listening":
            friday.gate.answered()
            send_listening_mode(settings.follow_up_seconds if friday.gate.in_follow_up else 0)

    # Typed messages are always answered: typing to her is already addressing her.
    await session.start(agent=friday, room=ctx.room)
    await session.generate_reply(instructions=greeting_instructions(settings.user_title))


def main() -> None:
    missing = settings.missing(*REQUIRED_ENV)
    if missing:
        sys.exit(f"Missing in .env: {', '.join(missing)} (see .env.example)")
    # `uv run friday-voice` with no arguments runs the worker; `console` etc. still work.
    if len(sys.argv) == 1:
        sys.argv.append("start")
    cli.run_app(server)


if __name__ == "__main__":
    main()
