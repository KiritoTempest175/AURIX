# AURIX release readiness — 2026-10-10

**Release decision: blocked.** This is an engineering evidence log, not a 10/10 rating. The requested product is substantially larger than the current implementation. Passing unit tests is necessary but does not establish Windows hardware behavior, an adversarial security boundary, or reliable autonomous computer use.

## Verified locally

- Existing supported Python tests plus release-hardening regressions execute without a GPU or downloaded model. Legacy research tests require their optional dependencies and run separately on Windows CI.
- React production bundle and Vitest tests pass.
- Live HTTP tests exercise hostile Origins, busy inference, rate limiting, and emergency-stop availability.
- Model import tests verify checksum mismatch preserves the installed model and cleans temporary files.
- Approval tests cover exact arguments, NUL rejection, replay/expiry in the existing policy suite, and invalidation across stop/resume.
- The desktop router now selects embedded llama.cpp, not Ollama. Historical Ollama/research modules remain in the source but the desktop exposes no Ollama commands.

Windows CI, installer results and browser evidence are authoritative in PR #15. Do not infer a pass from workflow definitions or this document. A browser runtime download failed in the editing environment, so visual/axe checks are delegated to the newly added Windows CI job, not claimed as locally passed.

## Changes and reasons

| Files | Change |
|---|---|
| `ai_brain/agent_router.py` | Normalize known-app aliases; route production chat to the embedded GGUF singleton. |
| `frontend/bridge_server.py` | Reject queued actions immediately, bound socket reads, rate-limit mutations, preserve emergency-control access, remove inherited session secret, expose local model import and accurate model readiness. |
| `ai_engine/inference/local_gguf.py` | Reap the actual singleton, explicitly close idle models, preserve bounded conversation history, serialize initialization and model replacement. |
| `scripts/import_model.py` | Hash the copied bytes before atomic replacement; unique temporary files prevent concurrent import collisions. |
| `frontend/src-tauri/src/main.rs` | Release builds cannot execute a working-directory Python checkout; private HTTP does not use proxies or follow redirects; native approval precedes local model import. |
| `ai_brain/tool_executor.py` | Complete exact-argument preview, bounded native preview size, deceptive-control rejection, safe returned error code, stop-generation invalidation. |
| `security/action_control.py`, `ai_brain/dispatcher.py` | Deterministic stop phrase; stop speech and invalidate pending approvals. This is not an OS-level kill switch. |
| `native_ui/audio/wake_service.py` | Suppress wake processing during speech, clear queued events when disabled. This deliberately does not claim barge-in. |
| `ai_brain/app_control.py` | Request WM_CLOSE instead of force-terminating apps; preserve save prompts and accurately report a close request. |
| `security/config_loader.py` | Reject malformed section types, coerced booleans, fractional contexts and invalid path arrays. |
| `frontend/src/components/ModelsPanel.jsx`, `frontend/src/App.jsx` | Offline verified-model setup, labeled inputs, time-aware greeting and non-overlapping health polls. |
| `pyproject.toml`, `installer/requirements-desktop.lock` | Keep research dependencies out of normal runtime; pin and hash the Windows desktop dependency resolution; bundle llama.cpp. |
| `installer/build_windows.ps1`, `installer/smoke_installed.ps1` | Package locked runtime; test actual installer with Python/Node/Rust removed from PATH. This is runtime isolation on a hosted runner, not a clean VM. |
| `.github/workflows/*`, `frontend/e2e/*` | PR installer builds, scoped accessibility/layout tests, runtime security scanning, reproducible npm install. |

## Original audit mapping

The attachment supplies finding IDs and selected descriptions, not the full original audit text. This mapping follows the repository's prior tracker and does not invent missing audit details.

| Finding | Current disposition and evidence |
|---|---|
| C-01 | Partial: authenticated loopback HTTP, no browser origins, no proxies, bounded reads/rate limits. Protected native IPC is still required. |
| C-02 | Partial: native exact preview, one-use expiring action fingerprint, stop invalidation. Authorization/execution still lives in Python; compromised-worker resistance is NOT solved. |
| H-01 | Generic shell remains disabled; restricted-token/Job Object execution not implemented. |
| H-02 | Existing canonical file-root checks; race-safe native file operations and full unification remain. |
| H-03 | Existing component-safe vault containment and regression test. |
| H-04 | Current vault ignored; removed hardcoded caller identity. Historical Git cleanup is not performed. |
| H-05 | Release source fallback removed; installer worker smoke plus installed-runtime smoke added. Actual results pending. |
| H-06 | Existing committed ICO used by packaging. Complete asset/installer visual audit pending. |
| H-07 | No fake training added. Real scheduled QLoRA, evaluation/activation/rollback remain unimplemented. |
| H-08 | Adaptive checks remain; hard 6 GB VRAM / 12 GB RAM enforcement and measured idle targets remain unimplemented. |
| H-09 | Full argument preview plus bounded messages and control-character checks. Rich scrollable native diff review remains. |
| H-10 | Existing CSP; full capability/IPC penetration testing remains. |
| M-01 | Busy inference no longer queues stale physical actions; health/control requests remain separate. Inference remains serialized. |
| M-02 | Central tool failures use a safe code; legacy logs and controllers still need comprehensive secret-scrubbing review. |
| M-03 | Fixed private HTTP proxy/redirect exposure; complete cancellation and worker tree supervision remain. |
| M-04 | Existing Tauri/browser separation retained; browser UI tests added. |
| M-05 | Real microphone backends remain; actual input, language packs and wake recognition need hardware testing. |
| M-06 | Existing native telemetry/history/CSV remain; measurements and hardware consistency need validation. |
| M-07 | Strict active TOML validation improved; legacy configuration/naming consolidation remains. |
| M-08 | npm lock plus Windows runtime hash lock committed; Cargo lock and all scanners need passing evidence. |
| M-09 | Live transport/security regression suite and installed-runtime smoke added; full native IPC abuse tests remain. |
| M-10 | Existing DPAPI-keyed audit hash chain retained; it is not an independently trusted authorization ledger. |
| M-11 | README rewritten to match active runtime and limitations. |
| M-12 | Unsandboxed generic shell remains disabled. Git/process helpers still need bounded output and child-tree termination. |
| L-01 | Prior duplicate class removal retained. |
| L-02 | Model-panel automated accessibility/layout gate added; full WCAG audit and native screen-reader testing remain. |
| L-03 | Existing functional panels retained; complete requested tool/plugin/training views remain. |
| L-04 | Correct repo/setup and explicit test scope documented. |
| L-05 | Product/persona naming retained; complete legacy cleanup remains. |

## Final release gates

1. Passing exact-commit Windows Python/Rust/frontend/security jobs and installed-runtime smoke.
2. Clean Windows 10/11 VM install/uninstall/upgrade with no developer tools, including absent WebView2 handling.
3. Real GGUF answers and tool routing; supported model format/version; CPU-only, RTX 4060, resource peaks and recovery under pressure. The pinned package currently builds its default CPU backend, not a verified CUDA build.
4. Real microphone/wake/greeting/interrupt tests. Current wake mode repeatedly transcribes audio; it is not the requested tiny always-on detector and has no verified <150 MB idle budget.
5. SMTP and WhatsApp tests with explicitly authorized test accounts/recipients. Current email is SMTP, not the requested webmail UI automation. No emails or calls were sent as part of this work.
6. Independent native authorization, protected IPC, restricted process execution, full cancel/undo, filesystem race resistance.
7. Encrypted vector memory, tested backup/key rotation, actual QLoRA scheduling/regression evaluation, plugin SDK, IDE bridge and remaining capability set.
8. Signing identity and certificate provisioning; signed updater implementation, key custody and upgrade/rollback tests. No signing credentials were available in this task.

Do not publish a stable v0.2.0 release until these gates have concrete evidence. CI artifacts remain unsigned test builds. No stable installer is created merely by changing a version label.
