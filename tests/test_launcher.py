"""The one-command launcher."""

import io
import socket
import subprocess
import sys
import threading

from friday import launcher


def closed_port_url() -> str:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return f"http://127.0.0.1:{sock.getsockname()[1]}/"


def test_is_up_sees_a_running_server(live_server):
    assert launcher.is_up(f"{live_server}/")


def test_is_up_is_false_when_nothing_listens():
    assert not launcher.is_up(closed_port_url())


def test_wait_until_up_gives_up_after_the_timeout():
    assert not launcher.wait_until_up(closed_port_url(), timeout=0.5)


def test_wait_until_up_stops_early_when_the_process_has_died():
    assert not launcher.wait_until_up(closed_port_url(), timeout=30, still_running=lambda: False)


def test_stop_ends_a_running_process_and_tolerates_a_finished_one():
    process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    launcher.stop(process)
    assert process.poll() is not None
    launcher.stop(process)  # already gone: must not raise


def test_main_only_opens_the_browser_when_already_running(live_server, monkeypatch, capsys):
    opened, started = [], []
    monkeypatch.setattr(launcher, "settings", type("S", (), {"base_url": live_server})())
    monkeypatch.setattr(launcher.webbrowser, "open", opened.append)
    monkeypatch.setattr(launcher.subprocess, "Popen", lambda *a, **k: started.append(a))
    monkeypatch.setattr(sys, "argv", ["friday"])

    launcher.main()

    assert opened == [f"{live_server}/"]
    assert started == []  # no second copy is launched
    assert "already running" in capsys.readouterr().out


def sleeper(seconds: float) -> subprocess.Popen:
    return subprocess.Popen([sys.executable, "-c", f"import time; time.sleep({seconds})"])


def run_main_with(monkeypatch, processes, during_wait):
    """Run launcher.main() with fake child processes; `during_wait` replaces the 1 s poll."""
    queue = list(processes)
    real_popen = subprocess.Popen

    def fake_popen(*args, **kwargs):
        # The first two launches are the server and agent; later ones (taskkill) are real.
        return queue.pop(0) if queue else real_popen(*args, **kwargs)

    monkeypatch.setattr(launcher, "settings", type("S", (), {"base_url": closed_port_url()[:-1]})())
    monkeypatch.setattr(launcher, "is_up", lambda url: False)
    monkeypatch.setattr(launcher, "wait_until_up", lambda *a, **k: True)
    monkeypatch.setattr(launcher, "wait_for_agent", lambda *a, **k: True)
    monkeypatch.setattr(launcher, "relay_agent_output", lambda *a, **k: None)
    monkeypatch.setattr(launcher.webbrowser, "open", lambda url: None)
    monkeypatch.setattr(launcher.subprocess, "Popen", fake_popen)
    # Not time.sleep: that is global, and Popen.wait() relies on it on Linux and macOS.
    monkeypatch.setattr(launcher, "pause", during_wait)
    monkeypatch.setattr(sys, "argv", ["friday", "--no-browser"])
    launcher.main()


def test_ctrl_c_stops_both_processes(monkeypatch, capsys):
    server, agent = sleeper(60), sleeper(60)

    def press_ctrl_c(_seconds):
        raise KeyboardInterrupt

    run_main_with(monkeypatch, [server, agent], press_ctrl_c)

    assert server.poll() is not None and agent.poll() is not None
    assert "Stopping FRIDAY" in capsys.readouterr().out


def test_if_one_process_dies_the_other_is_stopped_too(monkeypatch, capsys):
    server, agent = sleeper(60), sleeper(0)
    agent.wait()

    run_main_with(monkeypatch, [server, agent], lambda _seconds: None)

    assert server.poll() is not None
    assert "voice agent stopped" in capsys.readouterr().out


def test_agent_output_is_filtered_and_registration_is_detected(capsys):
    registered = threading.Event()
    stream = io.StringIO(
        '{"message": "starting worker", "level": "INFO"}\n'
        '{"message": "event loop blocked", "level": "WARNING"}\n'
        '{"message": "registered worker", "level": "INFO"}\n'
        '{"message": "TTS failed", "level": "ERROR", '
        '"exc_info": "Traceback\\nAPIError: bad voice"}\n'
        "Missing in .env: GOOGLE_API_KEY\n"
        "[1, 2]\n"
    )

    launcher.relay_agent_output(stream, registered)

    assert registered.is_set()
    out = capsys.readouterr().out
    assert (
        out == "  [voice agent] TTS failed APIError: bad voice\nMissing in .env: GOOGLE_API_KEY\n"
    )


def test_wait_for_agent_returns_false_when_the_agent_dies():
    agent = sleeper(0)
    agent.wait()
    assert not launcher.wait_for_agent(agent, threading.Event(), timeout=30)


def test_wait_for_agent_returns_true_once_registered():
    registered = threading.Event()
    registered.set()
    agent = sleeper(30)
    try:
        assert launcher.wait_for_agent(agent, registered, timeout=5)
    finally:
        launcher.stop(agent)
