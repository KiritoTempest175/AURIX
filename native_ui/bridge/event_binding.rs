// ─────────────────────────────────────────────────────────────────────────────
// AURIX Desktop AI Agent — Native Bridge: Slint → Rust Event Dispatcher
// ─────────────────────────────────────────────────────────────────────────────
// Strongly-typed event dispatching layer between Slint UI components and
// the Rust backend (Security Sandbox, Governor, Whisper STT, Piper TTS).
//
// Invariant:
// Zero business logic in Slint. Slint emits UI events; Rust backend decides
// execution, validation, self-healing, and audio processing.
// ─────────────────────────────────────────────────────────────────────────────

use std::collections::HashMap;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc::{self, Sender};
use std::sync::{Arc, Mutex, RwLock};
use std::thread::{self, JoinHandle};
use std::time::Duration;

use crate::config::AurixConfig;
use crate::whisper_stt::WhisperEngine;
use crate::piper_tts::PiperEngine;

// ─── Strongly-Typed Event Definitions ───────────────────────────────────────

/// Parameter key-value pairs associated with automation tasks.
pub type TaskParameters = HashMap<String, String>;

/// Events emitted from Review Card UI components.
#[derive(Debug, Clone, PartialEq)]
pub enum ReviewEvent {
    Approved {
        action_title: String,
        category: String,
        command: String,
        project_path: String,
        parameters: TaskParameters,
    },
    EditRequested {
        action_title: String,
        command: String,
        parameters: TaskParameters,
    },
    Rejected {
        action_title: String,
        reason: String,
    },
    CommandCopied {
        command: String,
    },
}

/// Events emitted from Alert Modal error & self-healing components.
#[derive(Debug, Clone, PartialEq)]
pub enum AlertEvent {
    RetryRequested {
        error_title: String,
        failed_command: String,
    },
    Dismissed {
        error_title: String,
    },
    SelfHealTriggered {
        error_title: String,
        suggested_fix: String,
        exit_code: i32,
    },
    AutoHealToggled {
        active: bool,
    },
    ErrorLogCopied {
        error_message: String,
    },
}

/// Events emitted from Voice Core and Microphone controls.
#[derive(Debug, Clone, PartialEq)]
pub enum VoiceEvent {
    StartListening,
    StopListening,
    TranscriptionReceived(String),
    SpeakRequested(String),
    SpeechStarted(String),
    SpeechCompleted(String),
    AudioLevel(f32),
}

/// System, hardware, and configuration events.
#[derive(Debug, Clone, PartialEq)]
pub enum SystemEvent {
    HardwareCeilingExceeded {
        metric: String,
        current_value: f64,
        threshold: f64,
    },
    ConfigReloaded,
    ToastMessage(String),
    ChatMessageSubmitted(String),
}

/// Master enumeration representing all events crossing the Slint ↔ Rust boundary.
#[derive(Debug, Clone, PartialEq)]
pub enum AurixEvent {
    Review(ReviewEvent),
    Alert(AlertEvent),
    Voice(VoiceEvent),
    System(SystemEvent),
}

// ─── Event Listener Trait ───────────────────────────────────────────────────

/// Interface for backend systems to listen to asynchronously dispatched events.
pub trait AurixEventListener: Send + Sync {
    fn on_event(&self, event: &AurixEvent);
}

// ─── Central Event Dispatcher & Bus ─────────────────────────────────────────

/// Thread-safe event bus for broadcasting UI callbacks to AURIX backend systems.
pub struct AurixEventDispatcher {
    listeners: Arc<RwLock<Vec<Box<dyn AurixEventListener>>>>,
    event_tx: Sender<AurixEvent>,
    worker_handle: Option<JoinHandle<()>>,
    is_running: Arc<AtomicBool>,
}

impl AurixEventDispatcher {
    /// Creates a new background event dispatcher worker.
    pub fn new() -> Self {
        let (event_tx, event_rx) = mpsc::channel::<AurixEvent>();
        let listeners: Arc<RwLock<Vec<Box<dyn AurixEventListener>>>> = Arc::new(RwLock::new(Vec::new()));
        let is_running = Arc::new(AtomicBool::new(true));

        let worker_listeners = Arc::clone(&listeners);
        let worker_running = Arc::clone(&is_running);

        let worker_handle = thread::spawn(move || {
            while worker_running.load(Ordering::SeqCst) {
                match event_rx.recv_timeout(Duration::from_millis(100)) {
                    Ok(event) => {
                        if let Ok(listeners_guard) = worker_listeners.read() {
                            for listener in listeners_guard.iter() {
                                listener.on_event(&event);
                            }
                        }
                    }
                    Err(mpsc::RecvTimeoutError::Timeout) => continue,
                    Err(mpsc::RecvTimeoutError::Disconnected) => break,
                }
            }
        });

        Self {
            listeners,
            event_tx,
            worker_handle: Some(worker_handle),
            is_running,
        }
    }

    /// Registers a custom backend event listener.
    pub fn register_listener<L: AurixEventListener + 'static>(&self, listener: L) {
        if let Ok(mut guard) = self.listeners.write() {
            guard.push(Box::new(listener));
        }
    }

    /// Dispatches an event non-blockingly from UI or worker threads.
    pub fn dispatch(&self, event: AurixEvent) {
        let _ = self.event_tx.send(event);
    }

    /// Shuts down the background dispatcher worker safely.
    pub fn shutdown(&mut self) {
        self.is_running.store(false, Ordering::SeqCst);
        if let Some(handle) = self.worker_handle.take() {
            let _ = handle.join();
        }
    }
}

impl Default for AurixEventDispatcher {
    fn default() -> Self {
        Self::new()
    }
}

impl Drop for AurixEventDispatcher {
    fn drop(&mut self) {
        self.shutdown();
    }
}

// ─── Central AURIX Application Bridge ───────────────────────────────────────

/// Integrated controller binding Slint UI, Configuration, Security, and Audio.
pub struct AurixAppBridge {
    pub config: Arc<RwLock<AurixConfig>>,
    pub dispatcher: Arc<AurixEventDispatcher>,
    pub stt_engine: Arc<Mutex<WhisperEngine>>,
    pub tts_engine: Arc<Mutex<PiperEngine>>,
}

impl AurixAppBridge {
    /// Initializes the full application bridge with loaded configuration and audio engines.
    pub fn initialize() -> Result<Self, Box<dyn std::error::Error + Send + Sync>> {
        let config = AurixConfig::load_or_default();
        let dispatcher = Arc::new(AurixEventDispatcher::new());

        // Initialize Whisper STT with configuration
        let stt_cfg = crate::whisper_stt::WhisperConfig {
            model_path: config.audio.whisper_model_path.clone(),
            language: config.audio.whisper_language.clone(),
            threads: config.audio.whisper_threads,
            sample_rate: config.audio.whisper_sample_rate,
            ..Default::default()
        };
        let stt_engine = Arc::new(Mutex::new(WhisperEngine::new(stt_cfg)?));

        // Initialize Piper TTS with configuration
        let tts_cfg = crate::piper_tts::PiperConfig {
            model_path: config.audio.piper_model_path.clone(),
            config_path: config.audio.piper_config_path.clone(),
            speed: config.audio.piper_speed,
            sample_rate: 22050,
            ..Default::default()
        };
        let tts_engine = Arc::new(Mutex::new(PiperEngine::new(tts_cfg)?));

        let bridge = Self {
            config: Arc::new(RwLock::new(config)),
            dispatcher,
            stt_engine,
            tts_engine,
        };

        // Attach default backend audit and action handlers
        bridge.setup_backend_handlers();

        Ok(bridge)
    }

    /// Configures default backend handlers for Review, Alert, Voice, and Sandbox actions.
    fn setup_backend_handlers(&self) {
        let config_clone = Arc::clone(&self.config);
        let tts_clone = Arc::clone(&self.tts_engine);

        struct DefaultBackendHandler {
            config: Arc<RwLock<AurixConfig>>,
            tts: Arc<Mutex<PiperEngine>>,
        }

        impl AurixEventListener for DefaultBackendHandler {
            fn on_event(&self, event: &AurixEvent) {
                match event {
                    AurixEvent::Review(ReviewEvent::Approved { action_title, command, project_path, .. }) => {
                        println!("[A.U.R.I.X Backend]: Review Approved: '{}'", action_title);
                        println!("                      Command: '{}'", command);
                        println!("                      Path: '{}'", project_path);

                        // Enforce security file jail check on target project path
                        if let Ok(cfg) = self.config.read() {
                            let path_obj = std::path::Path::new(project_path);
                            match cfg.security.is_path_allowed(path_obj) {
                                Ok(true) => {
                                    println!("[Security Sandbox]: Path '{}' verified within security whitelist.", project_path);
                                    // Backend execution would proceed here safely
                                }
                                _ => {
                                    eprintln!("[Security Alert]: Path '{}' failed whitelist verification. Execution halted.", project_path);
                                }
                            }
                        }
                    }

                    AurixEvent::Review(ReviewEvent::Rejected { action_title, reason }) => {
                        println!("[A.U.R.I.X Backend]: Review Rejected: '{}' (Reason: '{}')", action_title, reason);
                    }

                    AurixEvent::Review(ReviewEvent::EditRequested { action_title, .. }) => {
                        println!("[A.U.R.I.X Backend]: Review Edit Mode Requested: '{}'", action_title);
                    }

                    AurixEvent::Alert(AlertEvent::RetryRequested { error_title, failed_command }) => {
                        println!("[A.U.R.I.X Self-Healing]: Manual Retry Triggered for '{}' (cmd: '{}')", error_title, failed_command);
                    }

                    AurixEvent::Alert(AlertEvent::SelfHealTriggered { error_title, suggested_fix, exit_code }) => {
                        println!("[A.U.R.I.X Self-Healing]: Auto-Healing Protocol Triggered (exit code: {}): '{}'", exit_code, error_title);
                        println!("                            Executing repair: '{}'", suggested_fix);
                    }

                    AurixEvent::Alert(AlertEvent::Dismissed { error_title }) => {
                        println!("[A.U.R.I.X Backend]: Alert Dismissed by User: '{}'", error_title);
                    }

                    AurixEvent::Voice(VoiceEvent::TranscriptionReceived(text)) => {
                        println!("[A.U.R.I.X Voice STT]: Transcribed voice command: '{}'", text);
                    }

                    AurixEvent::Voice(VoiceEvent::SpeakRequested(text)) => {
                        if let Ok(cfg) = self.config.read() {
                            if cfg.audio.auto_tts_reply {
                                if let Ok(tts) = self.tts.lock() {
                                    let _ = tts.speak(text);
                                }
                            }
                        }
                    }

                    AurixEvent::System(SystemEvent::ChatMessageSubmitted(msg)) => {
                        println!("[A.U.R.I.X Console]: User Command Submitted: '{}'", msg);
                    }

                    _ => {}
                }
            }
        }

        self.dispatcher.register_listener(DefaultBackendHandler {
            config: config_clone,
            tts: tts_clone,
        });
    }

    // ─── Convenience Dispatch Helper Methods ────────────────────────────────

    pub fn handle_review_approve(&self, title: String, category: String, cmd: String, path: String, params: TaskParameters) {
        self.dispatcher.dispatch(AurixEvent::Review(ReviewEvent::Approved {
            action_title: title,
            category,
            command: cmd,
            project_path: path,
            parameters: params,
        }));
    }

    pub fn handle_review_reject(&self, title: String, reason: String) {
        self.dispatcher.dispatch(AurixEvent::Review(ReviewEvent::Rejected {
            action_title: title,
            reason,
        }));
    }

    pub fn handle_review_edit(&self, title: String, cmd: String, params: TaskParameters) {
        self.dispatcher.dispatch(AurixEvent::Review(ReviewEvent::EditRequested {
            action_title: title,
            command: cmd,
            parameters: params,
        }));
    }

    pub fn handle_alert_retry(&self, error_title: String, failed_command: String) {
        self.dispatcher.dispatch(AurixEvent::Alert(AlertEvent::RetryRequested {
            error_title,
            failed_command,
        }));
    }

    pub fn handle_alert_dismiss(&self, error_title: String) {
        self.dispatcher.dispatch(AurixEvent::Alert(AlertEvent::Dismissed {
            error_title,
        }));
    }

    pub fn handle_alert_self_heal(&self, error_title: String, fix: String, exit_code: i32) {
        self.dispatcher.dispatch(AurixEvent::Alert(AlertEvent::SelfHealTriggered {
            error_title,
            suggested_fix: fix,
            exit_code,
        }));
    }

    pub fn handle_voice_toggle(&self) -> Result<bool, String> {
        let stt = self.stt_engine.lock().map_err(|e| e.to_string())?;
        if stt.is_recording() {
            let result = stt.stop_listening().map_err(|e| e.to_string())?;
            self.dispatcher.dispatch(AurixEvent::Voice(VoiceEvent::StopListening));
            self.dispatcher.dispatch(AurixEvent::Voice(VoiceEvent::TranscriptionReceived(result)));
            Ok(false)
        } else {
            stt.start_listening().map_err(|e| e.to_string())?;
            self.dispatcher.dispatch(AurixEvent::Voice(VoiceEvent::StartListening));
            Ok(true)
        }
    }

    pub fn handle_speak(&self, text: &str) {
        self.dispatcher.dispatch(AurixEvent::Voice(VoiceEvent::SpeakRequested(text.to_string())));
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    struct TestListener {
        received_events: Arc<Mutex<Vec<AurixEvent>>>,
    }

    impl AurixEventListener for TestListener {
        fn on_event(&self, event: &AurixEvent) {
            if let Ok(mut list) = self.received_events.lock() {
                list.push(event.clone());
            }
        }
    }

    #[test]
    fn test_event_dispatcher_broadcast() {
        let mut dispatcher = AurixEventDispatcher::new();
        let received = Arc::new(Mutex::new(Vec::new()));

        dispatcher.register_listener(TestListener {
            received_events: Arc::clone(&received),
        });

        let test_review_event = AurixEvent::Review(ReviewEvent::Approved {
            action_title: "Build Production Binary".to_string(),
            category: "BUILD".to_string(),
            command: "cargo build --release".to_string(),
            project_path: "G:/AURIX".to_string(),
            parameters: HashMap::new(),
        });

        dispatcher.dispatch(test_review_event.clone());
        thread::sleep(Duration::from_millis(150));

        let events = received.lock().unwrap();
        assert_eq!(events.len(), 1);
        assert_eq!(events[0], test_review_event);

        dispatcher.shutdown();
    }

    #[test]
    fn test_app_bridge_initialization_and_flow() {
        let bridge = AurixAppBridge::initialize().expect("Bridge should initialize cleanly");
        
        // Test Review Dispatch
        bridge.handle_review_approve(
            "Test Deploy".into(),
            "DEPLOY".into(),
            "npm start".into(),
            ".".into(),
            HashMap::new(),
        );

        // Test Alert Dispatch
        bridge.handle_alert_retry("Link Error".into(), "link.exe".into());
        bridge.handle_alert_self_heal("Build Fail".into(), "cargo clean".into(), 101);

        // Test Voice Dispatch
        bridge.handle_speak("Test speech output.");

        thread::sleep(Duration::from_millis(100));
    }
}
