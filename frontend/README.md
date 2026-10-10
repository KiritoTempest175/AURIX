# AURIX desktop application

Windows installer preview: https://github.com/KiritoTempest175/AURIX/releases

The packaged application includes the Tauri UI, Python worker, and desktop-control Python dependencies. **An end user does not need Python, Node.js, Rust or terminal commands.**

On opening AURIX, the worker should connect and greet you. In **Models**, enable downloads, install Ollama, download an available local model, and activate it. The quick commands **Open WhatsApp**, **Open calculator** and **Open notepad** use safe built-in routing even if no model is installed.

In **Email**, enter a Gmail address and app password. Windows DPAPI protects the stored secret. Message sending is still gated on user review. **System** offers opt-in "Hey Luna" listening and a microphone test. Windows speech recognition and installed voice/language support vary; a dedicated local Whisper installation is optional.

The test preview remains unsigned. Physical mic/speaker, third-party app automation and email delivery have not been fully verified on end-user devices.

Developer-only source setup:
```powershell
cd frontend
npm install
npm run tauri dev
```
