// Prevents additional console window on Windows in release
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use serde::{Deserialize, Serialize};
use std::process::{Child, Command};
use std::sync::Mutex;
use sysinfo::System;
use tauri::State;

// ---------------------------------------------------------------------------
// Telemetry (native, via sysinfo)
// ---------------------------------------------------------------------------
#[derive(Serialize)]
struct Telemetry {
    cpu: f32,
    ram: f32,
    gpu: f32,
    gpu_temp: f32,
}

struct SysState(Mutex<System>);

#[tauri::command]
fn get_telemetry(state: State<SysState>) -> Telemetry {
    let mut sys = state.0.lock().unwrap();
    sys.refresh_cpu_usage();
    sys.refresh_memory();

    let cpu = sys.global_cpu_usage();
    let ram = (sys.used_memory() as f32 / sys.total_memory().max(1) as f32) * 100.0;

    // GPU usage/temp isn't exposed by sysinfo. For NVIDIA hardware (e.g. RTX 4060),
    // wire in the `nvml-wrapper` crate here and read utilization + temperature
    // from the driver. Placeholder values keep the UI functional without it.
    let gpu = 0.0;
    let gpu_temp = 0.0;

    Telemetry { cpu, ram, gpu, gpu_temp }
}

// ---------------------------------------------------------------------------
// Python Bridge Server management
// ---------------------------------------------------------------------------
struct BridgeProcess(Mutex<Option<Child>>);

const BRIDGE_URL: &str = "http://127.0.0.1:9721";

/// Spawn the Python bridge_server.py that connects the React UI to the
/// AURIX AI brain (dispatcher, tool executor, etc.).
fn spawn_bridge(project_root: &str) -> Option<Child> {
    let bridge_path = format!("{}/frontend/bridge_server.py", project_root);

    // Try python, then python3
    let child = Command::new("python")
        .arg(&bridge_path)
        .current_dir(project_root)
        .spawn()
        .or_else(|_| {
            Command::new("python3")
                .arg(&bridge_path)
                .current_dir(project_root)
                .spawn()
        });

    match child {
        Ok(c) => {
            eprintln!("[tauri] Bridge server spawned (PID {})", c.id());
            Some(c)
        }
        Err(e) => {
            eprintln!("[tauri] Failed to spawn bridge server: {e}");
            None
        }
    }
}

// ---------------------------------------------------------------------------
// Tauri commands that proxy to the Python bridge
// ---------------------------------------------------------------------------
#[derive(Deserialize)]
struct DispatchRequest {
    text: String,
}

#[derive(Serialize, Deserialize)]
struct DispatchResponse {
    reply: String,
    action: bool,
}

#[tauri::command]
async fn send_message(payload: DispatchRequest) -> Result<DispatchResponse, String> {
    let client = reqwest::Client::new();
    let resp = client
        .post(format!("{BRIDGE_URL}/dispatch"))
        .json(&serde_json::json!({"text": payload.text}))
        .send()
        .await
        .map_err(|e| format!("Bridge request failed: {e}"))?;

    let data: DispatchResponse = resp
        .json()
        .await
        .map_err(|e| format!("Bridge response parse error: {e}"))?;

    Ok(data)
}

#[derive(Serialize, Deserialize)]
struct BridgeTelemetry {
    cpu: f64,
    ram: f64,
    gpu: f64,
    gpu_temp: f64,
}

#[tauri::command]
async fn get_bridge_telemetry() -> Result<BridgeTelemetry, String> {
    let client = reqwest::Client::new();
    let resp = client
        .get(format!("{BRIDGE_URL}/telemetry"))
        .send()
        .await
        .map_err(|e| format!("Bridge telemetry failed: {e}"))?;

    let data: BridgeTelemetry = resp
        .json()
        .await
        .map_err(|e| format!("Bridge telemetry parse error: {e}"))?;

    Ok(data)
}

#[derive(Deserialize)]
struct TrustRequest {
    request: String,
}

#[derive(Serialize, Deserialize)]
struct TrustResponse {
    result: String,
}

#[tauri::command]
async fn execute_trust(payload: TrustRequest) -> Result<TrustResponse, String> {
    let client = reqwest::Client::new();
    let resp = client
        .post(format!("{BRIDGE_URL}/execute_trust"))
        .json(&serde_json::json!({"request": payload.request}))
        .send()
        .await
        .map_err(|e| format!("Bridge trust request failed: {e}"))?;

    let data: TrustResponse = resp
        .json()
        .await
        .map_err(|e| format!("Bridge trust parse error: {e}"))?;

    Ok(data)
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------
fn main() {
    // Resolve the AURIX project root (two levels up from src-tauri/)
    let project_root = std::env::current_dir()
        .ok()
        .and_then(|p| p.parent().map(|pp| pp.parent().map(|ppp| ppp.to_path_buf())))
        .flatten()
        .unwrap_or_else(|| {
            // Fallback: use AURIX_ROOT env var or default
            std::path::PathBuf::from(
                std::env::var("AURIX_ROOT").unwrap_or_else(|_| "e:/AURIX".to_string()),
            )
        });

    let root_str = project_root.to_string_lossy().to_string();

    // Spawn the Python bridge server
    let bridge = spawn_bridge(&root_str);

    tauri::Builder::default()
        .manage(SysState(Mutex::new(System::new_all())))
        .manage(BridgeProcess(Mutex::new(bridge)))
        .invoke_handler(tauri::generate_handler![
            get_telemetry,
            send_message,
            get_bridge_telemetry,
            execute_trust,
        ])
        .run(tauri::generate_context!())
        .expect("error while running AURIX");
}
