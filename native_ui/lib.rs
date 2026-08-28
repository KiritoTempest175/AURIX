#[path = "audio/whisper_stt.rs"]
pub mod whisper_stt;

#[path = "audio/piper_tts.rs"]
pub mod piper_tts;

#[path = "bridge/event_binding.rs"]
pub mod event_binding;

slint::include_modules!();
