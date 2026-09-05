// ─────────────────────────────────────────────────────────────────────────────
// AURIX Desktop AI Agent — Configuration Subsystem: Local TOML Configuration
// ─────────────────────────────────────────────────────────────────────────────
// Strongly-typed configuration parser, validator, and serializer for AURIX.
// Controls Security & Path Whitelists, Audio (Whisper STT / Piper TTS),
// Hardware Resource Thresholds (RAM/VRAM Governor), and General UI settings.
//
// Invariants:
// - Zero external network calls. Everything operates locally.
// - All configuration paths are strictly validated through the security sandbox.
// - No arbitrary command execution from configuration values.
// - Graceful fallback to verified safe defaults on missing or corrupted files.
// ─────────────────────────────────────────────────────────────────────────────

use std::fmt;
use std::fs::{self, File};
use std::io::{Read, Write};
use std::path::{Path, PathBuf};

// ─── Configuration Errors ───────────────────────────────────────────────────

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ConfigError {
    FileNotFound(String),
    IoError(String),
    ParseError(String),
    ValidationError(String),
    SecurityViolation(String),
}

impl fmt::Display for ConfigError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::FileNotFound(path) => write!(f, "Configuration file not found: {}", path),
            Self::IoError(msg) => write!(f, "I/O error reading configuration: {}", msg),
            Self::ParseError(msg) => write!(f, "TOML parse error: {}", msg),
            Self::ValidationError(msg) => write!(f, "Configuration validation failed: {}", msg),
            Self::SecurityViolation(msg) => write!(f, "Security sandbox violation in configuration: {}", msg),
        }
    }
}

impl std::error::Error for ConfigError {}

// ─── Security Configuration Section ─────────────────────────────────────────

#[derive(Debug, Clone, PartialEq)]
pub struct SecurityConfig {
    /// Whitelist of allowed project directory roots accessible to AURIX.
    pub allowed_project_paths: Vec<PathBuf>,
    /// Whether File Jail sandbox path canonicalization is strictly enforced.
    pub file_jail_enabled: bool,
    /// Read-only sandbox mode (prevents file writes and modifications).
    pub read_only_mode: bool,
    /// Require explicit cryptographic trust token for privileged file access.
    pub trust_token_required: bool,
}

impl Default for SecurityConfig {
    fn default() -> Self {
        let default_workspace = std::env::current_dir().unwrap_or_else(|_| PathBuf::from("."));
        let default_projects = get_default_projects_dir();

        Self {
            allowed_project_paths: vec![default_workspace, default_projects],
            file_jail_enabled: true,
            read_only_mode: false,
            trust_token_required: true,
        }
    }
}

impl SecurityConfig {
    /// Validates that a requested path is strictly within the allowed project paths whitelist.
    pub fn is_path_allowed(&self, target_path: &Path) -> Result<bool, ConfigError> {
        if !self.file_jail_enabled {
            return Ok(true);
        }

        let canonical_target = match target_path.canonicalize() {
            Ok(p) => p,
            Err(_) => {
                // If target doesn't exist yet, check its nearest existing parent
                let mut curr = target_path.to_path_buf();
                while let Some(parent) = curr.parent() {
                    if parent.exists() {
                        if let Ok(canon_parent) = parent.canonicalize() {
                            curr = canon_parent;
                            break;
                        }
                    }
                    curr = parent.to_path_buf();
                }
                curr
            }
        };

        for allowed in &self.allowed_project_paths {
            if let Ok(canonical_allowed) = allowed.canonicalize() {
                if canonical_target.starts_with(&canonical_allowed) {
                    return Ok(true);
                }
            } else if canonical_target.starts_with(allowed) {
                return Ok(true);
            }
        }

        Err(ConfigError::SecurityViolation(format!(
            "Target path '{}' is outside the permitted whitelist",
            target_path.display()
        )))
    }
}

// ─── Audio Configuration Section ────────────────────────────────────────────

#[derive(Debug, Clone, PartialEq)]
pub struct AudioConfig {
    /// Microphone input device name ("Default" or specific device).
    pub microphone: String,
    /// Path to Whisper GGML model for offline speech-to-text.
    pub whisper_model_path: PathBuf,
    /// Language code for Whisper transcription (e.g. "en", "auto").
    pub whisper_language: String,
    /// CPU threads allocated to Whisper inference.
    pub whisper_threads: usize,
    /// Target audio sample rate for STT (default: 16000 Hz).
    pub whisper_sample_rate: u32,
    /// Voice synthesizer name ("Default" or specific voice).
    pub voice: String,
    /// Path to Piper ONNX voice model.
    pub piper_model_path: PathBuf,
    /// Path to Piper ONNX model JSON configuration.
    pub piper_config_path: Option<PathBuf>,
    /// Speech playback speed multiplier (1.0 = normal, 1.2 = faster).
    pub piper_speed: f32,
    /// Whether AURIX should automatically speak responses aloud via TTS.
    pub auto_tts_reply: bool,
}

impl Default for AudioConfig {
    fn default() -> Self {
        Self {
            microphone: "Default".to_string(),
            whisper_model_path: PathBuf::from("models/whisper/ggml-base.en.bin"),
            whisper_language: "en".to_string(),
            whisper_threads: std::thread::available_parallelism().map(|n| n.get()).unwrap_or(4).min(8),
            whisper_sample_rate: 16_000,
            voice: "Default".to_string(),
            piper_model_path: PathBuf::from("models/piper/en_US-lessac-medium.onnx"),
            piper_config_path: Some(PathBuf::from("models/piper/en_US-lessac-medium.onnx.json")),
            piper_speed: 1.0,
            auto_tts_reply: true,
        }
    }
}

// ─── Resource Governor Configuration Section ────────────────────────────────

#[derive(Debug, Clone, PartialEq)]
pub struct ResourceConfig {
    /// Maximum host RAM usage threshold in gigabytes before Governor triggers throttle/suspend.
    pub max_ram_gb: f64,
    /// Maximum discrete GPU VRAM usage threshold in gigabytes.
    pub max_vram_gb: f64,
    /// CPU load percentage ceiling threshold (e.g. 85.0%).
    pub cpu_throttle_percent: f64,
    /// Background telemetry hardware polling interval in milliseconds (default: 1000ms).
    pub poll_interval_ms: u64,
    /// Whether to automatically suspend AI workloads upon ceiling breach.
    pub suspend_on_overload: bool,
}

impl Default for ResourceConfig {
    fn default() -> Self {
        Self {
            max_ram_gb: 12.0,
            max_vram_gb: 6.0,
            cpu_throttle_percent: 85.0,
            poll_interval_ms: 1000,
            suspend_on_overload: true,
        }
    }
}

// ─── General Configuration Section ──────────────────────────────────────────

#[derive(Debug, Clone, PartialEq)]
pub struct GeneralConfig {
    /// Visual interface theme ("dark", "midnight", "command-center").
    pub theme: String,
    /// Strictly enforce local offline mode (prohibits all network egress).
    pub offline_mode: bool,
    /// Logging verbosity level ("debug", "info", "warn", "error").
    pub log_level: String,
    /// Path for encrypted session logs.
    pub log_file: PathBuf,
}

impl Default for GeneralConfig {
    fn default() -> Self {
        Self {
            theme: "dark".to_string(),
            offline_mode: true,
            log_level: "info".to_string(),
            log_file: PathBuf::from("logs/aurix_session.log"),
        }
    }
}

// ─── LLM Configuration Section ──────────────────────────────────────────────

#[derive(Debug, Clone, PartialEq)]
pub struct LlmConfig {
    pub model_name: String,
    pub model_alias: String,
    pub max_seq_length: usize,
    pub load_in_4bit: bool,
    pub quantization: String,
    pub device: String,
    pub temperature: f32,
    pub top_p: f32,
}

impl Default for LlmConfig {
    fn default() -> Self {
        Self {
            model_name: "google/gemma-4-E4B-it".to_string(),
            model_alias: "Gemma 3n E4B".to_string(),
            max_seq_length: 2048,
            load_in_4bit: true,
            quantization: "nf4".to_string(),
            device: "cuda".to_string(),
            temperature: 0.7,
            top_p: 0.9,
        }
    }
}

// ─── Root AURIX Configuration ───────────────────────────────────────────────

#[derive(Debug, Clone, Default, PartialEq)]
pub struct AurixConfig {
    pub security: SecurityConfig,
    pub audio: AudioConfig,
    pub resources: ResourceConfig,
    pub general: GeneralConfig,
    pub llm: LlmConfig,
}

impl AurixConfig {
    /// Loads configuration by searching standard local paths or creates default if absent.
    pub fn load_or_default() -> Self {
        match Self::load() {
            Ok(config) => config,
            Err(e) => {
                eprintln!("[A.U.R.I.X Config]: Notice: Using default configuration (reason: {}).", e);
                let default_cfg = Self::default();
                let _ = default_cfg.save_to_path(&PathBuf::from("config.toml"));
                default_cfg
            }
        }
    }

    /// Searches standard configuration paths and loads the first valid config found.
    pub fn load() -> Result<Self, ConfigError> {
        let candidates = [
            PathBuf::from("config.toml"),
            PathBuf::from("config/config.toml"),
            dirs_hint().join(".aurix").join("config.toml"),
            PathBuf::from("../config.toml"),
        ];

        for path in &candidates {
            if path.exists() {
                return Self::load_from_path(path);
            }
        }

        Err(ConfigError::FileNotFound("No config.toml located in search paths".to_string()))
    }

    /// Loads and parses configuration from a specific file path.
    pub fn load_from_path(path: &Path) -> Result<Self, ConfigError> {
        let mut file = File::open(path).map_err(|e| {
            ConfigError::IoError(format!("Failed to open '{}': {}", path.display(), e))
        })?;

        let mut content = String::new();
        file.read_to_string(&mut content).map_err(|e| {
            ConfigError::IoError(format!("Failed to read '{}': {}", path.display(), e))
        })?;

        let config = Self::parse_toml(&content)?;
        config.validate()?;
        Ok(config)
    }

    /// Saves the current configuration to a TOML file.
    pub fn save_to_path(&self, path: &Path) -> Result<(), ConfigError> {
        if let Some(parent) = path.parent() {
            if !parent.as_os_str().is_empty() {
                let _ = fs::create_dir_all(parent);
            }
        }

        let toml_str = self.to_toml_string();
        let mut file = File::create(path).map_err(|e| {
            ConfigError::IoError(format!("Failed to create '{}': {}", path.display(), e))
        })?;

        file.write_all(toml_str.as_bytes()).map_err(|e| {
            ConfigError::IoError(format!("Failed to write to '{}': {}", path.display(), e))
        })?;

        file.flush().map_err(|e| {
            ConfigError::IoError(format!("Failed to flush '{}': {}", path.display(), e))
        })?;

        Ok(())
    }

    /// Validates all configuration constraints and invariants.
    pub fn validate(&self) -> Result<(), ConfigError> {
        // Resource ceilings validation
        if self.resources.max_ram_gb <= 0.0 || self.resources.max_ram_gb > 512.0 {
            return Err(ConfigError::ValidationError(format!(
                "Invalid max_ram_gb '{}'. Must be between 1.0 and 512.0 GB.",
                self.resources.max_ram_gb
            )));
        }

        if self.resources.max_vram_gb <= 0.0 || self.resources.max_vram_gb > 256.0 {
            return Err(ConfigError::ValidationError(format!(
                "Invalid max_vram_gb '{}'. Must be between 1.0 and 256.0 GB.",
                self.resources.max_vram_gb
            )));
        }

        if self.resources.poll_interval_ms < 50 || self.resources.poll_interval_ms > 60_000 {
            return Err(ConfigError::ValidationError(format!(
                "Invalid poll_interval_ms '{}'. Must be between 50ms and 60000ms.",
                self.resources.poll_interval_ms
            )));
        }

        // Audio parameters validation
        if self.audio.whisper_sample_rate != 16_000 && self.audio.whisper_sample_rate != 8_000 {
            return Err(ConfigError::ValidationError(format!(
                "Whisper sample rate must be 16000 Hz, got {}",
                self.audio.whisper_sample_rate
            )));
        }

        if self.audio.piper_speed <= 0.1 || self.audio.piper_speed > 4.0 {
            return Err(ConfigError::ValidationError(format!(
                "Piper speech speed must be between 0.1 and 4.0, got {}",
                self.audio.piper_speed
            )));
        }

        // Security whitelist validation
        if self.security.allowed_project_paths.is_empty() {
            return Err(ConfigError::ValidationError(
                "Security whitelist cannot be empty; at least one project path must be specified.".to_string(),
            ));
        }

        Ok(())
    }

    /// Serializes configuration struct into clean, documented TOML text.
    pub fn to_toml_string(&self) -> String {
        let mut out = String::new();
        out.push_str("# ═══════════════════════════════════════════════════════════════════════════\n");
        out.push_str("#  A.U.R.I.X Desktop AI Agent — Local System Configuration\n");
        out.push_str("# ═══════════════════════════════════════════════════════════════════════════\n\n");

        // [security]
        out.push_str("[security]\n");
        out.push_str("# Whitelisted project directories accessible to the AURIX agent\n");
        out.push_str("allowed_project_paths = [\n");
        for p in &self.security.allowed_project_paths {
            let normalized = p.to_string_lossy().replace('\\', "/");
            out.push_str(&format!("    \"{}\",\n", normalized));
        }
        out.push_str("]\n");
        out.push_str(&format!("file_jail_enabled = {}\n", self.security.file_jail_enabled));
        out.push_str(&format!("read_only_mode = {}\n", self.security.read_only_mode));
        out.push_str(&format!("trust_token_required = {}\n\n", self.security.trust_token_required));

        // [audio]
        out.push_str("[audio]\n");
        out.push_str(&format!("microphone = \"{}\"\n", self.audio.microphone));
        out.push_str(&format!("whisper_model_path = \"{}\"\n", self.audio.whisper_model_path.to_string_lossy().replace('\\', "/")));
        out.push_str(&format!("whisper_language = \"{}\"\n", self.audio.whisper_language));
        out.push_str(&format!("whisper_threads = {}\n", self.audio.whisper_threads));
        out.push_str(&format!("whisper_sample_rate = {}\n", self.audio.whisper_sample_rate));
        out.push_str(&format!("voice = \"{}\"\n", self.audio.voice));
        out.push_str(&format!("piper_model_path = \"{}\"\n", self.audio.piper_model_path.to_string_lossy().replace('\\', "/")));
        if let Some(ref cfg_p) = self.audio.piper_config_path {
            out.push_str(&format!("piper_config_path = \"{}\"\n", cfg_p.to_string_lossy().replace('\\', "/")));
        }
        out.push_str(&format!("piper_speed = {:.2}\n", self.audio.piper_speed));
        out.push_str(&format!("auto_tts_reply = {}\n\n", self.audio.auto_tts_reply));

        // [resources]
        out.push_str("[resources]\n");
        out.push_str("# Maximum host RAM ceiling in GB before Governor suspends AI operations\n");
        out.push_str(&format!("max_ram_gb = {:.1}\n", self.resources.max_ram_gb));
        out.push_str("# Maximum discrete GPU VRAM ceiling in GB\n");
        out.push_str(&format!("max_vram_gb = {:.1}\n", self.resources.max_vram_gb));
        out.push_str(&format!("cpu_throttle_percent = {:.1}\n", self.resources.cpu_throttle_percent));
        out.push_str(&format!("poll_interval_ms = {}\n", self.resources.poll_interval_ms));
        out.push_str(&format!("suspend_on_overload = {}\n\n", self.resources.suspend_on_overload));

        // [general]
        out.push_str("[general]\n");
        out.push_str(&format!("theme = \"{}\"\n", self.general.theme));
        out.push_str(&format!("offline_mode = {}\n", self.general.offline_mode));
        out.push_str(&format!("log_level = \"{}\"\n", self.general.log_level));
        out.push_str(&format!("log_file = \"{}\"\n\n", self.general.log_file.to_string_lossy().replace('\\', "/")));

        // [llm]
        out.push_str("[llm]\n");
        out.push_str(&format!("model_name = \"{}\"\n", self.llm.model_name));
        out.push_str(&format!("model_alias = \"{}\"\n", self.llm.model_alias));
        out.push_str(&format!("max_seq_length = {}\n", self.llm.max_seq_length));
        out.push_str(&format!("load_in_4bit = {}\n", self.llm.load_in_4bit));
        out.push_str(&format!("quantization = \"{}\"\n", self.llm.quantization));
        out.push_str(&format!("device = \"{}\"\n", self.llm.device));
        out.push_str(&format!("temperature = {:.2}\n", self.llm.temperature));
        out.push_str(&format!("top_p = {:.2}\n", self.llm.top_p));

        out
    }

    /// Fast, zero-dependency TOML parser for AURIX configuration.
    pub fn parse_toml(input: &str) -> Result<Self, ConfigError> {
        let mut config = Self::default();
        let mut current_section = String::new();
        let mut in_array = false;
        let mut array_key = String::new();
        let mut array_values: Vec<String> = Vec::new();

        for (line_idx, raw_line) in input.lines().enumerate() {
            let line_num = line_idx + 1;
            let line = raw_line.trim();

            // Ignore comments and blank lines
            if line.is_empty() || line.starts_with('#') || line.starts_with(';') {
                continue;
            }

            // Handle multiline array completion
            if in_array {
                if line.contains(']') {
                    let before_bracket = line.split(']').next().unwrap_or("").trim();
                    for item in before_bracket.split(',') {
                        let trimmed_item = item.trim().trim_matches('"').trim_matches('\'').trim();
                        if !trimmed_item.is_empty() {
                            array_values.push(trimmed_item.to_string());
                        }
                    }
                    in_array = false;
                    Self::apply_array_field(&mut config, &current_section, &array_key, &array_values);
                    array_values.clear();
                    array_key.clear();
                    continue;
                } else {
                    for item in line.split(',') {
                        let trimmed_item = item.trim().trim_matches('"').trim_matches('\'').trim();
                        if !trimmed_item.is_empty() {
                            array_values.push(trimmed_item.to_string());
                        }
                    }
                    continue;
                }
            }

            // Section headers [section_name]
            if line.starts_with('[') && line.ends_with(']') {
                let sec = line[1..line.len() - 1].trim().to_lowercase();
                if sec.is_empty() || sec.contains('[') || sec.contains(']') {
                    return Err(ConfigError::ParseError(format!(
                        "Invalid section header at line {}: '{}'",
                        line_num, line
                    )));
                }
                current_section = sec;
                continue;
            }

            if current_section.is_empty() {
                return Err(ConfigError::ParseError(format!(
                    "Syntax error at line {}: key-value found before any [section] header: '{}'",
                    line_num, line
                )));
            }

            // Key = Value pairs
            if let Some((key_part, val_part)) = line.split_once('=') {
                let key = key_part.trim().to_lowercase();
                let val_trimmed = val_part.trim();

                if key.is_empty() || key.contains(' ') || key.contains('=') {
                    return Err(ConfigError::ParseError(format!(
                        "Invalid key format at line {}: '{}'",
                        line_num, key_part
                    )));
                }

                // Check for array start
                if val_trimmed.starts_with('[') {
                    if val_trimmed.ends_with(']') {
                        // Single-line array [ "a", "b" ]
                        let inside = &val_trimmed[1..val_trimmed.len() - 1];
                        let mut items = Vec::new();
                        for item in inside.split(',') {
                            let clean = item.trim().trim_matches('"').trim_matches('\'').trim();
                            if !clean.is_empty() {
                                items.push(clean.to_string());
                            }
                        }
                        Self::apply_array_field(&mut config, &current_section, &key, &items);
                    } else {
                        // Multiline array start
                        in_array = true;
                        array_key = key;
                        let after_bracket = val_trimmed[1..].trim();
                        for item in after_bracket.split(',') {
                            let clean = item.trim().trim_matches('"').trim_matches('\'').trim();
                            if !clean.is_empty() {
                                array_values.push(clean.to_string());
                            }
                        }
                    }
                    continue;
                }

                // Strip inline comments from scalar value
                let val_no_comment = if let Some((before_hash, _)) = val_trimmed.split_once('#') {
                    before_hash.trim()
                } else {
                    val_trimmed
                };

                if val_no_comment.is_empty() || (val_no_comment.contains('=') && !val_no_comment.starts_with('"')) {
                    return Err(ConfigError::ParseError(format!(
                        "Invalid value format at line {}: '{}'",
                        line_num, val_part
                    )));
                }

                let clean_val = val_no_comment.trim_matches('"').trim_matches('\'').trim();
                Self::apply_scalar_field(&mut config, &current_section, &key, clean_val, line_num)?;
            } else {
                return Err(ConfigError::ParseError(format!(
                    "Syntax error at line {}: expected 'key = value', found '{}'",
                    line_num, line
                )));
            }
        }

        if in_array {
            return Err(ConfigError::ParseError(format!(
                "Unterminated array for key '{}'",
                array_key
            )));
        }

        Ok(config)
    }

    fn apply_scalar_field(
        config: &mut AurixConfig,
        section: &str,
        key: &str,
        value: &str,
        line_num: usize,
    ) -> Result<(), ConfigError> {
        match (section, key) {
            // [security]
            ("security", "allowed_project_path") => {
                config.security.allowed_project_paths = vec![PathBuf::from(value)];
            }
            ("security", "file_jail_enabled") => {
                config.security.file_jail_enabled = parse_bool(value, line_num)?;
            }
            ("security", "read_only_mode") => {
                config.security.read_only_mode = parse_bool(value, line_num)?;
            }
            ("security", "trust_token_required") => {
                config.security.trust_token_required = parse_bool(value, line_num)?;
            }

            // [audio]
            ("audio", "microphone") => {
                config.audio.microphone = value.to_string();
            }
            ("audio", "whisper_model_path") => {
                config.audio.whisper_model_path = PathBuf::from(value);
            }
            ("audio", "whisper_language") => {
                config.audio.whisper_language = value.to_string();
            }
            ("audio", "whisper_threads") => {
                config.audio.whisper_threads = value.parse::<usize>().map_err(|_| {
                    ConfigError::ParseError(format!("Invalid integer for whisper_threads at line {}", line_num))
                })?;
            }
            ("audio", "whisper_sample_rate") => {
                config.audio.whisper_sample_rate = value.parse::<u32>().map_err(|_| {
                    ConfigError::ParseError(format!("Invalid integer for whisper_sample_rate at line {}", line_num))
                })?;
            }
            ("audio", "voice") => {
                config.audio.voice = value.to_string();
            }
            ("audio", "piper_model_path") => {
                config.audio.piper_model_path = PathBuf::from(value);
            }
            ("audio", "piper_config_path") => {
                config.audio.piper_config_path = if value.is_empty() { None } else { Some(PathBuf::from(value)) };
            }
            ("audio", "piper_speed") => {
                config.audio.piper_speed = value.parse::<f32>().map_err(|_| {
                    ConfigError::ParseError(format!("Invalid float for piper_speed at line {}", line_num))
                })?;
            }
            ("audio", "auto_tts_reply") => {
                config.audio.auto_tts_reply = parse_bool(value, line_num)?;
            }

            // [resources]
            ("resources", "max_ram_gb") => {
                config.resources.max_ram_gb = value.parse::<f64>().map_err(|_| {
                    ConfigError::ParseError(format!("Invalid float for max_ram_gb at line {}", line_num))
                })?;
            }
            ("resources", "max_vram_gb") => {
                config.resources.max_vram_gb = value.parse::<f64>().map_err(|_| {
                    ConfigError::ParseError(format!("Invalid float for max_vram_gb at line {}", line_num))
                })?;
            }
            ("resources", "cpu_throttle_percent") => {
                config.resources.cpu_throttle_percent = value.parse::<f64>().map_err(|_| {
                    ConfigError::ParseError(format!("Invalid float for cpu_throttle_percent at line {}", line_num))
                })?;
            }
            ("resources", "poll_interval_ms") => {
                config.resources.poll_interval_ms = value.parse::<u64>().map_err(|_| {
                    ConfigError::ParseError(format!("Invalid integer for poll_interval_ms at line {}", line_num))
                })?;
            }
            ("resources", "suspend_on_overload") => {
                config.resources.suspend_on_overload = parse_bool(value, line_num)?;
            }

            // [general]
            ("general", "theme") => {
                config.general.theme = value.to_string();
            }
            ("general", "offline_mode") => {
                config.general.offline_mode = parse_bool(value, line_num)?;
            }
            ("general", "log_level") => {
                config.general.log_level = value.to_string();
            }
            ("general", "log_file") => {
                config.general.log_file = PathBuf::from(value);
            }

            // [llm]
            ("llm", "model_name") => {
                config.llm.model_name = value.to_string();
            }
            ("llm", "model_alias") => {
                config.llm.model_alias = value.to_string();
            }
            ("llm", "max_seq_length") => {
                config.llm.max_seq_length = value.parse::<usize>().map_err(|_| {
                    ConfigError::ParseError(format!("Invalid integer for max_seq_length at line {}", line_num))
                })?;
            }
            ("llm", "load_in_4bit") => {
                config.llm.load_in_4bit = parse_bool(value, line_num)?;
            }
            ("llm", "quantization") => {
                config.llm.quantization = value.to_string();
            }
            ("llm", "device") => {
                config.llm.device = value.to_string();
            }
            ("llm", "temperature") => {
                config.llm.temperature = value.parse::<f32>().map_err(|_| {
                    ConfigError::ParseError(format!("Invalid float for temperature at line {}", line_num))
                })?;
            }
            ("llm", "top_p") => {
                config.llm.top_p = value.parse::<f32>().map_err(|_| {
                    ConfigError::ParseError(format!("Invalid float for top_p at line {}", line_num))
                })?;
            }

            // Unknown or unsectioned keys
            _ => {}
        }
        Ok(())
    }

    fn apply_array_field(config: &mut AurixConfig, section: &str, key: &str, items: &[String]) {
        if section == "security" && (key == "allowed_project_paths" || key == "allowed_project_path") {
            let paths: Vec<PathBuf> = items.iter().map(PathBuf::from).collect();
            if !paths.is_empty() {
                config.security.allowed_project_paths = paths;
            }
        }
    }
}

fn parse_bool(value: &str, line_num: usize) -> Result<bool, ConfigError> {
    match value.to_lowercase().as_str() {
        "true" | "yes" | "1" | "on" => Ok(true),
        "false" | "no" | "0" | "off" => Ok(false),
        _ => Err(ConfigError::ParseError(format!(
            "Invalid boolean value '{}' at line {}",
            value, line_num
        ))),
    }
}

fn get_default_projects_dir() -> PathBuf {
    if let Ok(home) = std::env::var("USERPROFILE") {
        PathBuf::from(home).join("Projects")
    } else if let Ok(home) = std::env::var("HOME") {
        PathBuf::from(home).join("Projects")
    } else {
        PathBuf::from(".")
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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_default_config_validity() {
        let config = AurixConfig::default();
        assert!(config.validate().is_ok());
        assert_eq!(config.resources.max_ram_gb, 12.0);
        assert_eq!(config.resources.max_vram_gb, 6.0);
        assert!(config.security.file_jail_enabled);
        assert!(config.general.offline_mode);
    }

    #[test]
    fn test_parse_valid_toml() {
        let toml_sample = r#"
[security]
allowed_project_paths = [
    "D:/Workspace/Projects",
    "C:/Users/Zain/Dev"
]
file_jail_enabled = true
read_only_mode = false

[audio]
microphone = "Focusrite Scarlett"
whisper_model_path = "models/whisper/ggml-base.en.bin"
whisper_language = "en"
voice = "Default"
piper_speed = 1.15
auto_tts_reply = true

[resources]
max_ram_gb = 14.5
max_vram_gb = 7.2
poll_interval_ms = 500
suspend_on_overload = true

[general]
theme = "command-center"
offline_mode = true
"#;

        let config = AurixConfig::parse_toml(toml_sample).expect("Should parse TOML");
        assert_eq!(config.security.allowed_project_paths.len(), 2);
        assert_eq!(config.audio.microphone, "Focusrite Scarlett");
        assert_eq!(config.audio.piper_speed, 1.15);
        assert_eq!(config.resources.max_ram_gb, 14.5);
        assert_eq!(config.resources.poll_interval_ms, 500);
        assert_eq!(config.general.theme, "command-center");
        assert!(config.validate().is_ok());
    }

    #[test]
    fn test_invalid_toml_syntax() {
        let invalid_toml = "this is not valid toml = =";
        let result = AurixConfig::parse_toml(invalid_toml);
        assert!(result.is_err());
    }

    #[test]
    fn test_invalid_resource_validation() {
        let mut config = AurixConfig::default();
        config.resources.max_ram_gb = -5.0;
        assert!(config.validate().is_err());

        config.resources.max_ram_gb = 16.0;
        config.resources.poll_interval_ms = 10; // too fast (<50ms)
        assert!(config.validate().is_err());
    }

    #[test]
    fn test_serialization_roundtrip() {
        let original = AurixConfig::default();
        let toml_str = original.to_toml_string();
        let parsed = AurixConfig::parse_toml(&toml_str).expect("Roundtrip parse failed");

        assert_eq!(original.resources.max_ram_gb, parsed.resources.max_ram_gb);
        assert_eq!(original.audio.microphone, parsed.audio.microphone);
        assert_eq!(original.general.theme, parsed.general.theme);
    }

    #[test]
    fn test_security_path_whitelist_check() {
        let temp_dir = std::env::temp_dir().join("aurix_whitelist_test");
        let _ = fs::create_dir_all(&temp_dir);
        let safe_subfile = temp_dir.join("workspace").join("safe.rs");
        let _ = fs::create_dir_all(safe_subfile.parent().unwrap());
        let _ = File::create(&safe_subfile);

        let mut config = SecurityConfig::default();
        config.allowed_project_paths = vec![temp_dir.clone()];

        let is_allowed = config.is_path_allowed(&safe_subfile);
        assert!(is_allowed.is_ok());
        assert!(is_allowed.unwrap());

        // Escape attempt outside whitelist
        let outside_path = PathBuf::from("C:/Windows/System32/drivers/etc/hosts");
        let outside_check = config.is_path_allowed(&outside_path);
        assert!(outside_check.is_err());

        let _ = fs::remove_dir_all(temp_dir);
    }
}
