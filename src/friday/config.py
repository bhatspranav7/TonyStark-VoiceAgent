"""Settings loaded from the environment (.env in the project root)."""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


@dataclass(frozen=True)
class Settings:
    # LiveKit
    livekit_url: str = _env("LIVEKIT_URL")
    livekit_api_key: str = _env("LIVEKIT_API_KEY")
    livekit_api_secret: str = _env("LIVEKIT_API_SECRET")

    # Tool server + HUD
    host: str = _env("FRIDAY_HOST", "127.0.0.1")
    port: int = int(_env("FRIDAY_PORT", "8000"))
    # Lets a HUD that is not on this machine (e.g. hosted on Vercel) get a session.
    access_code: str = _env("FRIDAY_ACCESS_CODE")
    on_vercel: bool = bool(_env("VERCEL"))

    # Voice pipeline
    # Comma-separated, tried in order. Gemini's free tier has a small daily quota per
    # model (20 requests/day on gemini-2.5-flash), so the agent falls through the list.
    llm_model: str = _env(
        "FRIDAY_LLM_MODEL",
        "gemini-3.5-flash-lite,gemini-3.1-flash-lite,gemini-3.5-flash,gemini-2.5-flash",
    )
    stt_model: str = _env("FRIDAY_STT_MODEL", "saaras:v3")
    stt_language: str = _env("FRIDAY_STT_LANGUAGE", "en-IN")
    tts_model: str = _env("FRIDAY_TTS_MODEL", "bulbul:v3")
    tts_voice: str = _env("FRIDAY_TTS_VOICE", "priya")
    tts_language: str = _env("FRIDAY_TTS_LANGUAGE", "en-IN")
    tts_pace: float = float(_env("FRIDAY_TTS_PACE", "1.1"))

    # Persona
    user_title: str = _env("FRIDAY_USER_TITLE", "boss")

    @property
    def llm_models(self) -> list[str]:
        return [name.strip() for name in self.llm_model.split(",") if name.strip()]

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    @property
    def mcp_url(self) -> str:
        return f"{self.base_url}/mcp"

    def missing(self, *names: str) -> list[str]:
        """Return the env var names among `names` that are not set."""
        return [n for n in names if not _env(n)]


settings = Settings()
