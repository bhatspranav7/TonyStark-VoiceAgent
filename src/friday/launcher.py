"""Start everything with one command: tool server, voice agent and the HUD.

Run with: uv run friday            (add --no-browser to skip opening the HUD)
On Windows you can also double-click "Start FRIDAY.bat".

Closing the window or pressing Ctrl+C stops both processes.
"""

import json
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser

from .config import settings

SERVER_START_TIMEOUT = 30
# Loading the speech models and registering with LiveKit; slow on a cold start.
AGENT_START_TIMEOUT = 120


def is_up(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=2) as response:  # noqa: S310 - local http URL
            return response.status == 200
    except (urllib.error.URLError, OSError):
        return False


def wait_until_up(url: str, timeout: float, still_running=lambda: True) -> bool:
    """Poll `url` until it answers; give up after `timeout` or if the process died."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and still_running():
        if is_up(url):
            return True
        time.sleep(0.3)
    return False


def relay_agent_output(stream, registered: threading.Event) -> None:
    """Read the agent's JSON log lines: note when it is ready, show only real problems."""
    for line in stream:
        try:
            record = json.loads(line)
        except ValueError:
            print(line, end="", flush=True)  # plain text: startup errors, tracebacks
            continue
        if not isinstance(record, dict):
            continue
        if record.get("message") == "registered worker":
            registered.set()
        if record.get("level") in ("ERROR", "CRITICAL"):
            detail = (record.get("exc_info") or "").strip().rsplit("\n", 1)[-1]
            print(f"  [voice agent] {record.get('message')} {detail}".rstrip(), flush=True)


def wait_for_agent(agent: subprocess.Popen, registered: threading.Event, timeout: float) -> bool:
    """Wait until the agent has registered with LiveKit; False if it died or timed out."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if registered.wait(0.5):
            return True
        if agent.poll() is not None:
            return False
    return False


def stop(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    if sys.platform == "win32":
        # terminate() would leave the agent's worker processes behind; take the whole tree.
        subprocess.run(  # noqa: S603
            ["taskkill", "/T", "/F", "/PID", str(process.pid)],  # noqa: S607
            capture_output=True,
            check=False,
        )
    else:
        process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()


def main() -> None:
    hud_url = f"{settings.base_url}/"
    open_browser = "--no-browser" not in sys.argv[1:]

    if is_up(hud_url):
        print(f"FRIDAY is already running at {hud_url}")
        if open_browser:
            webbrowser.open(hud_url)
        return

    print("Starting F.R.I.D.A.Y. (close this window or press Ctrl+C to stop)\n", flush=True)
    server = subprocess.Popen([sys.executable, "-m", "friday.server"])  # noqa: S603
    agent = subprocess.Popen(  # noqa: S603
        [sys.executable, "-m", "friday.agent", "start"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    processes = {"tool server": server, "voice agent": agent}
    registered = threading.Event()
    threading.Thread(
        target=relay_agent_output, args=(agent.stdout, registered), daemon=True
    ).start()

    try:
        if not wait_until_up(hud_url, SERVER_START_TIMEOUT, lambda: server.poll() is None):
            print("The tool server did not start. See the messages above.")
            return
        print("  Tool server is up. Waking the voice agent...", flush=True)
        if not wait_for_agent(agent, registered, AGENT_START_TIMEOUT):
            if agent.poll() is not None:
                print("The voice agent did not start. See the messages above.")
                return
            print("  The voice agent is slow to start; the HUD will connect once it is ready.")
        print(f"  Ready. Talk to FRIDAY at {hud_url}\n", flush=True)
        if open_browser:
            webbrowser.open(hud_url)

        while True:
            for name, process in processes.items():
                if process.poll() is not None:
                    print(f"\nThe {name} stopped (exit code {process.returncode}). Shutting down.")
                    return
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping FRIDAY...")
    finally:
        for process in processes.values():
            stop(process)


if __name__ == "__main__":
    main()
