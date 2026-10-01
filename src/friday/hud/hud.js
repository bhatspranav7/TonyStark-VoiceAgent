(() => {
  "use strict";

  const { Room, RoomEvent, Track } = LivekitClient;

  const TRANSCRIPT_TOPIC = "lk.transcription";
  const CHAT_TOPIC = "lk.chat";
  const HUD_TOPIC = "friday.hud";
  const AGENT_STATE_ATTR = "lk.agent.state";
  const AGENT_JOIN_TIMEOUT_MS = 15000;
  const MAX_CARDS = 12;

  const $ = (id) => document.getElementById(id);
  const els = {
    orb: $("orb"), orbLabel: $("orb-label"), canvas: $("orb-canvas"),
    state: $("state"), notice: $("notice"),
    mic: $("mic"), disconnect: $("disconnect"),
    chat: $("chat"), chatInput: $("chat-input"), chatSend: $("chat").querySelector("button"),
    transcript: $("transcript"), cards: $("cards"), activity: $("tool-activity"),
    link: $("readout-link"), room: $("readout-room"), clock: $("readout-clock"),
  };

  const STATE_LABELS = {
    offline: "Offline",
    connecting: "Establishing link",
    waiting: "Waiting for FRIDAY",
    initializing: "Waking up",
    idle: "Standing by",
    listening: "Listening",
    thinking: "Thinking",
    speaking: "Speaking",
  };

  let room = null;
  let audioCtx = null;
  let agentState = "offline";
  let agentTimer = null;
  let micMuted = false;
  let asleep = false;
  let joinNoticeShown = false;
  const analysers = { agent: null, user: null };
  const audioEls = new Set();

  // ---------- clock ----------
  const tick = () => { els.clock.textContent = new Date().toLocaleTimeString([], { hour12: false }); };
  tick();
  setInterval(tick, 1000);

  // ---------- status ----------
  function setState(state) {
    agentState = state;
    renderState();
  }

  function renderState() {
    const sleeping = asleep && (agentState === "listening" || agentState === "idle");
    els.state.textContent = sleeping ? "Asleep — say “Friday”" : (STATE_LABELS[agentState] || agentState);
  }

  function showNotice(message, isError = false) {
    els.notice.textContent = message;
    els.notice.classList.toggle("error", isError);
    els.notice.hidden = false;
  }

  function clearNotice() { els.notice.hidden = true; }

  function setConnectedUi(connected) {
    els.orb.disabled = connected;
    els.orbLabel.hidden = connected;
    els.mic.disabled = !connected;
    els.disconnect.disabled = !connected;
    els.chatInput.disabled = !connected;
    els.chatSend.disabled = !connected;
    els.link.textContent = connected ? "online" : "offline";
    els.link.dataset.on = String(connected);
    if (!connected) els.room.textContent = "—";
  }

  // ---------- transcript ----------
  const lines = new Map();

  function upsertLine(id, role, text, interim = false) {
    let line = lines.get(id);
    if (!line) {
      els.transcript.querySelector(".empty")?.remove();
      line = document.createElement("p");
      line.className = `line ${role}`;
      const who = document.createElement("span");
      who.className = "who";
      who.textContent = role === "user" ? "You" : "FRIDAY";
      const what = document.createElement("span");
      what.className = "what";
      line.append(who, what);
      els.transcript.append(line);
      lines.set(id, line);
    }
    line.classList.toggle("interim", interim);
    line.querySelector(".what").textContent = text;
    els.transcript.scrollTop = els.transcript.scrollHeight;
  }

  async function onTranscription(reader, participantInfo) {
    const attrs = reader.info.attributes || {};
    const id = attrs["lk.segment_id"] || reader.info.id;
    const role = participantInfo.identity === room?.localParticipant.identity ? "user" : "agent";
    const interim = attrs["lk.transcription_final"] === "false";
    let text = "";
    for await (const chunk of reader) {
      text += chunk;
      if (text.trim()) upsertLine(id, role, text, interim);
    }
  }

  // ---------- intel cards ----------
  function safeLink(href) {
    try {
      const url = new URL(href);
      return url.protocol === "http:" || url.protocol === "https:" ? url.href : null;
    } catch { return null; }
  }

  function titleNode(title, href) {
    const link = safeLink(href);
    if (!link) {
      const strong = document.createElement("strong");
      strong.textContent = title;
      return strong;
    }
    const a = document.createElement("a");
    a.href = link;
    a.target = "_blank";
    a.rel = "noopener noreferrer";
    a.textContent = title;
    return a;
  }

  function parseToolOutput(output) {
    let data = output;
    // Tool output arrives as a JSON string, sometimes wrapped in an MCP text block.
    for (let depth = 0; depth < 3 && typeof data === "string"; depth++) {
      try { data = JSON.parse(data); } catch { return null; }
      if (data && typeof data === "object" && typeof data.text === "string" && data.type === "text") {
        data = data.text;
      }
    }
    return data && typeof data === "object" ? data : null;
  }

  function addCard(toolName, data, isError) {
    const card = document.createElement("article");
    card.className = "card";

    const head = document.createElement("header");
    head.className = "card-head";
    const label = document.createElement("span");
    const time = document.createElement("time");
    time.textContent = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false });
    head.append(label, time);
    card.append(head);

    if (isError || data.error) {
      card.classList.add("error");
      label.textContent = `${toolName} failed`;
      const p = document.createElement("p");
      p.textContent = data.error || "The tool returned an error.";
      card.append(p);
    } else if (data.kind === "news" || data.kind === "search") {
      label.textContent = data.title || data.kind;
      const list = document.createElement("ol");
      for (const item of data.items || []) {
        const li = document.createElement("li");
        if (item.source) {
          const src = document.createElement("span");
          src.className = "src";
          src.textContent = item.source;
          li.append(src);
        }
        li.append(titleNode(item.title, item.link));
        if (item.summary) {
          const p = document.createElement("p");
          p.textContent = item.summary;
          li.append(p);
        }
        list.append(li);
      }
      card.append(list);
    } else if (data.kind === "page") {
      label.textContent = "page";
      card.append(titleNode(data.title, data.link));
      const p = document.createElement("p");
      const text = data.text || "";
      p.textContent = text.length > 420 ? `${text.slice(0, 420)}…` : text;
      card.append(p);
    } else {
      return;
    }

    els.cards.querySelector(".empty")?.remove();
    els.cards.prepend(card);
    while (els.cards.children.length > MAX_CARDS) els.cards.lastElementChild.remove();
    els.cards.scrollTop = 0;
  }

  async function onHudMessage(reader) {
    let message;
    try { message = JSON.parse(await reader.readAll()); } catch { return; }
    if (message.type === "tool_start") {
      els.activity.textContent = `running ${message.name}…`;
      els.activity.hidden = false;
    } else if (message.type === "tool_result") {
      els.activity.hidden = true;
      const data = parseToolOutput(message.output);
      if (data) addCard(message.name, data, message.is_error);
      else if (message.is_error) addCard(message.name, { error: String(message.output) }, true);
    } else if (message.type === "mode") {
      asleep = Boolean(message.asleep);
      renderState();
    } else if (message.type === "error") {
      showNotice(message.message, true);
    }
  }

  // ---------- audio ----------
  function attachAnalyser(kind, mediaStreamTrack) {
    if (!audioCtx || !mediaStreamTrack) return;
    const source = audioCtx.createMediaStreamSource(new MediaStream([mediaStreamTrack]));
    const analyser = audioCtx.createAnalyser();
    analyser.fftSize = 256;
    analyser.smoothingTimeConstant = 0.78;
    source.connect(analyser);
    analysers[kind] = analyser;
  }

  // ---------- connection ----------
  function readAgentState(participant) {
    const state = participant.attributes?.[AGENT_STATE_ATTR];
    if (!state) return;
    clearTimeout(agentTimer);
    if (joinNoticeShown) { clearNotice(); joinNoticeShown = false; }
    setState(state);
  }

  function cleanup() {
    clearTimeout(agentTimer);
    for (const el of audioEls) el.remove();
    audioEls.clear();
    analysers.agent = analysers.user = null;
    room = null;
    micMuted = false;
    asleep = false;
    els.mic.textContent = "Mute mic";
    els.mic.setAttribute("aria-pressed", "false");
    els.activity.hidden = true;
    joinNoticeShown = false;
    clearNotice();
    setConnectedUi(false);
    setState("offline");
  }

  async function connect() {
    if (room) return;
    clearNotice();
    setState("connecting");
    els.orb.disabled = true;

    // Created inside the click so the browser allows audio playback.
    audioCtx ??= new AudioContext();
    audioCtx.resume();

    let creds;
    try {
      const res = await fetch("/api/token", { method: "POST" });
      creds = await res.json();
      if (!res.ok) throw new Error(creds.error || res.statusText);
    } catch (err) {
      cleanup();
      showNotice(`Could not get a session: ${err.message}`, true);
      return;
    }

    room = new Room();
    room
      .on(RoomEvent.TrackSubscribed, (track) => {
        if (track.kind !== Track.Kind.Audio) return;
        const el = track.attach();
        document.body.append(el);
        audioEls.add(el);
        attachAnalyser("agent", track.mediaStreamTrack);
      })
      .on(RoomEvent.LocalTrackPublished, (pub) => {
        if (pub.source === Track.Source.Microphone) attachAnalyser("user", pub.track?.mediaStreamTrack);
      })
      .on(RoomEvent.ParticipantConnected, readAgentState)
      .on(RoomEvent.ParticipantAttributesChanged, (_changed, participant) => {
        if (participant !== room?.localParticipant) readAgentState(participant);
      })
      .on(RoomEvent.ParticipantDisconnected, () => {
        if (room && room.remoteParticipants.size === 0) {
          setState("waiting");
          showNotice("FRIDAY left the room. Disconnect and engage again to restart.");
        }
      })
      .on(RoomEvent.Disconnected, cleanup);

    room.registerTextStreamHandler(TRANSCRIPT_TOPIC, onTranscription);
    room.registerTextStreamHandler(HUD_TOPIC, onHudMessage);

    try {
      await room.connect(creds.url, creds.token);
    } catch (err) {
      cleanup();
      showNotice(`Could not reach LiveKit: ${err.message}`, true);
      return;
    }

    els.room.textContent = creds.room;
    setConnectedUi(true);
    setState("waiting");
    room.remoteParticipants.forEach(readAgentState);
    agentTimer = setTimeout(() => {
      if (agentState === "waiting") {
        showNotice("FRIDAY has not joined. Check that `uv run friday-voice` is running.", true);
        joinNoticeShown = true;
      }
    }, AGENT_JOIN_TIMEOUT_MS);

    try {
      await room.localParticipant.setMicrophoneEnabled(true);
    } catch {
      els.mic.disabled = true;
      showNotice("Microphone unavailable. You can still type to FRIDAY.");
    }
  }

  els.orb.addEventListener("click", connect);
  els.disconnect.addEventListener("click", () => room?.disconnect());

  els.mic.addEventListener("click", async () => {
    if (!room) return;
    micMuted = !micMuted;
    await room.localParticipant.setMicrophoneEnabled(!micMuted);
    els.mic.textContent = micMuted ? "Mic muted" : "Mute mic";
    els.mic.setAttribute("aria-pressed", String(micMuted));
  });

  els.chat.addEventListener("submit", async (event) => {
    event.preventDefault();
    const text = els.chatInput.value.trim();
    if (!room || !text) return;
    els.chatInput.value = "";
    upsertLine(`typed-${Date.now()}`, "user", text);
    try {
      await room.localParticipant.sendText(text, { topic: CHAT_TOPIC });
    } catch (err) {
      showNotice(`Message not sent: ${err.message}`, true);
    }
  });

  // ---------- orb ----------
  const g = els.canvas.getContext("2d");
  const TAU = Math.PI * 2;
  const reducedMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const PALETTE = {
    offline: [70, 120, 145],
    thinking: [255, 180, 84],
    speaking: [170, 244, 255],
    default: [94, 230, 255],
  };
  const SPIN_SPEED = { connecting: 1.8, waiting: 1.2, initializing: 1.2, thinking: 2.6, speaking: 0.9, listening: 0.4 };
  const ARCS = [
    { radius: 0.8, start: 0.0, length: 1.3, direction: 1, width: 0.016 },
    { radius: 0.8, start: Math.PI, length: 1.3, direction: 1, width: 0.016 },
    { radius: 0.89, start: 0.6, length: 0.7, direction: -1.6, width: 0.01 },
    { radius: 0.89, start: 2.7, length: 1.9, direction: -1.6, width: 0.01 },
    { radius: 0.89, start: 5.0, length: 0.4, direction: -1.6, width: 0.01 },
  ];
  const BARS = 72;
  const freq = new Uint8Array(128);
  let level = 0;
  let spin = 0;

  function resizeCanvas() {
    const rect = els.canvas.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    els.canvas.width = Math.round(rect.width * dpr);
    els.canvas.height = Math.round(rect.height * dpr);
  }
  new ResizeObserver(resizeCanvas).observe(els.canvas);

  function sampleAudio() {
    // Show FRIDAY's voice while she speaks, otherwise the user's microphone.
    const analyser = agentState === "speaking" ? analysers.agent : (micMuted ? null : analysers.user);
    if (!analyser) { freq.fill(0); return 0; }
    analyser.getByteFrequencyData(freq);
    let sum = 0;
    for (let i = 0; i < 48; i++) sum += freq[i];
    return sum / (48 * 255);
  }

  function draw(now) {
    requestAnimationFrame(draw);
    const w = els.canvas.width, h = els.canvas.height;
    if (!w || !h) return;
    const cx = w / 2, cy = h / 2, R = Math.min(w, h) / 2;
    const [r, gr, b] = (asleep && agentState !== "speaking" ? PALETTE.offline : PALETTE[agentState]) || PALETTE.default;
    const color = (alpha) => `rgba(${r},${gr},${b},${alpha})`;

    level += (sampleAudio() - level) * 0.25;
    if (!reducedMotion) spin += (SPIN_SPEED[agentState] ?? 0.12) * 0.012;
    const breathe = reducedMotion ? 0 : Math.sin(now / 900) * 0.012;

    g.clearRect(0, 0, w, h);

    // core
    const coreR = R * (0.24 + breathe + level * 0.14);
    const glow = g.createRadialGradient(cx, cy, 0, cx, cy, coreR * 2.1);
    glow.addColorStop(0, color(0.6));
    glow.addColorStop(0.4, color(0.16));
    glow.addColorStop(1, color(0));
    g.fillStyle = glow;
    g.beginPath(); g.arc(cx, cy, coreR * 2.1, 0, TAU); g.fill();
    g.lineWidth = R * 0.012;
    g.strokeStyle = color(0.9);
    g.beginPath(); g.arc(cx, cy, coreR, 0, TAU); g.stroke();

    // audio spectrum, mirrored left/right
    const inner = R * 0.5;
    g.lineCap = "round";
    g.lineWidth = R * 0.014;
    for (let i = 0; i < BARS; i++) {
      const bin = i < BARS / 2 ? i : BARS - 1 - i;
      const v = freq[bin + 2] / 255;
      const length = R * (0.02 + v * 0.22);
      const angle = (i / BARS) * TAU - Math.PI / 2;
      const cos = Math.cos(angle), sin = Math.sin(angle);
      g.strokeStyle = color(0.22 + v * 0.78);
      g.beginPath();
      g.moveTo(cx + cos * inner, cy + sin * inner);
      g.lineTo(cx + cos * (inner + length), cy + sin * (inner + length));
      g.stroke();
    }

    // rotating arcs
    g.lineCap = "butt";
    for (const arc of ARCS) {
      const start = arc.start + spin * arc.direction;
      g.lineWidth = R * arc.width;
      g.strokeStyle = color(0.7);
      g.beginPath(); g.arc(cx, cy, R * arc.radius, start, start + arc.length); g.stroke();
    }

    // outer tick ring
    g.lineWidth = R * 0.006;
    for (let i = 0; i < 60; i++) {
      const angle = (i / 60) * TAU;
      const long = i % 5 === 0;
      const r1 = R * (long ? 0.94 : 0.96), r2 = R * 0.985;
      g.strokeStyle = color(long ? 0.6 : 0.28);
      g.beginPath();
      g.moveTo(cx + Math.cos(angle) * r1, cy + Math.sin(angle) * r1);
      g.lineTo(cx + Math.cos(angle) * r2, cy + Math.sin(angle) * r2);
      g.stroke();
    }
  }

  resizeCanvas();
  requestAnimationFrame(draw);
})();
