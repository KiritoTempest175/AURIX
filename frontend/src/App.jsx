import { useEffect, useRef, useState, useCallback } from "react";
import { invoke } from "@tauri-apps/api/core";

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
  const [stats, setStats] = useState({
    cpu: null,
    ram: null,
    gpu: null,
    gpu_temp: null,
  });

  useEffect(() => {
    let active = true;
    let pending = false;

    const poll = async () => {
      if (pending) return;
      pending = true;
      try {
        const data = await apiTelemetry();
        if (active) {
          setStats({
            cpu: data.cpu == null ? null : Math.round(data.cpu),
            ram: data.ram == null ? null : Math.round(data.ram),
            gpu: data.gpu == null ? null : Math.round(data.gpu),
            gpu_temp: data.gpu_temp == null ? null : Math.round(data.gpu_temp),
          });
        }
      } catch {
        // Service can start after UI; retry on next tick.
      } finally {
        pending = false;
      }
    };

    poll();
    const id = setInterval(poll, 3000);
    return () => {
      active = false;
      clearInterval(id);
    };
  }, []);

  return stats;
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
    { from: "aurix", text: "LUNA ready for text commands. Voice input is not connected in this build." },
  ]);
  const [draft, setDraft] = useState("");
  const logRef = useRef(null);
  const [approval, setApproval] = useState(null);
  const [workerOnline, setWorkerOnline] = useState(false);
  const [approving, setApproving] = useState(false);

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

  // Never simulate captured speech or claim that microphone capture succeeded.
  const handleMicPress = () => {
    setMessages((items) => [
      ...items,
      { from: "aurix", text: "Voice input is not yet available. Use text chat." },
    ]);
  };

  const respondToApproval = async (accept) => {
    const currentApproval = approval;
    if (!currentApproval || approving) return;
    setApproval(null);
    if (!accept) {
      setMessages((items) => [...items, { from: "aurix", text: "Action rejected." }]);
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

  // --- Chat send (wired to Python AI brain) ---
  const sendMessage = useCallback(
    async (e) => {
      e.preventDefault();
      const text = draft.trim();
      if (!text) return;

      setMessages((m) => [...m, { from: "user", text }]);
      setDraft("");
      setStatus("processing");

      try {
        const data = await apiDispatch(text);
        const reply = String(data.reply ?? "");
        if (reply.startsWith("TRUST_TOKEN_REQUIRED:")) {
          const [, id, ...description] = reply.split(":");
          if (/^[a-f0-9]{12}$/i.test(id)) {
            setApproval({ id, description: description.join(":") });
            setMessages((m) => [...m, {
              from: "aurix",
              text: "This action requires your explicit confirmation.",
            }]);
          } else {
            setMessages((m) => [...m, { from: "aurix", text: "Invalid approval request." }]);
          }
        } else {
          setMessages((m) => [...m, { from: "aurix", text: reply || "No response." }]);
        }
      } catch (err) {
        setMessages((m) => [
          ...m,
          { from: "aurix", text: `Connection error: ${err.message}` },
        ]);
      } finally {
        setStatus("standby");
      }
    },
    [draft]
  );

  const current = STATUS[status];

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
          {["Command", "Activity Log", "Integrations", "System"].map((item, i) => (
            <button key={item} className={`nav-item ${i === 0 ? "is-active" : ""}`} disabled={i !== 0} title={i === 0 ? "Command" : "Not yet implemented"}>
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
            aria-label="Toggle listening"
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
          <Bar
            label="GPU temp"
            value={telemetry.gpu_temp}
            unit="°C"
            accent={telemetry.gpu_temp > 72 ? "var(--warn)" : "var(--accent-2)"}
          />
        </section>

        <section className="panel panel-chat">
          <h3 className="panel-title">Chat</h3>
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
