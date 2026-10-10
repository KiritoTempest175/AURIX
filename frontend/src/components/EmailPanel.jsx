import { useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";

/** Credentials go only to the authenticated native worker. Never persist in UI. */
export default function EmailPanel({ workerOnline, offline }) {
  const [state, setState] = useState(null);
  const [address, setAddress] = useState("");
  const [password, setPassword] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (!workerOnline) return;
    invoke("email_configuration").then(setState)
      .catch(() => setMessage("Email configuration cannot be loaded."));
  }, [workerOnline]);
  const save = async (event) => {
    event.preventDefault();
    if (!workerOnline || busy) return;
    setBusy(true); setMessage("");
    try {
      const saved = await invoke("save_email_configuration", { address: address.trim(), password });
      setState(saved);
      setPassword("");
      setMessage("Credentials securely saved for this Windows user.");
    } catch {
      setMessage("Could not save credentials. Check the email, app password, and worker connection.");
      setPassword("");
    } finally { setBusy(false); }
  };
  const remove = async () => {
    if (!window.confirm("Remove saved SMTP credentials from this device?")) return;
    setBusy(true);
    try {
      await invoke("remove_email_configuration");
      setState({ configured: false, address: "" });
      setAddress(""); setPassword("");
      setMessage("Stored email credentials removed.");
    } catch { setMessage("Could not remove email credentials."); }
    finally { setBusy(false); }
  };
  return (
    <div className="email-settings">
      <div className="section-eyebrow">INTEGRATIONS / EMAIL</div>
      <h2>Email account</h2>
      <p>Connect Gmail SMTP using a Google app password. Credentials are encrypted with Windows DPAPI and never shown after saving. No terminal or manual worker configuration is required.</p>
      <div className="integration-status" role="status">
        <span className={state?.configured ? "status-light ready" : "status-light"} />
        {state?.configured ? `Configured: ${state.address}` : "No email account connected"}
      </div>
      <form onSubmit={save} className="email-form">
        <label htmlFor="email-address">Gmail address</label>
        <input id="email-address" name="email" type="email" autoComplete="username" required maxLength={254}
          placeholder="you@gmail.com" value={address} onChange={e => setAddress(e.target.value)} />
        <label htmlFor="email-password">App password</label>
        <input id="email-password" name="app-password" type="password" autoComplete="new-password" required minLength={8} maxLength={256}
          placeholder="Paste your Gmail app password" value={password} onChange={e => setPassword(e.target.value)} />
        <div className="model-actions">
          <button type="submit" disabled={!workerOnline || busy}>Save securely</button>
          {state?.configured && <button type="button" onClick={remove} disabled={!workerOnline || busy}>Disconnect account</button>}
        </div>
      </form>
      {message && <p role="status">{message}</p>}
      {offline && <p className="model-notice">Offline Mode is active. You can configure email offline, but sending is blocked until you disable it.</p>}
      <p className="setting-note">Email is only sent after you review and approve each recipient, subject and message. A Gmail app password must be created in your Google account; AURIX does not ask for your main Google password.</p>
    </div>
  );
}
