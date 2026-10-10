#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]
use rand::RngCore;
use serde::{Deserialize, Serialize};
use std::path::{Path, PathBuf};
use std::process::{Child, Command};
use std::sync::Mutex;
use std::time::Duration;
use sysinfo::System;
use tauri::State;

const BRIDGE_URL: &str = "http://127.0.0.1:9721";

struct BridgeState {
    token: String,
    process: Mutex<Option<Child>>,
    client: reqwest::Client,
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

fn spawn_bridge(root: &Path, token: &str) -> Option<Child> {
    let entry = root.join("frontend/bridge_server.py");
    for python in ["python", "python3"] {
        let result = Command::new(python)
            .arg(&entry)
            .current_dir(root)
            .env("AURIX_BRIDGE_TOKEN", token)
            .env("AURIX_BRIDGE_HOST", "127.0.0.1")
            .spawn();
        if let Ok(child) = result {
            return Some(child);
        }
    }
    eprintln!("AURIX worker could not start: Python 3.10+ is required.");
    None
}

fn check_response(status: reqwest::StatusCode) -> Result<(), String> {
    if status.is_success() { Ok(()) } else { Err(format!("Worker rejected request (HTTP {})", status.as_u16())) }
}

#[derive(Serialize)]
struct Telemetry { cpu: f32, ram: f32, gpu: Option<f32>, gpu_temp: Option<f32> }
struct SysState(Mutex<System>);

#[tauri::command]
fn get_telemetry(state: State<'_, SysState>) -> Telemetry {
    let mut sys = state.0.lock().expect("telemetry mutex poisoned");
    sys.refresh_cpu_usage();
    sys.refresh_memory();
    let ram = sys.used_memory() as f32 / sys.total_memory().max(1) as f32 * 100.0;
    Telemetry { cpu: sys.global_cpu_usage(), ram, gpu: None, gpu_temp: None }
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
#[derive(Serialize)]
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
    if !authorized { return Ok(TrustResponse { result: "Action rejected by user.".into() }); }
    let result = state.client.post(format!("{BRIDGE_URL}/execute_trust"))
        .bearer_auth(&state.token).json(&serde_json::json!({"request":request}))
        .send().await.map_err(|_| "Local AI worker unavailable".to_string())?;
    check_response(result.status())?;
    result.json().await.map_err(|_| "Invalid action result".to_string())
}

fn main() {
    let token = secret();
    let child = discover_root().and_then(|root| spawn_bridge(&root, &token));
    let client = reqwest::Client::builder().timeout(Duration::from_secs(120))
        .build().expect("Unable to create local HTTP client");
    tauri::Builder::default()
        .manage(SysState(Mutex::new(System::new_all())))
        .manage(BridgeState { token, process: Mutex::new(child), client })
        .invoke_handler(tauri::generate_handler![
            get_telemetry, get_bridge_telemetry, get_bridge_health, send_message, execute_trust
        ])
        .run(tauri::generate_context!())
        .expect("error while running AURIX");
}
