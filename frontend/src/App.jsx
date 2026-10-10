import { useEffect, useRef, useState, useCallback } from "react";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { summarizeMetric } from "./utils/telemetry.mjs";

// The session credential never enters JavaScript; only native commands can
// access the authenticated Python worker.
const isTauri = () =>
  typeof window !== "undefined" && Boolean(window.__TAURI_INTERNALS__);

async function apiDispatch(text) {
  if (!isTauri()) throw new Error("Desktop runtime required.");
  return invoke("send_message", { payload: { text } });
}

async function apiTelemetry() {
  if (!isTauri()) return { cpu: null, ram: null, gpu: null, gpu_temp: null };
  // Native Rust reads actual CPU/RAM and optional NVIDIA NVML metrics.
  // Never silently fill missing GPU values with zero.
  return invoke("get_telemetry");
}

// ---------------------------------------------------------------------------
// Status definitions
// ---------------------------------------------------------------------------
const STATUS = {
  standby: { label: "Standby", tone: "dim" },
  listening: { label: "Listening", tone: "accent" },
  processing: { label: "Processing", tone: "warn" },
};

// ---------------------------------------------------------------------------
// Telemetry hook — polls the bridge (or native sysinfo) every 2 seconds
// ---------------------------------------------------------------------------
function useTelemetry() {
  const [stats, setStats] = useState({ cpu: null, ram: null, gpu: null, gpu_temp: null, vram_mb: null });

  useEffect(() => {
    if (!isTauri()) return;
    let active = true;
    let unsubscribe = null;
    const update = (data) => {
      if (active) setStats({
        cpu: data.cpu == null ? null : Math.round(data.cpu),
        ram: data.ram == null ? null : Math.round(data.ram),
        gpu: data.gpu == null ? null : Math.round(data.gpu),
        gpu_temp: data.gpu_temp == null ? null : Math.round(data.gpu_temp),
        vram_mb: data.vram_mb == null ? null : Math.round(data.vram_mb),
      });
    };
    invoke("get_telemetry").then(update).catch(() => {});
    listen("aurix://telemetry", (event) => update(event.payload))
      .then((stop) => { if (active) unsubscribe = stop; else stop(); })
      .catch(() => {});
    return () => { active = false; if (unsubscribe) unsubscribe(); };
  }, []);
  return stats;
}

function HistoryChart({ samples, metric }) {
  const valid = samples.filter((p) => typeof p[metric] === "number" && Number.isFinite(p[metric]));
  if (!valid.length) return <p>No measured history for this metric yet.</p>;
  const values = valid.map((p) => p[metric]);
  const { min, max, avg } = summarizeMetric(valid, metric);
  const scale = Math.max(0.001, max - min);
  const polyline = valid.map((p, i) => {
    const x = valid.length === 1 ? 360 : (i / (valid.length - 1)) * 700 + 10;
    const y = 184 - ((p[metric] - min) / scale) * 165;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
  return (
    <div className="history-chart">
      <svg viewBox="0 0 720 220" role="img" aria-label={`Historical ${metric} trend`}>
        {[20, 60, 100, 140, 180].map((y) =>
          <line key={y} x1="10" x2="710" y1={y} y2={y} stroke="currentColor" strokeOpacity=".08" />
        )}
        <polyline points={polyline} fill="none" stroke="var(--accent)" strokeWidth="3"
          strokeLinejoin="round" strokeLinecap="round" />
      </svg>
      <div className="metric-summary">
        <span>Min: {min.toFixed(1)}</span>
        <span>Avg: {avg.toFixed(1)}</span>
        <span>Max: {max.toFixed(1)}</span>
      </div>
      <p>{valid.length} recorded samples</p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// UI components
// ---------------------------------------------------------------------------
function Bar({ label, value, unit = "%", accent = "var(--accent)" }) {
  return (
    <div className="bar-row">
      <div className="bar-row-top">
        <span className="bar-label">{label}</span>
        <span className="bar-value">
          {value == null ? "N/A" : value}
          {value == null ? null : <span className="bar-unit">{unit}</span>}
        </span>
      </div>
      <div className="bar-track">
        <div
          className="bar-fill"
          style={{ width: `${Math.min(100, Math.max(0, value ?? 0))}%`, background: accent }}
        />
      </div>
    </div>
  );
}

function Waveform({ active }) {
  const bars = 20;
  return (
    <div className={`waveform ${active ? "is-active" : ""}`} aria-hidden="true">
      {Array.from({ length: bars }).map((_, i) => (
        <span key={i} style={{ "--i": i }} />
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main App
// ---------------------------------------------------------------------------
export default function App() {
  const telemetry = useTelemetry();
  const [status, setStatus] = useState("standby");
  const [messages, setMessages] = useState([
    { from: "aurix", text: "LUNA ready. Text works with a locally installed GGUF model. Offline speech needs a local Whisper model." },
  ]);
  const [draft, setDraft] = useState("");
  const logRef = useRef(null);
  const [approval, setApproval] = useState(null);
  const [workerOnline, setWorkerOnline] = useState(false);
  const [approving, setApproving] = useState(false);
  const [activeView, setActiveView] = useState("Command");
  const [settings, setSettings] = useState(null);
  const [memories, setMemories] = useState([]);
  const [memoryKind, setMemoryKind] = useState("semantic");
  const [memoryText, setMemoryText] = useState("");
  const [memorySearch, setMemorySearch] = useState("");
  const [memoryError, setMemoryError] = useState("");
  const [historyWindow, setHistoryWindow] = useState("1h");
  const [historyMetric, setHistoryMetric] = useState("cpu");
  const [telemetryHistory, setTelemetryHistory] = useState([]);
  const [exportedPath, setExportedPath] = useState("");
  const [auditEvents, setAuditEvents] = useState([]);
  const [auditVerified, setAuditVerified] = useState(null);
  const [speechStatus, setSpeechStatus] = useState("");

  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [messages]);

  useEffect(() => {
    if (!isTauri()) return;
    let active = true;
    const check = async () => {
      try {
        const ready = await invoke("get_bridge_health");
        if (active) setWorkerOnline(Boolean(ready));
      } catch {
        if (active) setWorkerOnline(false);
      }
    };
    check();
    const pollId = setInterval(check, 5000);
    return () => { active = false; clearInterval(pollId); };
  }, []);

  const loadMemories = useCallback(async () => {
    if (!isTauri()) return;
    try {
      const data = await invoke("list_memories");
      setMemories(data.items ?? []);
      setMemoryError(data.enabled ? "" : "Memory is disabled. Opt in using [memory].enabled in config.toml.");
    } catch (error) {
      setMemoryError(String(error));
    }
  }, []);

  useEffect(() => {
    if (activeView !== "Telemetry" || !isTauri()) return;
    let active = true;
    const reload = async () => {
      try {
        const points = await invoke("get_telemetry_history", { window: historyWindow });
        if (active) setTelemetryHistory(points);
      } catch (error) {
        if (active) setMemoryError(String(error));
      }
    };
    reload();
    const id = setInterval(reload, 15000);
    return () => { active = false; clearInterval(id); };
  }, [activeView, historyWindow]);

  const exportHistory = async () => {
    try {
      const path = await invoke("export_telemetry_csv", { window: historyWindow });
      setExportedPath(path);
    } catch (error) { setExportedPath(String(error)); }
  };

  useEffect(() => {
    if (activeView !== "Activity" || !isTauri() || !workerOnline) return;
    invoke("list_activity").then((data) => {
      setAuditEvents(data.events ?? []);
      setAuditVerified(data.enabled ? data.verified : null);
    }).catch(() => { setAuditVerified(false); });
  }, [activeView, workerOnline]);

  useEffect(() => {
    if (!workerOnline || !isTauri()) return;
    invoke("get_ui_settings").then(setSettings).catch(() => setSettings(null));
    if (activeView === "Memory") loadMemories();
  }, [workerOnline, activeView, loadMemories]);

  useEffect(() => {
    // Emergency shortcut while AURIX has keyboard focus (not a global hotkey).
    const keyDown = (event) => {
      if (event.ctrlKey && event.shiftKey && event.code === "KeyX") {
        event.preventDefault();
        if (isTauri()) invoke("kill_actions").then((next) =>
          setSettings((old) => ({ ...old, stopped: next.stopped }))
        ).catch(() => {});
      }
    };
    window.addEventListener("keydown", keyDown);
    return () => window.removeEventListener("keydown", keyDown);
  }, []);

  const updateMemory = async () => {
    if (!settings || !workerOnline || !isTauri()) return;
    const next = !settings.memory_enabled;
    if (next && !window.confirm("Enable persistent local memory? Future interactions may be stored in encrypted local files.")) {
      return;
    }
    try {
      const result = await invoke("set_memory_enabled", { enabled: next });
      setSettings((old) => ({ ...old, memory_enabled: result.memory_enabled }));
      setMemoryError(result.memory_enabled
        ? "" : "Memory capture is disabled. Existing saved memories remain until deleted.");
      if (result.memory_enabled) await loadMemories();
      else setMemories([]);
    } catch (error) {
      setMemoryError(`Cannot update memory preference: ${String(error)}`);
    }
  };

  const updateOffline = async () => {
    try {
      const next = await invoke("set_offline_mode", { enabled: !settings.offline });
      setSettings((old) => ({ ...old, offline: next.offline }));
    } catch (error) { setMemoryError(String(error)); }
  };

  const toggleStop = async () => {
    try {
      const next = await invoke(settings?.stopped ? "resume_actions" : "kill_actions");
      setSettings((old) => ({ ...old, stopped: next.stopped }));
    } catch (error) { setMemoryError(String(error)); }
  };

  const addFact = async (event) => {
    event.preventDefault();
    if (!memoryText.trim()) return;
    try {
      await invoke("add_memory", { kind: memoryKind, content: memoryText.trim() });
      setMemoryText("");
      await loadMemories();
    } catch (error) { setMemoryError(String(error)); }
  };

  const deleteFact = async (id) => {
    if (!window.confirm("Delete this stored memory permanently?")) return;
    try {
      await invoke("delete_memory", { id });
      await loadMemories();
    } catch (error) { setMemoryError(String(error)); }
  };

  const respondToApproval = async (accept) => {
    const currentApproval = approval;
    if (!currentApproval || approving) return;
    setApproval(null);
    if (!accept) {
      try {
        await invoke("reject_trust", { payload: { request: currentApproval.id } });
        setMessages((items) => [...items, { from: "aurix", text: "Action rejected." }]);
      } catch (error) {
        setMessages((items) => [...items, { from: "aurix", text: `Rejection error: ${String(error)}` }]);
      }
      return;
    }
    setApproving(true);
    try {
      const response = await invoke("execute_trust", {
        payload: { request: currentApproval.id },
      });
      setMessages((items) => [
        ...items,
        { from: "aurix", text: response.result || "Action finished without a result." },
      ]);
    } catch (error) {
      setMessages((items) => [
        ...items,
        { from: "aurix", text: `Approval failed: ${String(error)}` },
      ]);
    } finally {
      setApproving(false);
    }
  };

  // One path for typed messages and speech transcripts; never invent audio.
  const sendText = useCallback(async (text) => {
    const content = String(text || "").trim();
    if (!content) return;
    setMessages((m) => [...m, { from: "user", text: content }]);
    setDraft("");
    setStatus("processing");
    try {
      const data = await apiDispatch(content);
      const reply = String(data.reply ?? "");
      if (reply.startsWith("TRUST_TOKEN_REQUIRED:")) {
        const [, id, ...description] = reply.split(":");
        if (/^[a-f0-9]{12}$/i.test(id)) {
          setApproval({ id, description: description.join(":") });
          setMessages((m) => [...m, {
            from: "aurix", text: "This action requires explicit native confirmation.",
          }]);
        } else {
          setMessages((m) => [...m, { from: "aurix", text: "Invalid approval request." }]);
        }
      } else {
        setMessages((m) => [...m, { from: "aurix", text: reply || "No response." }]);
      }
    } catch (error) {
      setMessages((m) => [...m, {
        from: "aurix", text: `Error: ${String(error)}`,
      }]);
    } finally {
      setStatus("standby");
    }
  }, []);

  const sendMessage = async (event) => {
    event.preventDefault();
    if (status !== "standby") return;
    await sendText(draft);
  };

  const handleMicPress = async () => {
    if (status !== "standby") return;
    if (!isTauri()) {
      setMessages((m) => [...m, { from: "aurix", text: "Microphone requires the desktop app." }]);
      return;
    }
    setStatus("listening");
    try {
      const data = await invoke("listen_voice");
      if (data.text?.trim()) {
        await sendText(data.text);
      } else {
        setMessages((m) => [...m, {
          from: "aurix", text: "No speech detected; nothing was submitted.",
        }]);
      }
    } catch (error) {
      setMessages((m) => [...m, {
        from: "aurix", text: `Voice unavailable: ${String(error)}`,
      }]);
    } finally {
      setStatus("standby");
    }
  };

  const current = STATUS[status];
  const lastAssistantReply = [...messages].reverse().find((item) => item.from === "aurix")?.text ?? "";

  const speakLastReply = async () => {
    if (!isTauri() || !lastAssistantReply) return;
    setSpeechStatus("Requesting local speech synthesis…");
    try {
      await invoke("speak_text", { text: lastAssistantReply.slice(0, 800) });
      setSpeechStatus("Local speech requested. Use Stop speech to interrupt playback.");
    } catch (error) {
      setSpeechStatus(`Speech unavailable: ${String(error)}`);
    }
  };

  const stopSpeech = async () => {
    if (!isTauri()) return;
    try {
      await invoke("stop_speech");
      setSpeechStatus("Speech stop requested.");
    } catch (error) {
      setSpeechStatus(`Cannot stop speech: ${String(error)}`);
    }
  };

  return (
    <div className="shell">
      <div className="bg-layer" aria-hidden="true">
        <span className="blob blob-a" />
        <span className="blob blob-b" />
        <span className="blob blob-c" />
        <div className="grid-overlay" />
        <div className="scanline" />
      </div>

      {/* Left navigation */}
      <aside className="nav">
        <div className="brand">
          <div className="brand-mark">A</div>
          <div>
            <div className="brand-name">AURIX</div>
            <div className="brand-sub">on-device intelligence</div>
          </div>
        </div>

        <nav className="nav-list">
          {["Command", "Telemetry", "Memory", "System", "Activity"].map((item) => (
            <button key={item} className={`nav-item ${activeView === item ? "is-active" : ""}`} onClick={() => setActiveView(item)} aria-current={activeView === item ? "page" : undefined}>
              <span className="nav-dot" />
              {item}
            </button>
          ))}
        </nav>

        <div className="nav-footer">
          <span className={`pulse pulse-${current.tone}`} />
          {current.label}
        </div>
      </aside>

      {/* Center stage */}
      <main className="stage">
        <header className="stage-header">
          <span className="date">
            {new Date().toLocaleDateString("en-US", {
              weekday: "short",
              day: "numeric",
              month: "short",
              year: "numeric",
            })}
          </span>
          <span className="online">
            <span className={`pulse ${workerOnline ? "pulse-accent" : "pulse-warn"}`} /> {workerOnline ? "Worker connected" : "Worker unavailable"}
          </span>
        </header>


        {activeView === "Command" ? (
          <>
                    <div className="orb-wrap">
          <div className={`orb ${status !== "standby" ? "orb-active" : ""}`}>
            <div className="orb-ring ring-1" />
            <div className="orb-ring ring-2" />
            <div className="orb-ring ring-3" />
            <div className="orbit-particles">
              <span />
              <span />
              <span />
            </div>
            <div className="orb-core">
              <span className="orb-title">AURIX</span>
              <span className={`orb-status status-${current.tone}`}>{current.label}</span>
            </div>
          </div>
        </div>

        <p className="prompt">What can I help you with?</p>

        <div className="listen-block">
          <Waveform active={status === "listening"} />
          <button
            className={`mic-btn mic-${status}`}
            onClick={handleMicPress}
            aria-label="Transcribe microphone with local Whisper" disabled={status !== "standby"}
          >
            <svg viewBox="0 0 24 24" width="22" height="22" fill="none">
              <path
                d="M12 15a3 3 0 0 0 3-3V6a3 3 0 1 0-6 0v6a3 3 0 0 0 3 3Z"
                stroke="currentColor"
                strokeWidth="1.6"
              />
              <path
                d="M6 11v1a6 6 0 0 0 12 0v-1M12 19v3"
                stroke="currentColor"
                strokeWidth="1.6"
                strokeLinecap="round"
              />
            </svg>
          </button>
          <span className={`listen-status status-${current.tone}`}>
            {status === "processing" ? "Processing…" : current.label}
          </span>
        </div>

          </>
        ) : (
          <section className="workspace-panel" aria-label={activeView}>
            {activeView === "Telemetry" && (
              <>
                <h2>Telemetry history</h2>
                <p>Measured native system metrics. Raw samples are retained 24h, minute data 30 days, and hourly aggregates thereafter.</p>
                <div className="telemetry-controls">
                  {["1h", "24h", "7d"].map((range) =>
                    <button key={range} className={range === historyWindow ? "selected-range" : ""}
                      onClick={() => setHistoryWindow(range)}>{range}</button>
                  )}
                  <select value={historyMetric} onChange={(e) => setHistoryMetric(e.target.value)}
                    aria-label="Chart metric">
                    {["cpu", "ram", "gpu", "gpu_temp", "vram_mb"].map((m) =>
                      <option value={m} key={m}>{m}</option>)}
                  </select>
                  <button onClick={exportHistory} disabled={!isTauri()}>Export CSV</button>
                </div>
                <HistoryChart samples={telemetryHistory} metric={historyMetric} />
                {exportedPath && <p role="status">CSV export: {exportedPath}</p>}
              </>
            )}
            {activeView === "Memory" && (
              <>
                <h2>Encrypted memory</h2>
                <p>Stored locally with AES-GCM and a Windows DPAPI-wrapped key. Memory is opt-in.</p>
                {!settings?.memory_enabled && (
                  <button type="button" onClick={updateMemory} disabled={!workerOnline || !settings}>
                    Enable local memory
                  </button>
                )}
                {memoryError && <p role="alert">{memoryError}</p>}
                {settings?.memory_enabled && (
                  <>
                    <form onSubmit={addFact} className="workspace-form">
                      <select value={memoryKind} onChange={(e) => setMemoryKind(e.target.value)} aria-label="Memory type">
                        {["semantic", "episodic", "procedural", "knowledge"].map((v) =>
                          <option key={v} value={v}>{v}</option>)}
                      </select>
                      <textarea value={memoryText} onChange={(e) => setMemoryText(e.target.value)}
                        maxLength={12000} rows={3} placeholder="Memory to save" aria-label="Memory content" />
                      <button type="submit">Save memory</button>
                    </form>
                    <input className="workspace-search" placeholder="Filter recent memories"
                      value={memorySearch} onChange={(e) => setMemorySearch(e.target.value)} />
                    <div className="memory-list">
                      {memories.filter((m) => m.content.toLowerCase().includes(memorySearch.toLowerCase()))
                        .map((m) => (
                          <article className="memory-item" key={m.id}>
                            <span>{m.kind} · {new Date(m.created * 1000).toLocaleDateString()}</span>
                            <p>{m.content}</p>
                            <button onClick={() => deleteFact(m.id)}>Delete</button>
                          </article>
                        ))}
                    </div>
                  </>
                )}
              </>
            )}
            {activeView === "System" && (
              <>
                <h2>System controls</h2>
                <p>Worker: {workerOnline ? "Connected" : "Disconnected"}. Models need local files.</p>
                <div className="setting-line">
                  <div><strong>Offline mode</strong><p>Blocks the agent's network-capable tools while enabled.</p></div>
                  <button onClick={updateOffline} disabled={!workerOnline || !settings}>
                    {settings?.offline ? "Offline: ON" : "Offline: OFF"}
                  </button>
                </div>
                <div className="setting-line">
                  <div><strong>Persistent memory</strong>
                    <p>Encrypted on this Windows account. Turning off stops new memory capture; it does not delete existing records.</p>
                  </div>
                  <button onClick={updateMemory} disabled={!workerOnline || !settings}>
                    {settings?.memory_enabled ? "Memory: ON" : "Memory: OFF"}
                  </button>
                </div>
                <div className="setting-line">
                  <div><strong>Emergency action block</strong><p>Prevents new tools; does not forcibly terminate in-progress OS operations. Shortcut: Ctrl+Shift+X in this window.</p></div>
                  <button onClick={toggleStop} disabled={!workerOnline || !settings} className="stop-button">
                    {settings?.stopped ? "Resume new actions" : "Block new actions"}
                  </button>
                </div>
              </>
            )}
            {activeView === "Activity" && (
              <>
                <h2>Activity and authorization log</h2>
                <p>Event ledger stores tool names and fingerprints without user content. Verify status: {
                  auditVerified === null ? "Unavailable" : auditVerified ? "Valid HMAC chain" : "Verification failed"
                }</p>
                <div className="memory-list">
                  {auditEvents.map((event) => (
                    <article className="memory-item" key={event.seq}>
                      <span>#{event.seq} · {new Date(event.timestamp * 1000).toLocaleString()}</span>
                      <p>{event.tool} — {event.stage}</p>
                    </article>
                  ))}
                </div>
                <h3>Current session conversation</h3>
                <div className="memory-list">
                  {messages.map((m, i) => <article className="memory-item" key={i}>
                    <strong>{m.from === "user" ? "User" : "LUNA"}</strong><p>{m.text}</p>
                  </article>)}
                </div>
              </>
            )}
          </section>
        )}
      </main>

      {/* Right sidebar: status, telemetry, chat */}
      <aside className="side">
        <section className="panel">
          <h3 className="panel-title">System status</h3>
          <div className="status-grid">
            <div className="status-item">
              <span>Core system</span>
              <b className={workerOnline ? "ok" : ""}>{workerOnline ? "Connected" : "Disconnected"}</b>
            </div>
            <div className="status-item">
              <span>Neural link</span>
              <b>Unverified</b>
            </div>
            <div className="status-item">
              <span>Security</span>
              <b>Native approval</b>
            </div>
            <div className="status-item">
              <span>Network</span>
              <b>Local only</b>
            </div>
          </div>
        </section>

        <section className="panel">
          <h3 className="panel-title">Telemetry</h3>
          <Bar label="CPU" value={telemetry.cpu} />
          <Bar label="RAM" value={telemetry.ram} accent="var(--accent-2)" />
          <Bar label="GPU" value={telemetry.gpu} />
          <Bar label="VRAM" value={telemetry.vram_mb} unit=" MB" />
          <Bar
            label="GPU temp"
            value={telemetry.gpu_temp}
            unit="°C"
            accent={telemetry.gpu_temp > 72 ? "var(--warn)" : "var(--accent-2)"}
          />
        </section>

        <section className="panel panel-chat">
          <h3 className="panel-title">Chat</h3>
          <div className="speech-controls" role="group" aria-label="Local Piper voice controls">
            <button type="button" onClick={speakLastReply} disabled={!workerOnline || !lastAssistantReply}>Speak last reply</button>
            <button type="button" onClick={stopSpeech} disabled={!workerOnline}>Stop speech</button>
          </div>
          {speechStatus && <div className="speech-status" role="status">{speechStatus}</div>}
          <div className="chat-log" ref={logRef} role="log" aria-live="polite" aria-label="LUNA conversation">
            {messages.map((m, i) => (
              <div key={i} className={`chat-msg chat-${m.from}`}>
                {m.text}
              </div>
            ))}
          </div>
          {approval && (
            <div className="approval-card" role="alert">
              <p><strong>Approval required:</strong> {approval.description}</p>
              <div className="approval-actions">
                <button type="button" disabled={approving} onClick={() => respondToApproval(false)}>Reject</button>
                <button type="button" disabled={approving} onClick={() => respondToApproval(true)}>Review in native dialog</button>
              </div>
            </div>
          )}
          <form className="chat-input" onSubmit={sendMessage}>
            <input
              disabled={status !== "standby"}
              aria-label="Message LUNA"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              placeholder="Message AURIX…"
            />
            <button type="submit" aria-label="Send">
              <svg viewBox="0 0 24 24" width="16" height="16" fill="none">
                <path d="M4 12h15M13 5l7 7-7 7" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </button>
          </form>
        </section>
      </aside>
    </div>
  );
}
