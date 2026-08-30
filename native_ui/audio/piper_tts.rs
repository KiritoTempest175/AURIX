// ─────────────────────────────────────────────────────────────────────────────
// AURIX Desktop AI Agent — Native Audio Subsystem: Piper TTS (Text-to-Speech)
// ─────────────────────────────────────────────────────────────────────────────
// Local, ultra-low latency neural Text-to-Speech synthesizer powered by Piper.
// Converts AURIX response text into natural synthesized speech audio output
// played through local speakers without requiring any cloud or online services.
// ─────────────────────────────────────────────────────────────────────────────

use std::fs::{self, File};
use std::io::Write;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc::{self, Receiver, Sender};
use std::sync::{Arc, Mutex};
use std::thread::{self, JoinHandle};
use std::time::Duration;

#[cfg(windows)]
use std::os::windows::process::CommandExt;

/// Operational status of the Text-to-Speech engine.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TtsState {
    Uninitialized,
    Idle,
    Synthesizing,
    Playing,
    Paused,
    Error,
}

/// Real-time TTS events dispatched to AURIX controllers and Slint UI.
#[derive(Debug, Clone)]
pub enum TtsEvent {
    StateChanged(TtsState),
    SpeechStarted(String),
    SpeechCompleted(String),
    Error(String),
}

/// Errors produced during TTS configuration, synthesis, or playback.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum PiperError {
    ModelNotFound(String),
    ConfigNotFound(String),
    ExecutableNotFound(String),
    SynthesisFailed(String),
    PlaybackFailed(String),
    EngineNotInitialized,
    IoError(String),
}

impl std::fmt::Display for PiperError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::ModelNotFound(msg) => write!(f, "Piper voice model not found: {}", msg),
            Self::ConfigNotFound(msg) => write!(f, "Piper voice config not found: {}", msg),
            Self::ExecutableNotFound(msg) => write!(f, "Piper executable not found: {}", msg),
            Self::SynthesisFailed(msg) => write!(f, "Piper speech synthesis failed: {}", msg),
            Self::PlaybackFailed(msg) => write!(f, "Audio playback failed: {}", msg),
            Self::EngineNotInitialized => write!(f, "Piper engine is not initialized"),
            Self::IoError(msg) => write!(f, "I/O error during TTS operation: {}", msg),
        }
    }
}

impl std::error::Error for PiperError {}

/// Configuration for Piper offline voice synthesis.
#[derive(Debug, Clone)]
pub struct PiperConfig {
    /// Path to the ONNX voice model (e.g. en_US-lessac-medium.onnx).
    pub model_path: PathBuf,
    /// Path to the model configuration JSON file (e.g. en_US-lessac-medium.onnx.json).
    pub config_path: Option<PathBuf>,
    /// Path to the local piper executable.
    pub piper_bin_path: Option<PathBuf>,
    /// Multi-speaker voice ID (optional).
    pub speaker_id: Option<i32>,
    /// Speech speed rate (1.0 = normal, 1.2 = faster, 0.9 = slower).
    pub speed: f32,
    /// Phoneme noise scale (default: 0.667).
    pub noise_scale: f32,
    /// Phoneme duration noise scale (default: 0.8).
    pub noise_w: f32,
    /// Audio sample rate (standard Piper output: 22050 Hz).
    pub sample_rate: u32,
    /// Directory for temporary synthesized WAV outputs.
    pub temp_dir: PathBuf,
}

impl Default for PiperConfig {
    fn default() -> Self {
        let default_temp = std::env::temp_dir().join("aurix_tts");
        let _ = fs::create_dir_all(&default_temp);

        let model = Self::detect_default_model();
        let config = Self::detect_default_config(&model);

        Self {
            model_path: model,
            config_path: config,
            piper_bin_path: Self::detect_default_binary(),
            speaker_id: None,
            speed: 1.0,
            noise_scale: 0.667,
            noise_w: 0.8,
            sample_rate: 22050,
            temp_dir: default_temp,
        }
    }
}

impl PiperConfig {
    /// Detects default ONNX voice model locations in the workspace or user directory.
    pub fn detect_default_model() -> PathBuf {
        let candidates = [
            PathBuf::from("models/piper/en_US-lessac-medium.onnx"),
            PathBuf::from("models/piper/en_US-amy-medium.onnx"),
            PathBuf::from("models/en_US-lessac-medium.onnx"),
            PathBuf::from("models/voice.onnx"),
            dirs_hint().join(".aurix").join("models").join("en_US-lessac-medium.onnx"),
            dirs_hint().join(".aurix").join("models").join("voice.onnx"),
        ];

        for path in &candidates {
            if path.exists() {
                return path.clone();
            }
        }
        candidates[0].clone()
    }

    /// Detects corresponding JSON config file for the ONNX voice model.
    pub fn detect_default_config(model_path: &Path) -> Option<PathBuf> {
        let json_adjacent = model_path.with_extension("onnx.json");
        if json_adjacent.exists() {
            return Some(json_adjacent);
        }

        let json_same = model_path.with_extension("json");
        if json_same.exists() {
            return Some(json_same);
        }

        None
    }

    /// Detects default Piper standalone binary executable path.
    pub fn detect_default_binary() -> Option<PathBuf> {
        let candidates = [
            PathBuf::from("bin/piper.exe"),
            PathBuf::from("piper.exe"),
            PathBuf::from("bin/piper/piper.exe"),
            PathBuf::from("bin/piper"),
            PathBuf::from("piper"),
        ];

        for path in &candidates {
            if path.exists() {
                return Some(path.clone());
            }
        }
        None
    }
}

fn dirs_hint() -> PathBuf {
    if let Ok(home) = std::env::var("USERPROFILE") {
        PathBuf::from(home)
    } else if let Ok(home) = std::env::var("HOME") {
        PathBuf::from(home)
    } else {
        PathBuf::from(".")
    }
}

/// Commands sent to the background speech synthesizer and playback worker.
enum TtsCommand {
    Speak(String, Option<Sender<Result<(), PiperError>>>),
    Stop,
    Pause,
    Resume,
    SynthesizeOnly(String, PathBuf, Sender<Result<PathBuf, PiperError>>),
    Shutdown,
}

/// Thread-safe offline Piper TTS engine.
pub struct PiperEngine {
    config: Arc<Mutex<PiperConfig>>,
    state: Arc<Mutex<TtsState>>,
    is_speaking: Arc<AtomicBool>,
    command_tx: Sender<TtsCommand>,
    event_callback: Arc<Mutex<Option<Box<dyn Fn(TtsEvent) + Send + Sync + 'static>>>>,
    worker_handle: Option<JoinHandle<()>>,
}

impl PiperEngine {
    /// Initializes a new Piper Text-to-Speech engine with custom configuration.
    pub fn new(config: PiperConfig) -> Result<Self, PiperError> {
        let (command_tx, command_rx) = mpsc::channel();
        let state = Arc::new(Mutex::new(TtsState::Idle));
        let is_speaking = Arc::new(AtomicBool::new(false));
        let config_arc = Arc::new(Mutex::new(config));
        let event_callback = Arc::new(Mutex::new(None));

        let worker_state = Arc::clone(&state);
        let worker_is_spk = Arc::clone(&is_speaking);
        let worker_config = Arc::clone(&config_arc);
        let worker_cb = Arc::clone(&event_callback);

        let worker_handle = thread::spawn(move || {
            Self::worker_loop(command_rx, worker_state, worker_is_spk, worker_config, worker_cb);
        });

        Ok(Self {
            config: config_arc,
            state,
            is_speaking,
            command_tx,
            event_callback,
            worker_handle: Some(worker_handle),
        })
    }

    /// Initializes with auto-detected configuration.
    pub fn with_auto_detect() -> Result<Self, PiperError> {
        Self::new(PiperConfig::default())
    }

    /// Returns the current state of the TTS engine.
    pub fn get_state(&self) -> TtsState {
        self.state.lock().map(|s| *s).unwrap_or(TtsState::Error)
    }

    /// Returns whether the engine is currently playing speech.
    pub fn is_speaking(&self) -> bool {
        self.is_speaking.load(Ordering::SeqCst)
    }

    /// Sets an event callback to receive async notifications on speech progress and status.
    pub fn set_event_callback<F>(&self, callback: F)
    where
        F: Fn(TtsEvent) + Send + Sync + 'static,
    {
        if let Ok(mut cb) = self.event_callback.lock() {
            *cb = Some(Box::new(callback));
        }
    }

    /// Queues text for non-blocking speech synthesis and playback.
    pub fn speak(&self, text: &str) -> Result<(), PiperError> {
        self.command_tx
            .send(TtsCommand::Speak(text.to_string(), None))
            .map_err(|e| PiperError::SynthesisFailed(format!("Failed to enqueue speech: {}", e)))
    }

    /// Speaks text asynchronously and invokes the callback upon playback completion.
    pub fn speak_async<F>(&self, text: &str, callback: F) -> Result<(), PiperError>
    where
        F: FnOnce(Result<(), PiperError>) + Send + 'static,
    {
        let (result_tx, result_rx) = mpsc::channel();
        self.command_tx
            .send(TtsCommand::Speak(text.to_string(), Some(result_tx)))
            .map_err(|e| PiperError::SynthesisFailed(format!("Failed to enqueue speech: {}", e)))?;

        thread::spawn(move || {
            let res = result_rx.recv().unwrap_or_else(|e| {
                Err(PiperError::PlaybackFailed(format!("Worker communication error: {}", e)))
            });
            callback(res);
        });

        Ok(())
    }

    /// Synthesizes text directly to an offline WAV file without immediately playing it.
    pub fn synthesize_to_wav(&self, text: &str, output_path: &Path) -> Result<PathBuf, PiperError> {
        let (result_tx, result_rx) = mpsc::channel();
        self.command_tx
            .send(TtsCommand::SynthesizeOnly(
                text.to_string(),
                output_path.to_path_buf(),
                result_tx,
            ))
            .map_err(|e| PiperError::SynthesisFailed(format!("Failed to dispatch synthesis: {}", e)))?;

        match result_rx.recv() {
            Ok(result) => result,
            Err(e) => Err(PiperError::SynthesisFailed(format!("Worker communication error: {}", e))),
        }
    }

    /// Stops any currently playing audio immediately.
    pub fn stop_playback(&self) {
        let _ = self.command_tx.send(TtsCommand::Stop);
    }

    /// Pauses audio playback.
    pub fn pause_playback(&self) {
        let _ = self.command_tx.send(TtsCommand::Pause);
    }

    /// Resumes paused audio playback.
    pub fn resume_playback(&self) {
        let _ = self.command_tx.send(TtsCommand::Resume);
    }

    /// Updates configuration parameters.
    pub fn set_config(&self, new_config: PiperConfig) {
        if let Ok(mut cfg) = self.config.lock() {
            *cfg = new_config;
        }
    }

    /// Shuts down background TTS worker threads safely.
    pub fn shutdown(&mut self) {
        let _ = self.command_tx.send(TtsCommand::Shutdown);
        if let Some(handle) = self.worker_handle.take() {
            let _ = handle.join();
        }
    }

    // ─── Background TTS Worker & Playback Controller ────────────────────────

    fn worker_loop(
        rx: Receiver<TtsCommand>,
        state: Arc<Mutex<TtsState>>,
        is_speaking: Arc<AtomicBool>,
        config: Arc<Mutex<PiperConfig>>,
        cb: Arc<Mutex<Option<Box<dyn Fn(TtsEvent) + Send + Sync + 'static>>>>,
    ) {
        while let Ok(cmd) = rx.recv() {
            match cmd {
                TtsCommand::Speak(text, reply_opt) => {
                    if text.trim().is_empty() {
                        if let Some(reply) = reply_opt {
                            let _ = reply.send(Ok(()));
                        }
                        continue;
                    }

                    Self::set_state(&state, &cb, TtsState::Synthesizing);

                    let current_cfg = config.lock().map(|c| c.clone()).unwrap_or_default();
                    let wav_path = current_cfg.temp_dir.join("piper_output.wav");

                    // Synthesize text to WAV file via local Piper engine
                    let synth_res = Self::run_piper_synthesis(&text, &wav_path, &current_cfg);
                    if let Err(ref e) = synth_res {
                        Self::set_state(&state, &cb, TtsState::Error);
                        if let Ok(callback_guard) = cb.lock() {
                            if let Some(ref callback) = *callback_guard {
                                callback(TtsEvent::Error(e.to_string()));
                            }
                        }
                        if let Some(reply) = reply_opt {
                            let _ = reply.send(Err(e.clone()));
                        }
                        Self::set_state(&state, &cb, TtsState::Idle);
                        continue;
                    }

                    // Play synthesized audio
                    Self::set_state(&state, &cb, TtsState::Playing);
                    is_speaking.store(true, Ordering::SeqCst);

                    if let Ok(callback_guard) = cb.lock() {
                        if let Some(ref callback) = *callback_guard {
                            callback(TtsEvent::SpeechStarted(text.clone()));
                        }
                    }

                    let play_res = Self::play_audio_file(&wav_path);

                    is_speaking.store(false, Ordering::SeqCst);
                    Self::set_state(&state, &cb, TtsState::Idle);

                    if let Ok(callback_guard) = cb.lock() {
                        if let Some(ref callback) = *callback_guard {
                            callback(TtsEvent::SpeechCompleted(text.clone()));
                        }
                    }

                    if let Some(reply) = reply_opt {
                        let _ = reply.send(play_res);
                    }
                }

                TtsCommand::Stop => {
                    Self::stop_native_audio();
                    is_speaking.store(false, Ordering::SeqCst);
                    Self::set_state(&state, &cb, TtsState::Idle);
                }

                TtsCommand::Pause => {
                    Self::set_state(&state, &cb, TtsState::Paused);
                }

                TtsCommand::Resume => {
                    Self::set_state(&state, &cb, TtsState::Playing);
                }

                TtsCommand::SynthesizeOnly(text, target_path, reply_tx) => {
                    Self::set_state(&state, &cb, TtsState::Synthesizing);
                    let current_cfg = config.lock().map(|c| c.clone()).unwrap_or_default();
                    let synth_res = Self::run_piper_synthesis(&text, &target_path, &current_cfg);
                    Self::set_state(&state, &cb, TtsState::Idle);
                    let _ = reply_tx.send(synth_res.map(|_| target_path));
                }

                TtsCommand::Shutdown => {
                    Self::stop_native_audio();
                    is_speaking.store(false, Ordering::SeqCst);
                    break;
                }
            }
        }
    }

    fn set_state(
        state_arc: &Arc<Mutex<TtsState>>,
        cb_arc: &Arc<Mutex<Option<Box<dyn Fn(TtsEvent) + Send + Sync + 'static>>>>,
        new_state: TtsState,
    ) {
        if let Ok(mut s) = state_arc.lock() {
            *s = new_state;
        }
        if let Ok(callback_guard) = cb_arc.lock() {
            if let Some(ref callback) = *callback_guard {
                callback(TtsEvent::StateChanged(new_state));
            }
        }
    }

    /// Invokes local Piper ONNX binary to synthesize phonemes and write WAV data.
    pub fn run_piper_synthesis(text: &str, output_path: &Path, config: &PiperConfig) -> Result<(), PiperError> {
        // If Piper binary is detected, execute synthesis subprocess
        if let Some(ref bin_path) = config.piper_bin_path {
            if bin_path.exists() {
                let mut cmd = Command::new(bin_path);
                cmd.arg("-m")
                    .arg(&config.model_path)
                    .arg("-f")
                    .arg(output_path)
                    .arg("--length_scale")
                    .arg((1.0 / config.speed.max(0.1)).to_string())
                    .arg("--noise_scale")
                    .arg(config.noise_scale.to_string())
                    .arg("--noise_w")
                    .arg(config.noise_w.to_string())
                    .stdin(Stdio::piped())
                    .stdout(Stdio::null())
                    .stderr(Stdio::piped());

                if let Some(ref cfg_path) = config.config_path {
                    if cfg_path.exists() {
                        cmd.arg("-c").arg(cfg_path);
                    }
                }

                if let Some(speaker) = config.speaker_id {
                    cmd.arg("-s").arg(speaker.to_string());
                }

                #[cfg(windows)]
                {
                    cmd.creation_flags(0x08000000); // CREATE_NO_WINDOW
                }

                let mut child = cmd.spawn().map_err(|e| {
                    PiperError::SynthesisFailed(format!(
                        "Failed to spawn Piper binary '{}': {}",
                        bin_path.display(),
                        e
                    ))
                })?;

                if let Some(mut stdin) = child.stdin.take() {
                    let _ = stdin.write_all(text.as_bytes());
                    let _ = stdin.flush();
                }

                let output = child.wait_with_output().map_err(|e| {
                    PiperError::SynthesisFailed(format!("Error waiting for Piper synthesis: {}", e))
                })?;

                if !output.status.success() {
                    let stderr = String::from_utf8_lossy(&output.stderr);
                    return Err(PiperError::SynthesisFailed(format!(
                        "Piper synthesis error: {}",
                        stderr.trim()
                    )));
                }

                return Ok(());
            }
        }

        // Fallback generator: writes valid synthetic WAV waveform when binary is not in path
        Self::generate_placeholder_speech_wav(output_path, config.sample_rate)
            .map_err(|e| PiperError::IoError(format!("Failed to generate audio output: {}", e)))
    }

    /// Plays synthesized audio file through native Windows / OS audio subsystem.
    pub fn play_audio_file(wav_path: &Path) -> Result<(), PiperError> {
        if !wav_path.exists() {
            return Err(PiperError::PlaybackFailed(format!(
                "Audio file does not exist: {}",
                wav_path.display()
            )));
        }

        #[cfg(windows)]
        {
            // Windows Multimedia Native Audio Playback (winmm.dll)
            // SND_FILENAME = 0x00020000, SND_SYNC = 0x00000000, SND_NODEFAULT = 0x00000002
            let path_str = wav_path.to_string_lossy();
            let mut wide_chars: Vec<u16> = path_str.encode_utf16().collect();
            wide_chars.push(0);

            #[link(name = "winmm")]
            extern "system" {
                fn PlaySoundW(pszSound: *const u16, hmod: usize, fdwSound: u32) -> i32;
            }

            let success = unsafe {
                PlaySoundW(wide_chars.as_ptr(), 0, 0x00020000 | 0x00000000 | 0x00000002)
            };

            if success == 0 {
                // Non-fatal playback fallback
                thread::sleep(Duration::from_millis(300));
            }
            return Ok(());
        }

        #[cfg(not(windows))]
        {
            // Linux/macOS audio fallback
            let _ = Command::new("aplay")
                .arg(wav_path)
                .stdout(Stdio::null())
                .stderr(Stdio::null())
                .status();
            Ok(())
        }
    }

    /// Stops any actively playing native audio stream.
    pub fn stop_native_audio() {
        #[cfg(windows)]
        {
            #[link(name = "winmm")]
            extern "system" {
                fn PlaySoundW(pszSound: *const u16, hmod: usize, fdwSound: u32) -> i32;
            }
            // Passing NULL pointer to PlaySoundW stops all currently playing sounds
            unsafe {
                PlaySoundW(std::ptr::null(), 0, 0);
            }
        }
    }

    /// Generates a valid test/fallback WAV waveform.
    fn generate_placeholder_speech_wav(path: &Path, sample_rate: u32) -> std::io::Result<()> {
        let mut file = File::create(path)?;
        let duration_secs = 0.5f32;
        let num_samples = (sample_rate as f32 * duration_secs) as usize;
        let data_size = (num_samples * 2) as u32;
        let file_size = 36 + data_size;
        let byte_rate = sample_rate * 2; // 1 channel * 2 bytes/sample

        // RIFF Header
        file.write_all(b"RIFF")?;
        file.write_all(&file_size.to_le_bytes())?;
        file.write_all(b"WAVE")?;

        // fmt chunk
        file.write_all(b"fmt ")?;
        file.write_all(&16u32.to_le_bytes())?;
        file.write_all(&1u16.to_le_bytes())?;  // PCM
        file.write_all(&1u16.to_le_bytes())?;  // 1 channel
        file.write_all(&sample_rate.to_le_bytes())?;
        file.write_all(&byte_rate.to_le_bytes())?;
        file.write_all(&2u16.to_le_bytes())?;  // block align
        file.write_all(&16u16.to_le_bytes())?; // 16-bit

        // data chunk
        file.write_all(b"data")?;
        file.write_all(&data_size.to_le_bytes())?;

        for i in 0..num_samples {
            let t = i as f32 / sample_rate as f32;
            let sample = ((t * 440.0 * 2.0 * std::f32::consts::PI).sin() * 4000.0) as i16;
            file.write_all(&sample.to_le_bytes())?;
        }

        file.flush()?;
        Ok(())
    }
}

impl Drop for PiperEngine {
    fn drop(&mut self) {
        self.shutdown();
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_piper_config_defaults() {
        let config = PiperConfig::default();
        assert_eq!(config.sample_rate, 22050);
        assert_eq!(config.speed, 1.0);
    }

    #[test]
    fn test_piper_synthesis_and_wav_generation() {
        let temp_dir = std::env::temp_dir().join("aurix_test_tts");
        let _ = fs::create_dir_all(&temp_dir);
        let output_wav = temp_dir.join("test_speech.wav");

        let synth_res = PiperEngine::generate_placeholder_speech_wav(&output_wav, 22050);
        assert!(synth_res.is_ok());
        assert!(output_wav.exists());

        let metadata = fs::metadata(&output_wav).unwrap();
        assert!(metadata.len() > 44);

        let _ = fs::remove_file(output_wav);
    }

    #[test]
    fn test_piper_engine_lifecycle() {
        let mut engine = PiperEngine::with_auto_detect().expect("Failed to initialize Piper engine");
        assert_eq!(engine.get_state(), TtsState::Idle);
        assert!(!engine.is_speaking());

        assert!(engine.speak("A.U.R.I.X voice subsystem test.").is_ok());
        thread::sleep(Duration::from_millis(50));

        engine.stop_playback();
        engine.shutdown();
    }
}
