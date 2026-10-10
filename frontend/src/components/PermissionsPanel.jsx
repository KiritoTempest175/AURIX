import { useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";

const RULES = [
  ["allow_known_app_control", "Recognized application controls",
    "Open and close known applications without repeated approval. Unknown executables still require confirmation."],
  ["allow_local_file_reads", "Local file reading",
    "Read ordinary local files without prompting. Files remain subject to path restrictions."],
  ["allow_trusted_workspace_edits", "Trusted workspace edits",
    "Allow low-risk changes inside explicitly trusted project folders. Deletion, replacement, and risky changes still require approval."],
];

export default function PermissionsPanel({ workerOnline }) {
  const [values, setValues] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    if (!workerOnline) return;
    invoke("get_permission_preferences").then(setValues)
      .catch(() => setError("Unable to load permission preferences."));
  }, [workerOnline]);
  async function save(key, enabled) {
    if (!values || busy) return;
    setBusy(true);
    setError("");
    try {
      setValues(await invoke("set_permission_preferences", { values: { ...values, [key]: enabled } }));
    } catch (reason) {
      setError("Permission update was not saved: " + String(reason));
    } finally { setBusy(false); }
  }
  return <div className="permissions-panel">
    <span className="section-eyebrow">YOUR CONTROL / LUNA</span>
    <h2>Permission center</h2>
    <p>Decide which everyday local operations can run without repeated Windows confirmation. These preferences are saved on this device.</p>
    {RULES.map(([key, title, detail]) => <div className="setting-line" key={key}>
      <div><strong>{title}</strong><p>{detail}</p></div>
      <button type="button" role="switch" aria-checked={Boolean(values?.[key])}
        disabled={!workerOnline || !values || busy} onClick={() => save(key, !values[key])}>
        {values?.[key] ? "Allowed" : "Ask each time"}
      </button>
    </div>)}
    <section className="permission-guardrails">
      <strong>Always requires action-specific confirmation</strong>
      <p>Sending emails or WhatsApp messages, placing calls, deleting or replacing important files, running unknown applications, installing software, and privileged system changes. The Windows dialog shows the exact action before execution.</p>
    </section>
    {error && <p role="alert">{error}</p>}
  </div>;
}
