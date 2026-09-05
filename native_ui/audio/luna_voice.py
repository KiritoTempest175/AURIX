"""LUNA Audio & Voice Engine — Dynamic Speech Recording and Interruptible TTS.

Provides:
1. `record_audio`: Dynamic voice recording with adaptive noise floor calibration,
   pre-roll buffering to prevent clipped words, and silence cutoff detection.
2. `speak`: Real-time female voice Text-to-Speech (Piper ONNX) with 80ms chunked playback
   and lockstep microphone interruption detection (wake-word / voice burst).
"""

from __future__ import annotations

import collections
import logging
import os
import subprocess
import tempfile
import threading
import time
import warnings
from pathlib import Path
from typing import Callable, Optional

import numpy as np

try:
    import sounddevice as sd
    HAS_SOUNDDEVICE = True
except ImportError:
    sd = None
    HAS_SOUNDDEVICE = False


try:
    from scipy.io.wavfile import write as wav_write
    HAS_SCIPY = True
except ImportError:
    import wave
    HAS_SCIPY = False

try:
    from piper.voice import PiperVoice
    HAS_PIPER_VOICE = True
except ImportError:
    PiperVoice = None
    HAS_PIPER_VOICE = False

logging.getLogger("root").setLevel(logging.ERROR)
warnings.filterwarnings("ignore")

logger = logging.getLogger("luna.audio.voice")

# Base directory paths
BASE_DIR = Path(__file__).resolve().parent.parent.parent
VOICES_DIR = BASE_DIR / "voices"

# Female Piper Voice Models (in priority order)
FEMALE_VOICE_CANDIDATES = [
    VOICES_DIR / "en_US-amy-medium.onnx",        # Crisp natural American female
    VOICES_DIR / "en_US-lessac-medium.onnx",     # High quality female/neutral
    VOICES_DIR / "en_US-hfc_female-medium.onnx",  # American female voice
    VOICES_DIR / "en_US-kristin-medium.onnx",    # Expressive female voice
    VOICES_DIR / "luna-female.onnx",             # Custom Luna voice
    VOICES_DIR / "female-medium.onnx",
]

_voice_instance: Optional[object] = None
_voice_model_path: Optional[Path] = None
_wake_model: Optional[object] = None
_lock = threading.Lock()


def get_female_voice_model() -> tuple[Optional[Path], Optional[Path]]:
    """Resolve the best available female Piper ONNX model and its config JSON."""
    custom_model = os.getenv("LUNA_VOICE_MODEL")
    if custom_model:
        p = Path(custom_model)
        if p.exists():
            cfg = p.with_suffix(".onnx.json") if not str(p).endswith(".onnx.json") else p
            if not cfg.exists():
                cfg = p.with_suffix(".json")
            return p, (cfg if cfg.exists() else None)

    for candidate in FEMALE_VOICE_CANDIDATES:
        if candidate.exists():
            cfg = candidate.with_suffix(".onnx.json")
            if not cfg.exists():
                cfg = candidate.with_suffix(".json")
            return candidate, (cfg if cfg.exists() else None)

    # Check any .onnx inside voices directory
    if VOICES_DIR.exists():
        for f in VOICES_DIR.glob("*.onnx"):
            cfg = f.with_suffix(".onnx.json")
            if not cfg.exists():
                cfg = f.with_suffix(".json")
            return f, (cfg if cfg.exists() else None)

    # Default placeholder path for auto-download / Piper setup
    default_model = VOICES_DIR / "en_US-amy-medium.onnx"
    default_cfg = VOICES_DIR / "en_US-amy-medium.onnx.json"
    return default_model, default_cfg


def get_voice():
    """Lazy-load and cache the PiperVoice instance in memory for zero-lag synthesis."""
    global _voice_instance, _voice_model_path
    if not HAS_PIPER_VOICE:
        return None

    with _lock:
        model_path, config_path = get_female_voice_model()
        if model_path and model_path.exists() and _voice_instance is None:
            try:
                cfg_str = str(config_path) if config_path and config_path.exists() else None
                _voice_instance = PiperVoice.load(str(model_path), config_path=cfg_str)
                _voice_model_path = model_path
                logger.info(f"Loaded Luna female voice model: {model_path.name}")
            except Exception as e:
                logger.warning(f"Failed to load PiperVoice in memory: {e}")
                _voice_instance = None
    return _voice_instance


def get_wake_model():
    """Lazy-load openwakeword model if installed."""
    global _wake_model
    if _wake_model is None:
        try:
            from openwakeword.model import Model
            # Load wake word models (e.g. hey_jarvis or custom wake words)
            _wake_model = Model(wakeword_models=["hey_jarvis"])
        except Exception:
            _wake_model = None
    return _wake_model


from native_ui.audio.stt import transcribe_audio


# ============================================================================
# 1. DYNAMIC AUDIO RECORDING
# ============================================================================

def record_audio(
    filename: str = "input.wav",
    sample_rate: int = 16000,
    silence_limit: float = 1.2,
    initial_timeout: float = 6.0,
    max_record_time: float = 30.0,
    on_status: Optional[Callable[[str], None]] = None,
) -> Optional[str]:
    """Dynamically listens and records speech:
    - Flushes initial device-open transient spikes.
    - Calibrates noise floor adaptively from ambient samples.
    - Waits for speech to start (up to initial_timeout seconds).
    - Preserves 600ms pre-roll audio buffer so initial phonemes are never clipped.
    - Continuously records as long as user is speaking.
    - When user stops speaking and `silence_limit` seconds of silence is observed, stops and saves.
    - If user did not speak at all within timeout, returns None.
    """
    if not HAS_SOUNDDEVICE:
        logger.warning("sounddevice is not installed. Run: pip install sounddevice")
        return None

    logger.info("🎤 [Luna] Microphone listening initiated...")
    if on_status:
        try:
            on_status("Listening... Speak now.")
        except Exception:
            pass

    chunk_size = int(sample_rate * 0.1)  # 100ms per block
    silence_chunks_needed = max(8, int(silence_limit / 0.1))
    timeout_chunks = int(initial_timeout / 0.1)

    pre_buffer = collections.deque(maxlen=6)  # 600ms pre-roll
    recorded_chunks = []

    speech_started = False
    consecutive_silence = 0
    total_chunks = 0

    ambient_samples = []

    try:
        with sd.InputStream(samplerate=sample_rate, channels=1, dtype="int16") as stream:
            # 1. Flush initial device-opening pop/click
            stream.read(chunk_size)

            # 2. Measure ambient noise across 300ms
            for _ in range(3):
                c, _ = stream.read(chunk_size)
                ambient_samples.append(float(np.sqrt(np.mean(c.astype(np.float32) ** 2))))
                pre_buffer.append(c)

            ambient_floor = float(np.mean(ambient_samples))
            # Clamp floor to reasonable bounds (10.0 to 80.0)
            ambient_floor = max(10.0, min(80.0, ambient_floor))

            # Speech onset thresholds: adaptive to room noise
            onset_rms = max(25.0, ambient_floor * 1.5)
            onset_peak = max(220.0, ambient_floor * 4.0)

            # Silence cutoff threshold
            cutoff_rms = max(18.0, ambient_floor * 1.25)
            cutoff_peak = max(160.0, ambient_floor * 2.5)

            logger.debug(
                f"Audio calibrated: ambient_floor={ambient_floor:.1f}, "
                f"onset_rms={onset_rms:.1f}, onset_peak={onset_peak:.1f}"
            )

            while True:
                chunk, _ = stream.read(chunk_size)
                total_chunks += 1

                rms = float(np.sqrt(np.mean(chunk.astype(np.float32) ** 2)))
                max_val = float(np.max(np.abs(chunk)))

                # Speech onset detection
                if not speech_started:
                    pre_buffer.append(chunk)

                    if rms > onset_rms or max_val > onset_peak:
                        speech_started = True
                        if on_status:
                            try:
                                on_status("Hearing speech...")
                            except Exception:
                                pass
                        # Prepend pre-roll buffer to preserve start of speech
                        recorded_chunks.extend(list(pre_buffer))
                        consecutive_silence = 0
                    elif total_chunks >= timeout_chunks:
                        # User did not speak within initial timeout
                        logger.info("Voice recording timed out: No speech detected.")
                        return None
                else:
                    # Active recording mode
                    recorded_chunks.append(chunk)

                    if rms < cutoff_rms and max_val < cutoff_peak:
                        consecutive_silence += 1
                        if consecutive_silence >= silence_chunks_needed:
                            # User finished speaking
                            logger.info(f"Speech finished after {len(recorded_chunks) * 0.1:.1f}s.")
                            break
                    else:
                        consecutive_silence = 0

                    # Safety maximum duration
                    if total_chunks * 0.1 >= max_record_time:
                        break

    except Exception as e:
        logger.error(f"Microphone recording error: {e}")
        if not recorded_chunks:
            return None

    if not recorded_chunks:
        return None

    audio_array = np.concatenate(recorded_chunks, axis=0)

    # Save to WAV file
    os.makedirs(os.path.dirname(os.path.abspath(filename)), exist_ok=True)
    if HAS_SCIPY:
        wav_write(filename, sample_rate, audio_array)
    else:
        with wave.open(filename, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(audio_array.tobytes())

    logger.info(f"🎤 [Luna] Recording complete: saved to {filename}")
    return filename


# ============================================================================
# 2. SYNCHRONIZED INTERRUPTIBLE TTS (FEMALE VOICE)
# ============================================================================

def _speak_windows_sapi_female(text: str) -> bool:
    """Fallback female voice synthesizer using Windows SAPI5 (Microsoft Zira / Hazel / female)."""
    try:
        ps_script = f"""
Add-Type -AssemblyName System.Speech
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
$female = $synth.GetInstalledVoices() | Where-Object {{ $_.VoiceInfo.Gender -eq 'Female' -or $_.VoiceInfo.Name -match 'Zira|Hazel|Eva|Susan|Jenny' }} | Select-Object -First 1
if ($female) {{
    $synth.SelectVoice($female.VoiceInfo.Name)
}}
$synth.Speak('{text.replace("'", "''")}')
"""
        res = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script],
            capture_output=True,
            timeout=30,
        )
        return res.returncode == 0
    except Exception as e:
        logger.debug(f"SAPI fallback speak failed: {e}")
        return False


def speak(
    text: str,
    interruptible: bool = True,
    ack_phrase: str = "Yes, I'm listening.",
) -> bool:
    """Speaks text in Luna's female voice with chunk-by-chunk synchronized I/O.

    - If interruptible=True, plays audio in small 80ms slices while reading mic in lockstep.
    - If user speaks or triggers wake-word during playback, playback halts within 80ms
      and acknowledges with a female response (e.g. 'Yes, I'm listening.').
    - Returns True if interrupted, False otherwise.
    """
    if not text or not text.strip():
        return False

    voice = get_voice()
    if voice is not None and HAS_SOUNDDEVICE:
        try:

            audio_chunks = []
            for chunk in voice.synthesize(text):
                audio_chunks.append(chunk.audio_float_array)

            if audio_chunks:
                full_audio = np.concatenate(audio_chunks, axis=0)
                sr = voice.config.sample_rate

                if not interruptible or len(full_audio) < int(sr * 0.8):
                    sd.play(full_audio, sr)
                    sd.wait()
                    return False

                # Synchronized Chunked Playback + Mic Interruption
                wake_model = get_wake_model()
                out_stream = sd.OutputStream(samplerate=sr, channels=1, dtype="float32")
                in_stream = sd.InputStream(samplerate=16000, channels=1, dtype="int16", blocksize=1280)

                out_stream.start()
                in_stream.start()

                chunk_size = int(sr * 0.08)  # 80ms audio slice
                pos = 0
                interrupted = False

                # Skip first 160ms (2 chunks) to prevent mic catching initial speaker burst
                warmup_chunks = 2
                chunk_index = 0

                try:
                    while pos < len(full_audio):
                        end = min(pos + chunk_size, len(full_audio))
                        slice_data = full_audio[pos:end]
                        out_stream.write(slice_data)
                        pos = end
                        chunk_index += 1

                        # Read mic in lockstep
                        mic_data, _ = in_stream.read(1280)

                        if chunk_index > warmup_chunks:
                            flat = mic_data.flatten()
                            peak_val = np.max(np.abs(flat))

                            # 1. Wake word model score (if available)
                            score = 0.0
                            if wake_model is not None:
                                try:
                                    pred = wake_model.predict(flat)
                                    score = max(pred.values()) if pred else 0.0
                                except Exception:
                                    score = 0.0

                            # 2. Voice interruption trigger (wake word or sharp speech onset)
                            if score > 0.15 or (score > 0.08 and peak_val > 10000) or peak_val > 18000:
                                interrupted = True
                                if wake_model is not None:
                                    try:
                                        wake_model.reset()
                                    except Exception:
                                        pass
                                print("\n\u26a1 [Luna Interrupted!]")
                                break

                finally:
                    out_stream.stop()
                    out_stream.close()
                    in_stream.stop()
                    in_stream.close()

                if interrupted:
                    # Immediate female acknowledgment
                    try:
                        ack_chunks = []
                        for c in voice.synthesize(ack_phrase):
                            ack_chunks.append(c.audio_float_array)
                        if ack_chunks:
                            ack_audio = np.concatenate(ack_chunks, axis=0)
                            sd.play(ack_audio, sr)
                            sd.wait()
                    except Exception:
                        pass
                    return True

                return False

        except Exception as e:
            logger.warning(f"Direct Piper playback error: {e}, attempting CLI/SAPI fallback")

    # Fallback 1: Piper CLI with female voice model
    model_path, config_path = get_female_voice_model()
    if model_path and model_path.exists():
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                output_file = f.name

            cmd = ["piper", "-m", str(model_path), "-f", output_file]
            if config_path and config_path.exists():
                cmd.extend(["-c", str(config_path)])

            subprocess.run(
                cmd,
                input=text.encode("utf-8"),
                check=True,
                capture_output=True,
            )

            import winsound
            winsound.PlaySound(output_file, winsound.SND_FILENAME)

            try:
                os.remove(output_file)
            except Exception:
                pass
            return False
        except Exception as e:
            logger.debug(f"Piper CLI fallback failed: {e}")

    # Fallback 2: Native Windows SAPI5 Female Voice (Microsoft Zira / Hazel)
    if _speak_windows_sapi_female(text):
        return False

    # Fallback 3: Standard console logging if audio output is unavailable
    print(f"[Luna (Female Voice)]: {text}")
    return False


# Auto-detect voice model on load
try:
    get_voice()
    get_wake_model()
except Exception:
    pass
