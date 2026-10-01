# TonyStark-VoiceAgent — F.R.I.D.A.Y.

A Tony Stark-style voice assistant with its own heads-up display. You talk (or type)
to FRIDAY in the browser; she answers out loud, and the headlines and search results
she finds appear as cards beside the conversation.

Everything runs on free tiers: LiveKit Cloud, Google Gemini and Sarvam AI.

## How it works

```text
            Browser HUD  (http://127.0.0.1:8000)
   mic / typed text │  ▲ voice, transcript, result cards
                    ▼  │
              LiveKit Cloud room
                    │  ▲
                    ▼  │
   Voice agent  (uv run friday-voice)
     Sarvam STT ─► Gemini ─► Sarvam TTS
                    │  ▲
          tool calls│  │results
                    ▼  │
   Tool server  (uv run friday-server)
     /mcp        MCP tools: get_briefing, search_news,
                 search_web, read_page, get_datetime
     /           serves the HUD
     /api/token  lets the HUD join a LiveKit room
```

Two processes run side by side:

| Command | What it does |
| --- | --- |
| `uv run friday-server` | Local web server on port 8000. Hosts the MCP tools, the HUD page and the token endpoint. |
| `uv run friday-voice` | The LiveKit voice agent. Joins the room the HUD creates, listens, thinks, speaks and calls the tools. |

## Quick start

You need Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/bhatspranav7/TonyStark-VoiceAgent.git
cd TonyStark-VoiceAgent
uv sync
cp .env.example .env
```

Fill in `.env`:

| Variable | Where to get it |
| --- | --- |
| `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET` | [cloud.livekit.io](https://cloud.livekit.io) → your project → API keys |
| `GOOGLE_API_KEY` | [aistudio.google.com/apikey](https://aistudio.google.com/apikey) |
| `SARVAM_API_KEY` | [dashboard.sarvam.ai](https://dashboard.sarvam.ai) |

Then start both processes, each in its own terminal:

```bash
uv run friday-server
```

```bash
uv run friday-voice
```

Open <http://127.0.0.1:8000> in Chrome or Edge, click **ENGAGE**, allow the microphone,
and say "catch me up".

## Things to say

- "Catch me up" / "What's happening in tech?" — briefings for world, finance, tech, science and India
- "Any news about ISRO?" — news search on a subject
- "Search for the latest Python release" — live web search
- "Open the second one and tell me more" — reads the page behind a result
- "What time is it?"

## Settings

Optional values in `.env` (defaults shown in `.env.example`):

| Variable | Purpose |
| --- | --- |
| `FRIDAY_LLM_MODEL` | Gemini model, default `gemini-2.5-flash` |
| `FRIDAY_TTS_VOICE` | Sarvam voice, default `priya`. Others for `bulbul:v3` include `ritu`, `neha`, `kavya`, `ishita`, `shreya`, `rahul`, `aditya`, `dev` |
| `FRIDAY_TTS_PACE` | Speaking speed, default `1.1` |
| `FRIDAY_STT_LANGUAGE` | Speech recognition language, default `en-IN` |
| `FRIDAY_USER_TITLE` | What FRIDAY calls you, default `boss` |
| `FRIDAY_PORT` | Port for the tool server and HUD, default `8000` |

The persona lives in [src/friday/prompts.py](src/friday/prompts.py).

## Adding a tool

1. Create a module in `src/friday/tools/` with a `register(mcp)` function and decorate
   your functions with `@mcp.tool()`. The docstring is what the model reads.
2. Add the module to `MODULES` in [src/friday/tools/__init__.py](src/friday/tools/__init__.py).
3. Restart both processes.

To get a card on the HUD, return a JSON string shaped like
`{"kind": "news" | "search", "title": "...", "items": [{"title", "summary", "link", "source"}]}`.

## Project layout

```text
src/friday/
├── agent.py        voice agent (STT → LLM → TTS, MCP tools, HUD events)
├── server.py       MCP server + HUD host + token endpoint
├── config.py       settings from .env
├── prompts.py      FRIDAY's persona and greeting
├── tools/
│   ├── news.py     get_briefing, search_news
│   ├── web.py      search_web, read_page
│   ├── system.py   get_datetime
│   └── feeds.py    RSS / Atom fetching and parsing
└── hud/            index.html, hud.css, hud.js
tests/              offline tests: uv run pytest
```

## Troubleshooting

- **"FRIDAY has not joined"** — `uv run friday-voice` is not running, or its LiveKit keys differ from the server's.
- **Red message on the HUD** — a provider rejected a request (wrong key, unknown voice, quota used up). The agent terminal has the detail.
- **No microphone** — the browser blocked it. Allow the mic for `127.0.0.1:8000`, or just type.
- **Typed replies but no voice** — click the page once; browsers block audio until you interact.

## Credits

Inspired by [SAGAR-TAMANG/friday-tony-stark-demo](https://github.com/SAGAR-TAMANG/friday-tony-stark-demo).
Built with [LiveKit Agents](https://github.com/livekit/agents) and the
[Model Context Protocol](https://modelcontextprotocol.io).
