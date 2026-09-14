import { useEffect, useRef, useState, useCallback } from "react";

// ---------------------------------------------------------------------------
// Bridge API helpers — works in both Tauri (invoke) and browser (fetch) mode
// ---------------------------------------------------------------------------
let tauriInvoke = null;

try {
  // Dynamic import so it doesn't crash outside of Tauri
  const tauriCore = await import("@tauri-apps/api/core");
  tauriInvoke = tauriCore.invoke;
} catch {
  // Running in plain browser — fall back to direct HTTP
}

const BRIDGE_URL = "http://127.0.0.1:9721";

async function callBridge(method, path, body) {
  const opts = { method, headers: { "Content-Type": "application/json" } };
  if (body) opts.body = JSON.stringify(body);
  const res = await fetch(`${BRIDGE_URL}${path}`, opts);
  return res.json();
}

async function apiDispatch(text) {
  if (tauriInvoke) {
    return tauriInvoke("send_message", { payload: { text } });
  }
  return callBridge("POST", "/dispatch", { text });
}

async function apiTelemetry() {
  if (tauriInvoke) {
    try {
      return await tauriInvoke("get_bridge_telemetry");
    } catch {
      // Bridge not running — fall back to native sysinfo command
      return tauriInvoke("get_telemetry");
    }
  }
  return callBridge("GET", "/telemetry");
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
    cpu: 0,
    ram: 0,
    gpu: 0,
    gpu_temp: 0,
  });

  useEffect(() => {
    let active = true;

    const poll = async () => {
      try {
        const data = await apiTelemetry();
        if (active) {
          setStats({
            cpu: Math.round(data.cpu ?? 0),
            ram: Math.round(data.ram ?? 0),
            gpu: Math.round(data.gpu ?? 0),
            gpu_temp: Math.round(data.gpu_temp ?? data.gpuTemp ?? 0),
          });
        }
      } catch {
        // Bridge may not be up yet — keep polling silently
      }
    };

    poll();
    const id = setInterval(poll, 2000);
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
          {value}
          <span className="bar-unit">{unit}</span>
        </span>
      </div>
      <div className="bar-track">
        <div
          className="bar-fill"
          style={{ width: `${Math.min(100, value)}%`, background: accent }}
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
    { from: "aurix", text: "Systems nominal. Say the word when you're ready." },
  ]);
  const [draft, setDraft] = useState("");
  const logRef = useRef(null);
  const timers = useRef([]);

  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [messages]);

  useEffect(() => () => timers.current.forEach(clearTimeout), []);

  // --- Mic press (simulated listen cycle for now) ---
  const handleMicPress = () => {
    timers.current.forEach(clearTimeout);
    timers.current = [];

    if (status === "standby") {
      setStatus("listening");
      const t1 = setTimeout(() => {
        setStatus("processing");
        const t2 = setTimeout(() => {
          setMessages((m) => [
            ...m,
            { from: "user", text: "(voice input captured)" },
            { from: "aurix", text: "Got it — working on that now." },
          ]);
          setStatus("standby");
        }, 1400);
        timers.current.push(t2);
      }, 2600);
      timers.current.push(t1);
    } else {
      setStatus("standby");
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
        setMessages((m) => [...m, { from: "aurix", text: data.reply || "Acknowledged." }]);
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
            <button key={item} className={`nav-item ${i === 0 ? "is-active" : ""}`}>
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
            <span className="pulse pulse-accent" /> System online
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
              <b className="ok">Online</b>
            </div>
            <div className="status-item">
              <span>Neural link</span>
              <b className="ok">Ready</b>
            </div>
            <div className="status-item">
              <span>Security</span>
              <b className="ok">Encrypted</b>
            </div>
            <div className="status-item">
              <span>Network</span>
              <b className="ok">Stable</b>
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
          <div className="chat-log" ref={logRef}>
            {messages.map((m, i) => (
              <div key={i} className={`chat-msg chat-${m.from}`}>
                {m.text}
              </div>
            ))}
          </div>
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
