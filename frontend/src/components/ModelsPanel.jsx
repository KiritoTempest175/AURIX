import { useCallback, useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";

const NATIVE = () => typeof window !== "undefined" && Boolean(window.__TAURI_INTERNALS__);
const OFFLINE_WARNING = "For installing Ollama or downloading models, turn OFF Offline Mode in System controls.";

export default function ModelsPanel({ workerOnline, offline }) {
  const [snapshot, setSnapshot] = useState(null);
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [progress, setProgress] = useState(null);
  const [customTag, setCustomTag] = useState("");

  const refresh = useCallback(async () => {
    if (!NATIVE() || !workerOnline) return;
    try {
      setSnapshot(await invoke("list_model_choices"));
      setError("");
    } catch (err) {
      setError(`Model service unavailable: ${String(err)}`);
    }
  }, [workerOnline]);

  useEffect(() => { refresh(); }, [refresh]);
  useEffect(() => {
    if (!NATIVE()) return;
    let unsubscribe = null;
    let active = true;
    listen("aurix://ollama-progress", (event) => {
      if (active) setProgress(event.payload);
    }).then((stop) => { if (active) unsubscribe = stop; else stop(); }).catch(() => {});
    return () => { active = false; if (unsubscribe) unsubscribe(); };
  }, []);

  const perform = async (key, action) => {
    setBusy(key);
    setError("");
    setStatus("");
    try {
      const message = await action();
      setStatus(typeof message === "string" ? message : "Model preference saved.");
      await refresh();
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy("");
    }
  };

  const installOllama = () => {
    if (offline) return setError(OFFLINE_WARNING);
    return perform("install", () => invoke("install_ollama"));
  };

  const download = (model) => {
    if (offline) return setError(OFFLINE_WARNING);
    setProgress({ model, status: "Starting download", completed: 0, total: null });
    return perform(`pull:${model}`, () => invoke("pull_ollama_model", { model }));
  };

  const activate = (model) => perform(`activate:${model}`, () =>
    invoke("activate_model", { backend: "ollama", model })
  );

  const switchToGguf = () => perform("gguf", () =>
    invoke("activate_model", {
      backend: "llama_cpp", model: snapshot?.selected || "qwen3:4b",
    })
  );

  const remove = (model) => perform(`delete:${model}`, () =>
    invoke("remove_ollama_model", { model })
  );

  const installed = snapshot?.installed || [];
  const recommended = snapshot?.recommendations || [];
  const models = [...recommended];
  for (const name of installed) {
    if (!models.some((entry) => entry.name === name)) {
      models.push({ name, label: name, purpose: "Installed model" });
    }
  }
  const selected = snapshot?.selected;
  const activeOllama = snapshot?.backend === "ollama";
  const percentage = progress?.total > 0
    ? Math.min(100, Math.round(100 * progress.completed / progress.total))
    : null;

  return (
    <div className="models-panel">
      <h2>Models & local inference</h2>
      <p>Select a free local model. Ollama handles model management and device-aware acceleration. No QLoRA training is used to chat or perform actions.</p>
      <div className="models-banner">
        <span>Backend: <strong>{snapshot?.backend || "Checking..."}</strong></span>
        <span>Ollama: <strong>{snapshot?.ollama_connected ? "Connected" : "Not running"}</strong></span>
        <span>Selected: <strong>{selected || "Not selected"}</strong></span>
      </div>
      <div className="model-actions">
        <button type="button" disabled={!workerOnline || Boolean(busy)} onClick={refresh}>Refresh models</button>
        <button type="button" disabled={!workerOnline || Boolean(busy) || offline} onClick={installOllama}>
          {busy === "install" ? "Installing Ollama..." : "Install Ollama (Windows)"}
        </button>
        <button type="button" disabled={!workerOnline || Boolean(busy)} onClick={switchToGguf}>
          Use existing GGUF backend
        </button>
      </div>
      {!snapshot?.ollama_connected && <p>Open Ollama after installation. AURIX will connect to its local service, not a cloud LLM API. Installation uses the official <strong>Ollama.Ollama</strong> winget package.</p>}
      {offline && <p className="model-notice">{OFFLINE_WARNING} Already installed models still work offline.</p>}
      <h3>Recommended models</h3>
      <div className="models-grid">
        {models.map((model) => {
          const present = installed.includes(model.name);
          const active = activeOllama && selected === model.name;
          return (
            <article key={model.name} className="model-card">
              <strong>{model.label}</strong>
              <span>{model.name}</span>
              <p>{model.purpose}</p>
              <div className="model-actions">
                {active && <span className="model-active">Active</span>}
                {present && !active && <button type="button" disabled={Boolean(busy)} onClick={() => activate(model.name)}>Use model</button>}
                {!present && <button type="button" disabled={Boolean(busy) || offline || !snapshot?.ollama_connected}
                  onClick={() => download(model.name)}>Download</button>}
                {present && !active && <button type="button" disabled={Boolean(busy)} onClick={() => remove(model.name)}>Remove</button>}
              </div>
            </article>
          );
        })}
      </div>
      <form className="model-custom" onSubmit={(event) => {
        event.preventDefault();
        const name = customTag.trim();
        if (name) download(name);
      }}>
        <label htmlFor="ollama-custom">Other Ollama model tag</label>
        <input id="ollama-custom" value={customTag} maxLength={120}
          onChange={(event) => setCustomTag(event.target.value)}
          placeholder="e.g. qwen3:14b" />
        <button type="submit" disabled={!customTag.trim() || Boolean(busy) || offline || !snapshot?.ollama_connected}>Download custom model</button>
      </form>
      {progress && <div role="status" className="model-progress">
        <strong>{progress.model}</strong> · {progress.status || "Downloading"}
        {percentage != null && <progress max="100" value={percentage} aria-label="Model download progress">{percentage}%</progress>}
        {percentage != null && <span>{percentage}%</span>}
      </div>}
      {status && <p role="status">{status}</p>}
      {error && <p role="alert" className="model-error">{error}</p>}
      <p className="model-footnote">Model downloads require internet and disk space. The models themselves run locally after installation. Hardware acceleration depends on the available Ollama backend and drivers.</p>
    </div>
  );
}
