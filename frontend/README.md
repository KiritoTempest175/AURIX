# AURIX desktop shell

React 18 + Vite + Tauri 2 interface for the LUNA agent. The **native** Tauri process owns the session credential used to reach the Python loopback worker. The agent runner loads a user-provided GGUF file lazily without cloud APIs. The browser preview is a UI-only environment; it cannot invoke desktop actions.

## Development

```powershell
npm install
npm run tauri dev
```

`npm run dev` opens only the browser preview. It does **not** start the worker.

Source-mode development requires Python. The experimental PyInstaller sidecar bundle script lives in `installer/build_windows.ps1`; its unsigned outputs are not yet suitable for general end users.

## Backend boundary

A 256-bit per-session token is created by Rust on startup. It is injected into the worker environment and used by native `invoke` commands; never share it with React. The bridge is loopback-bound and denies browser Origins. Exact pending actions are previewed from the worker; Tauri opens a native Windows confirmation before requesting execution.

The voice button, GPU telemetry, and most navigation panels are incomplete and clearly labeled, not represented as fully operational. See the root README for the audited status.
