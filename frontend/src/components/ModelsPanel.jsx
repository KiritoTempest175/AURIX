import { useCallback, useEffect, useState } from "react";
import { invoke, isTauri } from "@tauri-apps/api/core";

export default function ModelsPanel({ workerOnline }) {
  const [snapshot, setSnapshot] = useState(null);
  const [path, setPath] = useState("");
  const [checksum, setChecksum] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const refresh = useCallback(async () => {
    if (!isTauri() || !workerOnline) return;
    try { setSnapshot(await invoke("list_model_choices")); }
    catch (err) { setError(String(err)); }
  }, [workerOnline]);
  useEffect(() => { refresh(); }, [refresh]);
  const importModel = async (event) => {
    event.preventDefault();
    if (busy) return;
    setBusy(true); setError(""); setMessage("");
    try {
      const result = await invoke("import_local_model", { path: path.trim(), sha256: checksum.trim() });
      setSnapshot(result);
      setMessage("Checksum verified. Model selected; it will load on your next message.");
    } catch (err) { setError(String(err)); }
    finally { setBusy(false); }
  };
  return <section className="models-panel" aria-labelledby="models-heading">
    <h2 id="models-heading">Local models</h2>
    <p>LUNA runs GGUF models inside its own worker with llama.cpp. Models are loaded on demand and released after the configured idle timeout.</p>
    <div className="models-banner">
      <span>Engine: <strong>{snapshot ? (snapshot.engine_available ? "Available" : "Missing from this build") : "Checking…"}</strong></span>
      <span>Model: <strong>{snapshot?.selected || "Not installed"}</strong></span>
      <span>State: <strong>{snapshot?.model_loaded ? "Loaded" : snapshot?.model_ready ? "Ready to load" : "Setup required"}</strong></span>
    </div>
    <form className="model-custom" onSubmit={importModel}>
      <h3>Import a verified GGUF file</h3>
      <p>Choose a compatible quantized model you have downloaded and obtain its SHA-256 checksum from its publisher. Import works offline and copies the file into AURIX’s model directory.</p>
      <label htmlFor="model-path">Full path to the GGUF file</label>
      <input id="model-path" value={path} onChange={e => setPath(e.target.value)} maxLength={4096} required placeholder="C:\Models\model.gguf" disabled={busy} />
      <label htmlFor="model-sha256">Publisher SHA-256 checksum</label>
      <input id="model-sha256" value={checksum} onChange={e => setChecksum(e.target.value)} pattern="[a-fA-F0-9]{64}" minLength={64} maxLength={64} required spellCheck={false} disabled={busy} />
      <button type="submit" disabled={!workerOnline || busy}>{busy ? "Verifying and importing…" : "Import and select model"}</button>
    </form>
    <button type="button" onClick={refresh} disabled={!workerOnline || busy}>Refresh status</button>
    {message && <p role="status">{message}</p>}
    {error && <p role="alert" className="model-error">{error}</p>}
    <p>CPU inference works without a GPU. Acceleration depends on the bundled llama.cpp backend. A valid checksum verifies the file, not its compatibility or response quality.</p>
  </section>;
}
