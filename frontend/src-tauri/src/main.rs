#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]
use rand::RngCore;
use nvml_wrapper::{Nvml, enum_wrappers::device::TemperatureSensor};
use serde::{Deserialize, Serialize};
use std::path::{Path, PathBuf};
use std::process::{Child, Command};
use std::sync::Mutex;
use std::time::Duration;
use sysinfo::System;
use tauri::{Emitter, Manager, State};

mod telemetry_store;
use telemetry_store::{MetricPoint, TelemetryStore};

const BRIDGE_URL: &str = "http://127.0.0.1:9721";

struct BridgeState {
    token: String,
    process: Mutex<Option<Child>>,
    client: reqwest::Client,
    startup_error: Mutex<String>,
    log_path: PathBuf,
}

impl Drop for BridgeState {
    fn drop(&mut self) {
        if let Ok(mut guard) = self.process.lock() {
            if let Some(mut process) = guard.take() {
                let _ = process.kill();
                let _ = process.wait();
            }
        }
    }
}

fn secret() -> String {
    let mut buf = [0_u8; 32];
    rand::rngs::OsRng.fill_bytes(&mut buf);
    buf.iter().map(|b| format!("{b:02x}")).collect()
}

fn discover_root() -> Option<PathBuf> {
    if let Ok(root) = std::env::var("AURIX_ROOT") {
        let path = PathBuf::from(root);
        if path.join("frontend/bridge_server.py").is_file() {
            return Some(path);
        }
    }
    let cwd = std::env::current_dir().ok()?;
    for base in cwd.ancestors() {
        if base.join("frontend/bridge_server.py").is_file() {
            return Some(base.to_path_buf());
        }
    }
    None
}

/// Installer-built onefile sidecar is deployed beside AURIX.exe.
///
/// Do not execute arbitrary files from the working directory. Source mode
/// remains available exclusively from an existing project checkout.
fn worker_log_path() -> PathBuf {
    if let Some(custom) = std::env::var_os("AURIX_DATA_DIR") {
        return PathBuf::from(custom).join("logs").join("worker.log");
    }
    if let Some(local) = std::env::var_os("LOCALAPPDATA") {
        return PathBuf::from(local).join("AURIX").join("logs").join("worker.log");
    }
    std::env::temp_dir().join("AURIX").join("logs").join("worker.log")
}

fn spawn_bundled_worker(token: &str) -> Result<Child, String> {
    let app_dir = std::env::current_exe()
        .map_err(|_| "Cannot determine AURIX installation directory".to_string())?
        .parent().ok_or("Cannot determine AURIX executable directory")?.to_path_buf();
    let candidate = app_dir.join("aurix-worker.exe");
    if !candidate.is_file() {
        return Err("Packaged aurix-worker.exe is missing beside AURIX.exe. Rebuild/reinstall the installer.".into());
    }
    Command::new(candidate)
        .env("AURIX_BRIDGE_TOKEN", token)
        .env("AURIX_BRIDGE_HOST", "127.0.0.1")
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::null())
        .spawn()
        .map_err(|error| format!("Cannot launch the bundled worker ({:?}). Check antivirus quarantine and installation.", error.kind()))
}

fn spawn_bridge(root: &Path, token: &str) -> Result<Child, String> {
    let entry = root.join("frontend/bridge_server.py");
    for python in ["python", "python3"] {
        if let Ok(child) = Command::new(python)
            .arg(&entry)
            .current_dir(root)
            .env("AURIX_BRIDGE_TOKEN", token)
            .env("AURIX_BRIDGE_HOST", "127.0.0.1")
            .stdout(std::process::Stdio::null())
            .stderr(std::process::Stdio::null())
            .spawn()
        {
            return Ok(child);
        }
    }
    Err("Python worker could not launch from source. Install Python 3.10+ and project dependencies.".into())
}

fn launch_worker(token: &str) -> Result<Child, String> {
    let app_dir = std::env::current_exe()
        .map_err(|_| "Cannot resolve AURIX executable".to_string())?
        .parent().ok_or("Cannot resolve AURIX executable directory")?.to_path_buf();
    if app_dir.join("aurix-worker.exe").is_file() {
        return spawn_bundled_worker(token);
    }
    if let Some(root) = discover_root() {
        return spawn_bridge(&root, token);
    }
    spawn_bundled_worker(token)
}

#[derive(Serialize)]
struct WorkerDiagnostics {
    state: &'static str,
    message: String,
    log_path: String,
}

#[tauri::command]
fn get_worker_diagnostics(state: State<'_, BridgeState>) -> WorkerDiagnostics {
    let log_path = state.log_path.to_string_lossy().into_owned();
    let mut guard = match state.process.lock() {
        Ok(lock) => lock,
        Err(_) => return WorkerDiagnostics {
            state: "failed", message: "Worker process state unavailable".into(), log_path,
        },
    };
    if let Some(child) = guard.as_mut() {
        match child.try_wait() {
            Ok(Some(status)) => return WorkerDiagnostics {
                state: "exited",
                message: format!("Python worker exited ({status}). See the worker log or reinstall the app."),
                log_path,
            },
            Ok(None) => return WorkerDiagnostics {
                state: "starting",
                message: "Worker process is running but has not responded yet. If this persists, check worker.log and local port 9721.".into(),
                log_path,
            },
            Err(_) => return WorkerDiagnostics {
                state: "failed",
                message: "Cannot inspect the Python worker process".into(),
                log_path,
            },
        }
    }
    WorkerDiagnostics {
        state: "missing",
        message: state.startup_error.lock().map(|x| x.clone())
            .unwrap_or_else(|_| "Python worker did not start".into()),
        log_path,
    }
}

#[tauri::command]
fn restart_ai_worker(state: State<'_, BridgeState>) -> Result<String, String> {
    let mut guard = state.process.lock().map_err(|_| "Worker process lock unavailable")?;
    if let Some(mut old) = guard.take() {
        let _ = old.kill();
        let _ = old.wait();
    }
    match launch_worker(&state.token) {
        Ok(child) => {
            *guard = Some(child);
            if let Ok(mut message) = state.startup_error.lock() { message.clear(); }
            Ok("Worker restarted. Allow a few seconds for initialization.".into())
        }
        Err(error) => {
            if let Ok(mut message) = state.startup_error.lock() { *message = error.clone(); }
            Err(error)
        }
    }
}

fn check_response(status: reqwest::StatusCode) -> Result<(), String> {
    if status.is_success() { Ok(()) } else { Err(format!("Worker rejected request (HTTP {})", status.as_u16())) }
}

#[derive(Clone, Serialize)]
struct Telemetry { cpu: f32, ram: f32, gpu: Option<f32>, gpu_temp: Option<f32>, vram_mb: Option<f32> }
struct SysState(Mutex<System>);

fn sample_telemetry(state: &SysState) -> Telemetry {
    let mut sys = state.0.lock().expect("telemetry mutex poisoned");
    sys.refresh_cpu_usage();
    sys.refresh_memory();
    let ram = sys.used_memory() as f32 / sys.total_memory().max(1) as f32 * 100.0;
    // NVML reports real device statistics, not invented zeros. Without an
    // NVIDIA-compatible driver these fields remain unavailable.
    let (gpu, gpu_temp, vram_mb) = match Nvml::init() {
        Ok(nvml) => match nvml.device_by_index(0) {
            Ok(device) => (
                device.utilization_rates().ok().map(|v| v.gpu as f32),
                device.temperature(TemperatureSensor::Gpu).ok().map(|v| v as f32),
                device.memory_info().ok().map(|v| v.used as f32 / (1024.0 * 1024.0)),
            ),
            Err(_) => (None, None, None),
        },
        Err(_) => (None, None, None),
    };
    Telemetry { cpu: sys.global_cpu_usage(), ram, gpu, gpu_temp, vram_mb }
}

#[tauri::command]
fn get_telemetry(state: State<'_, SysState>) -> Telemetry {
    sample_telemetry(&state)
}

#[tauri::command]
fn get_telemetry_history(window: String, state: State<'_, TelemetryStore>) -> Result<Vec<MetricPoint>, String> {
    state.history(&window)
}

#[tauri::command]
fn export_telemetry_csv(
    window: String,
    state: State<'_, TelemetryStore>,
    app: tauri::AppHandle,
) -> Result<String, String> {
    let directory = app.path().app_data_dir().map_err(|e| e.to_string())?.join("exports");
    state.export_csv(&window, &directory)
}

#[derive(Deserialize)]
struct DispatchRequest { text: String }
#[derive(Serialize, Deserialize)]
struct DispatchResponse { reply: String, action: bool }
#[derive(Serialize, Deserialize)]
struct BridgeTelemetry { cpu: Option<f64>, ram: Option<f64>, gpu: Option<f64>, gpu_temp: Option<f64> }
#[derive(Deserialize)]
struct TrustRequest { request: String }
#[derive(Deserialize)]
struct TrustPreview { description: Option<String>, error: Option<String> }
#[derive(Serialize, Deserialize)]
struct TrustResponse { result: String }

#[tauri::command]
async fn send_message(payload: DispatchRequest, state: State<'_, BridgeState>) -> Result<DispatchResponse, String> {
    if payload.text.len() > 16000 { return Err("Input is too long".into()); }
    let response = state.client.post(format!("{BRIDGE_URL}/dispatch"))
        .bearer_auth(&state.token).json(&serde_json::json!({"text":payload.text}))
        .send().await.map_err(|_| "Local AI worker is unavailable".to_string())?;
    check_response(response.status())?;
    response.json().await.map_err(|_| "Invalid worker reply".to_string())
}

#[tauri::command]
async fn get_bridge_telemetry(state: State<'_, BridgeState>) -> Result<BridgeTelemetry, String> {
    let response = state.client.get(format!("{BRIDGE_URL}/telemetry"))
        .bearer_auth(&state.token).send().await
        .map_err(|_| "Local AI worker unavailable".to_string())?;
    check_response(response.status())?;
    response.json().await.map_err(|_| "Invalid worker telemetry".to_string())
}

#[tauri::command]
async fn get_bridge_health(state: State<'_, BridgeState>) -> Result<bool, String> {
    let response = state.client.get(format!("{BRIDGE_URL}/health"))
        .bearer_auth(&state.token).send().await
        .map_err(|_| "Local AI worker unavailable".to_string())?;
    Ok(response.status().is_success())
}

#[cfg(windows)]
fn native_approve(description: &str) -> bool {
    use windows_sys::Win32::UI::WindowsAndMessaging::{
        MessageBoxW, IDYES, MB_DEFBUTTON2, MB_ICONWARNING, MB_YESNO
    };
    let title: Vec<u16> = "AURIX — Authorize action\0".encode_utf16().collect();
    let details: Vec<u16> = format!(
        "LUNA requests permission to perform:\n\n{}\n\nApprove this exact action?",
        description
    ).encode_utf16().chain(std::iter::once(0)).collect();
    unsafe { MessageBoxW(0, details.as_ptr(), title.as_ptr(),
        MB_YESNO | MB_ICONWARNING | MB_DEFBUTTON2) == IDYES }
}

#[cfg(not(windows))]
fn native_approve(_description: &str) -> bool { false }

#[tauri::command]
async fn execute_trust(payload: TrustRequest, state: State<'_, BridgeState>) -> Result<TrustResponse, String> {
    let request = payload.request.trim();
    if request.len() != 12 || !request.bytes().all(|b| b.is_ascii_hexdigit()) {
        return Err("Invalid approval identifier".into());
    }
    let response = state.client.post(format!("{BRIDGE_URL}/trust_preview"))
        .bearer_auth(&state.token)
        .json(&serde_json::json!({"request":request}))
        .send().await.map_err(|_| "Local AI worker unavailable".to_string())?;
    check_response(response.status())?;
    let preview: TrustPreview = response.json().await.map_err(|_| "Invalid approval details".to_string())?;
    if preview.error.is_some() { return Err("Action expired or unavailable".into()); }
    let description = preview.description.ok_or("Missing action description")?;
    let authorized = tokio::task::spawn_blocking(move || native_approve(&description))
        .await.map_err(|_| "Approval dialog failed".to_string())?;
    if !authorized {
        let _ = local_post(&state, "/reject_trust", serde_json::json!({"request": request})).await;
        return Ok(TrustResponse { result: "Action rejected by user.".into() });
    }
    let result = state.client.post(format!("{BRIDGE_URL}/execute_trust"))
        .bearer_auth(&state.token).json(&serde_json::json!({"request":request}))
        .send().await.map_err(|_| "Local AI worker unavailable".to_string())?;
    check_response(result.status())?;
    result.json().await.map_err(|_| "Invalid action result".to_string())
}


// Native-only application APIs. All use the confidential session bearer;
// the renderer can never send arbitrary URLs or read the secret.
async fn local_get(state: &BridgeState, route: &str) -> Result<serde_json::Value, String> {
    let res = state.client.get(format!("{BRIDGE_URL}{route}"))
        .bearer_auth(&state.token).send().await
        .map_err(|_| "Private worker unavailable".to_string())?;
    check_response(res.status())?;
    res.json().await.map_err(|_| "Invalid private worker response".to_string())
}

async fn local_post(
    state: &BridgeState,
    route: &str,
    body: serde_json::Value,
) -> Result<serde_json::Value, String> {
    let res = state.client.post(format!("{BRIDGE_URL}{route}"))
        .bearer_auth(&state.token).json(&body).send().await
        .map_err(|_| "Private worker unavailable".to_string())?;
    if !res.status().is_success() {
        let status = res.status();
        let body: serde_json::Value = res.json().await.unwrap_or_default();
        let code = body.get("error").and_then(|x| x.as_str()).unwrap_or("REQUEST_FAILED");
        return Err(format!("{} (HTTP {})", code, status.as_u16()));
    }
    res.json().await.map_err(|_| "Invalid private worker response".to_string())
}

// The renderer cannot choose arbitrary addresses; Ollama is always a local
// installed service. All downloads and installations require a user gesture.
fn valid_ollama_model(name: &str) -> bool {
    !name.is_empty() && name.len() <= 120 && !name.contains("..")
        && !name.contains("://")
        && !name.to_ascii_lowercase().ends_with("-cloud")
        && name.bytes().enumerate().all(|(i, byte)| {
            byte.is_ascii_alphanumeric() || (i > 0 &&
                matches!(byte, b'-' | b'_' | b'.' | b'/' | b':'))
        })
}

async fn require_online(state: &BridgeState) -> Result<(), String> {
    let settings = local_get(state, "/settings").await?;
    if settings.get("offline").and_then(|x| x.as_bool()).unwrap_or(true) {
        Err("Offline mode is enabled. Turn it off in System settings to download.".into())
    } else {
        Ok(())
    }
}

#[tauri::command]
async fn list_model_choices(state: State<'_, BridgeState>) -> Result<serde_json::Value, String> {
    local_get(&state, "/models").await
}

#[tauri::command]
async fn activate_model(
    backend: String, model: String, state: State<'_, BridgeState>
) -> Result<serde_json::Value, String> {
    if !matches!(backend.as_str(), "ollama" | "llama_cpp") || !valid_ollama_model(&model) {
        return Err("Invalid backend or model tag".into());
    }
    local_post(&state, "/models/activate", serde_json::json!({
        "backend": backend, "model": model
    })).await
}

#[tauri::command]
async fn install_ollama(state: State<'_, BridgeState>) -> Result<String, String> {
    require_online(&state).await?;
    let accepted = tokio::task::spawn_blocking(|| native_approve(
        "Install Ollama using the official winget package Ollama.Ollama?\nThis downloads software from the internet."
    )).await.map_err(|_| "Installer approval failed".to_string())?;
    if !accepted { return Err("Installation cancelled by user".into()); }

    #[cfg(target_os = "windows")]
    {
        let mut command = tokio::process::Command::new("winget");
        command.args([
            "install", "--id", "Ollama.Ollama", "--exact", "--source", "winget",
            "--silent", "--accept-package-agreements", "--accept-source-agreements",
            "--disable-interactivity",
        ]).kill_on_drop(true)
          .stdout(std::process::Stdio::null())
          .stderr(std::process::Stdio::null());
        let status = tokio::time::timeout(
            Duration::from_secs(1800), command.status()
        ).await.map_err(|_| "Ollama installation timed out".to_string())?
            .map_err(|_| "winget unavailable. Install Ollama from https://ollama.com/download/windows".to_string())?;
        if !status.success() {
            return Err(format!(
                "winget install failed (exit {:?}). Check Windows App Installer or https://ollama.com/download/windows",
                status.code()
            ));
        }
        return Ok("Ollama installed. Launch Ollama if its local service is not yet running.".into());
    }
    #[cfg(not(target_os = "windows"))]
    Err("In-app Ollama installation is supported on Windows only".into())
}

#[tauri::command]
async fn pull_ollama_model(
    model: String, app: tauri::AppHandle, state: State<'_, BridgeState>
) -> Result<String, String> {
    if !valid_ollama_model(&model) { return Err("Invalid Ollama model tag".into()); }
    require_online(&state).await?;
    let description = format!(
        "Download Ollama model {} from the registry?\nThis may use several GB of disk space and internet data.",
        model
    );
    let accepted = tokio::task::spawn_blocking(move || native_approve(&description))
        .await.map_err(|_| "Download confirmation failed".to_string())?;
    if !accepted { return Err("Download cancelled by user".into()); }

    use futures_util::StreamExt;
    let client = reqwest::Client::builder().timeout(Duration::from_secs(3600))
        .build().map_err(|_| "Ollama client unavailable".to_string())?;
    let response = client.post("http://127.0.0.1:11434/api/pull")
        .json(&serde_json::json!({"model": model, "stream": true}))
        .send().await.map_err(|_| "Ollama is not running. Open Ollama and retry.".to_string())?;
    check_response(response.status())?;
    let mut body = response.bytes_stream();
    let mut buffer = Vec::<u8>::new();
    while let Some(piece) = body.next().await {
        let bytes = piece.map_err(|_| "Model download interrupted".to_string())?;
        if buffer.len() + bytes.len() > 128 * 1024 {
            return Err("Unexpectedly large Ollama progress response".into());
        }
        buffer.extend_from_slice(&bytes);
        while let Some(end) = buffer.iter().position(|byte| *byte == b'\n') {
            let line: Vec<u8> = buffer.drain(..=end).collect();
            if let Ok(data) = serde_json::from_slice::<serde_json::Value>(&line) {
                if let Some(error) = data.get("error").and_then(|x| x.as_str()) {
                    return Err(format!("Ollama rejected model download: {}", error.chars().take(250).collect::<String>()));
                }
                let _ = app.emit("aurix://ollama-progress", &serde_json::json!({
                    "model": model,
                    "status": data.get("status").and_then(|x| x.as_str()).unwrap_or("Downloading"),
                    "total": data.get("total").and_then(|x| x.as_u64()),
                    "completed": data.get("completed").and_then(|x| x.as_u64()),
                }));
            }
        }
    }
    Ok(format!("Model {} downloaded and ready to activate.", model))
}

#[tauri::command]
async fn remove_ollama_model(
    model: String, state: State<'_, BridgeState>
) -> Result<String, String> {
    if !valid_ollama_model(&model) { return Err("Invalid model tag".into()); }
    let display = format!("Permanently delete downloaded Ollama model {}?", model);
    let approved = tokio::task::spawn_blocking(move || native_approve(&display))
        .await.map_err(|_| "Deletion approval unavailable".to_string())?;
    if !approved { return Err("Deletion cancelled".into()); }
    let chosen = local_get(&state, "/models").await?;
    if chosen.get("selected").and_then(|x| x.as_str()) == Some(model.as_str())
       && chosen.get("backend").and_then(|x| x.as_str()) == Some("ollama") {
        return Err("Switch to another model before deleting the active model".into());
    }
    let response = reqwest::Client::new()
        .delete("http://127.0.0.1:11434/api/delete")
        .json(&serde_json::json!({"model": model}))
        .timeout(Duration::from_secs(30))
        .send().await.map_err(|_| "Ollama is unavailable".to_string())?;
    check_response(response.status())?;
    Ok(format!("Deleted {}", model))
}

#[tauri::command]
async fn email_configuration(state: State<'_, BridgeState>) -> Result<serde_json::Value, String> {
    local_get(&state, "/email/configure").await
}

#[tauri::command]
async fn save_email_configuration(
    address: String, password: String, state: State<'_, BridgeState>
) -> Result<serde_json::Value, String> {
    if address.len() > 254 || password.len() > 256 || address.len() < 3 || password.len() < 8 {
        return Err("Invalid email credentials".into());
    }
    // Never log, cache in JavaScript state beyond submission, or return password.
    local_post(&state, "/email/configure", serde_json::json!({
        "action": "save", "address": address, "password": password
    })).await
}

#[tauri::command]
async fn remove_email_configuration(state: State<'_, BridgeState>) -> Result<serde_json::Value, String> {
    local_post(&state, "/email/configure", serde_json::json!({"action": "remove"})).await
}

#[tauri::command]
async fn get_ui_settings(state: State<'_, BridgeState>) -> Result<serde_json::Value, String> {
    local_get(&state, "/settings").await
}

#[tauri::command]
async fn set_offline_mode(enabled: bool, state: State<'_, BridgeState>) -> Result<serde_json::Value, String> {
    local_post(&state, "/settings", serde_json::json!({"offline": enabled})).await
}

#[tauri::command]
async fn set_memory_enabled(enabled: bool, state: State<'_, BridgeState>) -> Result<serde_json::Value, String> {
    local_post(&state, "/settings", serde_json::json!({"memory_enabled": enabled})).await
}

#[tauri::command]
async fn list_memories(state: State<'_, BridgeState>) -> Result<serde_json::Value, String> {
    local_get(&state, "/memory").await
}

#[tauri::command]
async fn add_memory(kind: String, content: String, state: State<'_, BridgeState>) -> Result<serde_json::Value, String> {
    if content.len() > 12000 { return Err("Memory text too long".into()); }
    local_post(&state, "/memory", serde_json::json!({"action":"add","kind":kind,"content":content})).await
}

#[tauri::command]
async fn delete_memory(id: String, state: State<'_, BridgeState>) -> Result<serde_json::Value, String> {
    local_post(&state, "/memory", serde_json::json!({"action":"delete","id":id})).await
}

#[tauri::command]
async fn get_wake_status(state: State<'_, BridgeState>) -> Result<serde_json::Value, String> {
    local_get(&state, "/voice/wake").await
}

#[tauri::command]
async fn set_wake_enabled(enabled: bool, state: State<'_, BridgeState>) -> Result<serde_json::Value, String> {
    local_post(&state, "/voice/wake", serde_json::json!({"enabled": enabled})).await
}

#[tauri::command]
async fn listen_voice(state: State<'_, BridgeState>) -> Result<serde_json::Value, String> {
    local_post(&state, "/voice/transcribe", serde_json::json!({})).await
}

#[tauri::command]
async fn list_activity(state: State<'_, BridgeState>) -> Result<serde_json::Value, String> {
    local_get(&state, "/audit").await
}

#[tauri::command]
async fn reject_trust(payload: TrustRequest, state: State<'_, BridgeState>) -> Result<serde_json::Value, String> {
    local_post(&state, "/reject_trust", serde_json::json!({"request": payload.request})).await
}

#[tauri::command]
async fn speak_text(text: String, state: State<'_, BridgeState>) -> Result<serde_json::Value, String> {
    if text.is_empty() || text.chars().count() > 800 {
        return Err("Speech must have 1–800 characters".to_string());
    }
    local_post(&state, "/voice/speak", serde_json::json!({"text": text})).await
}

#[tauri::command]
async fn stop_speech(state: State<'_, BridgeState>) -> Result<serde_json::Value, String> {
    local_post(&state, "/voice/stop", serde_json::json!({})).await
}

#[tauri::command]
async fn kill_actions(state: State<'_, BridgeState>) -> Result<serde_json::Value, String> {
    local_post(&state, "/kill", serde_json::json!({})).await
}

#[tauri::command]
async fn resume_actions(state: State<'_, BridgeState>) -> Result<serde_json::Value, String> {
    local_post(&state, "/resume", serde_json::json!({})).await
}

fn main() {
    let token = secret();
    let worker_start = launch_worker(&token);
    let (child, startup_error) = match worker_start {
        Ok(child) => (Some(child), String::new()),
        Err(error) => (None, error),
    };
    let client = reqwest::Client::builder().timeout(Duration::from_secs(120))
        .build().expect("Unable to create local HTTP client");
    tauri::Builder::default()
        .manage(SysState(Mutex::new(System::new_all())))
        .setup(|app| {
            let directory = app.path().app_data_dir()?;
            let store = TelemetryStore::open(&directory).map_err(std::io::Error::other)?;
            app.manage(store);
            let handle = app.handle().clone();
            std::thread::spawn(move || loop {
                let snapshot = sample_telemetry(&handle.state::<SysState>());
                if let Ok(duration) = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH) {
                    let point = MetricPoint {
                        timestamp: duration.as_secs() as i64,
                        cpu: Some(snapshot.cpu as f64),
                        ram: Some(snapshot.ram as f64),
                        gpu: snapshot.gpu.map(|x| x as f64),
                        gpu_temp: snapshot.gpu_temp.map(|x| x as f64),
                        vram_mb: snapshot.vram_mb.map(|x| x as f64),
                    };
                    if let Err(err) = handle.state::<TelemetryStore>().record(&point) {
                        eprintln!("Telemetry store unavailable: {err}");
                    }
                }
                let _ = handle.emit("aurix://telemetry", &snapshot);
                std::thread::sleep(Duration::from_secs(3));
            });
            Ok(())
        })
        .manage(BridgeState {
            token, process: Mutex::new(child), client,
            startup_error: Mutex::new(startup_error),
            log_path: worker_log_path(),
        })
        .invoke_handler(tauri::generate_handler![
            get_telemetry, get_bridge_telemetry, get_bridge_health, get_worker_diagnostics,
            restart_ai_worker, send_message, execute_trust,
            get_ui_settings, set_offline_mode, set_memory_enabled,
            email_configuration, save_email_configuration, remove_email_configuration, list_memories, add_memory, delete_memory,
            listen_voice, get_wake_status, set_wake_enabled, speak_text, stop_speech,
            kill_actions, resume_actions, list_activity, reject_trust,
            get_telemetry_history, export_telemetry_csv,
            list_model_choices, activate_model, install_ollama, pull_ollama_model, remove_ollama_model
        ])
        .run(tauri::generate_context!())
        .expect("error while running AURIX");
}

#[cfg(test)]
mod model_setup_tests {
    use super::valid_ollama_model;
    #[test]
    fn only_local_model_tags_are_accepted() {
        assert!(valid_ollama_model("qwen3:4b"));
        assert!(valid_ollama_model("gpt-oss:20b"));
        assert!(!valid_ollama_model("gpt-oss:20b-cloud"));
        assert!(!valid_ollama_model("http://example.com/llm"));
        assert!(!valid_ollama_model("../../cmd"));
    }
}
