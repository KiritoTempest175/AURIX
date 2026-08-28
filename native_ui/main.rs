// ─────────────────────────────────────────────────────────────────────────────
// native_ui/main.rs — AURIX Desktop Application Entry Point
// ─────────────────────────────────────────────────────────────────────────────
// Launches the GPU-accelerated Slint Command Center window.
// ─────────────────────────────────────────────────────────────────────────────

slint::include_modules!();

fn main() -> Result<(), slint::PlatformError> {
    let main_window = AurixCommandCenter::new()?;
    main_window.run()
}
