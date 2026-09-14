# AURIX

React + Tauri desktop shell for AURIX, styled after your reference (dark
navy, cyan-glow core), with the wordmark changed to AURIX, chat moved to a
side panel instead of the center focus, live CPU/RAM/GPU/GPU-temp telemetry,
and a listen control that shows Standby / Listening / Processing with an
animated waveform.

## Structure
- `src/App.jsx`, `src/App.css` — the whole UI (orb centerpiece, left nav,
  right sidebar with system status, telemetry bars, and chat).
- `src-tauri/` — minimal Tauri v2 backend. `get_telemetry` currently reads
  real CPU/RAM via `sysinfo`; GPU usage/temp are stubbed at 0 — wire in
  `nvml-wrapper` there for real NVIDIA readings (see comment in `main.rs`).

## Run in the browser (fastest way to preview the design)
```bash
npm install
npm run dev
```

## Run as the actual desktop app
Requires the Rust toolchain and Tauri's OS prerequisites
(https://v2.tauri.app/start/prerequisites/).
```bash
npm install
npm run tauri dev      # dev window
npm run tauri build    # production installer
```

## Wiring real telemetry to the UI
`useSimulatedTelemetry` in `App.jsx` currently fakes the numbers with a
random walk so the panel is alive in the browser preview. Swap it for:
```js
import { invoke } from "@tauri-apps/api/core";
const stats = await invoke("get_telemetry"); // { cpu, ram, gpu, gpu_temp }
```
polled on an interval, once the app is running inside Tauri.

## Icons
No app icons are included yet. Run `npx tauri icon path/to/logo.png` once
you have an AURIX mark to generate the full icon set into `src-tauri/icons/`.
