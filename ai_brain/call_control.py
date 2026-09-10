"""AURIX AI Brain — Native WhatsApp Call Controller.

Automates WhatsApp Desktop to initiate a voice call, then utilizes AURIX's native
STT (Whisper/Google), Piper TTS, and Gemma E4B engine for autonomous conversation.

CHANGES vs the previous version:
  1. Auto-detects when the call actually connects instead of waiting for a manual
     keypress (polls the screen for `call_active_icon.png`).
  2. Listens via SYSTEM AUDIO LOOPBACK instead of the microphone, so it can
     actually hear the receiver (the receiver's voice plays through your
     speakers/output device during a WhatsApp call — it never touches your mic
     unless you physically route it there).
  3. Auto-detects call end (receiver hangs up, or the "in-call" UI disappears)
     and clicks the real hang-up button via image matching instead of guessing
     a hotkey.

New dependency: pip install soundcard
New assets needed next to this file:
  - call_icon.png          (already had this — the call button in the chat header)
  - call_active_icon.png   (crop of something ONLY visible while a call is live,
                             e.g. the mute/speaker row in the in-call overlay)
  - end_call_icon.png      (crop of the red hang-up button)
"""

import os
import sys
import time
import logging
import traceback
import wave
from pathlib import Path

# Use insert(0) to force Python to check the AURIX root directory before anything else
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    import pyautogui
    pyautogui.PAUSE = 0.15
    pyautogui.FAILSAFE = True
    PYAUTOGUI_AVAILABLE = True
except ImportError:
    PYAUTOGUI_AVAILABLE = False

try:
    import soundcard as sc
    import numpy as np
    LOOPBACK_AVAILABLE = True
except ImportError:
    LOOPBACK_AVAILABLE = False

try:
    import msvcrt  # Windows-only, non-blocking keypress check for manual override
    MSVCRT_AVAILABLE = True
except ImportError:
    MSVCRT_AVAILABLE = False

# Import AURIX Native Subsystems with Diagnostic Traceback
AURIX_IMPORT_ERROR = ""
try:
    from native_ui.audio.luna_voice import record_audio, speak
    from native_ui.audio.stt import transcribe_audio
    from ai_engine.inference.gemma_e4b import get_default_gemma_runner

    AURIX_NATIVE_AVAILABLE = True
except Exception as e:
    AURIX_NATIVE_AVAILABLE = False
    AURIX_IMPORT_ERROR = traceback.format_exc()
    print(f"\n[CallControl] System initialization failed. Details logged.")

logger = logging.getLogger("aurix.ai_brain.call_control")

# ─── CONFIGURATION ───────────────────────────────────────────────────
WHATSAPP_LOAD_DELAY = 3.0
TEMP_AUDIO_FILE = "aurix_call_temp.wav"

CONNECT_TIMEOUT_S = 45.0          # how long to wait for the call to be picked up
CONNECT_POLL_INTERVAL_S = 1.0
CALL_STATUS_CONFIDENCE = 0.7

# Ring-tone pattern detection (WhatsApp's ringing and connected screens are
# visually identical, so "picked up" can't be read off the screen — it has to
# come from the audio: the outgoing ringback tone stops the instant the call
# is answered). These are starting-point estimates — the script prints each
# beep/gap duration it observes so you can tune them after one real test call.
RING_CHUNK_S = 0.25                # how finely we sample loopback audio
RING_LOUD_RMS_THRESHOLD = 0.02      # above this = "tone/voice", below = "gap"
RING_BEEP_MAX_S = 2.0               # a continuous loud stretch longer than this
                                     # isn't a short ring beep anymore -> connected
RING_GAP_MAX_S = 5.0                # a silent stretch longer than this means the
                                     # tone cadence broke -> connected

LOOPBACK_SAMPLE_RATE = 16000
LOOPBACK_SILENCE_LIMIT_S = 1.5     # stop recording after this much silence
LOOPBACK_MAX_RECORD_S = 20.0
LOOPBACK_INITIAL_TIMEOUT_S = 8.0   # give up if nobody speaks at all
LOOPBACK_SILENCE_RMS_THRESHOLD = 0.01
# ─────────────────────────────────────────────────────────────────────


class CallManager:
    """Handles UI automation and the real-time LLM conversation loop natively."""

    def __init__(self):
        self.conversation_history = []
        self._assets_dir = Path(__file__).parent
        if AURIX_NATIVE_AVAILABLE:
            logger.info("Initializing native Gemma E4B engine for live call...")
            self.llm = get_default_gemma_runner()
        else:
            self.llm = None

    # ─── UI AUTOMATION ────────────────────────────────────────────

    def _locate(self, filename: str, confidence: float = CALL_STATUS_CONFIDENCE):
        """Best-effort screen search for an asset image. Returns box or None."""
        path = self._assets_dir / filename
        if not path.exists():
            return None
        try:
            return pyautogui.locateOnScreen(str(path), confidence=confidence)
        except Exception:
            return None

    def _start_whatsapp_call(self, contact_name: str) -> bool:
        """Automates Windows WhatsApp to find the contact and start a call via visual targeting."""
        if not PYAUTOGUI_AVAILABLE:
            logger.error("PyAutoGUI not installed.")
            return False

        logger.info("CallManager: Opening WhatsApp to call '%s'", contact_name)

        try:
            pyautogui.press("win")
            time.sleep(0.5)
            pyautogui.write("WhatsApp", interval=0.03)
            time.sleep(0.5)
            pyautogui.press("enter")
            time.sleep(WHATSAPP_LOAD_DELAY)

            pyautogui.hotkey("win", "up")
            time.sleep(0.5)

            pyautogui.hotkey("ctrl", "n")
            time.sleep(0.5)
            pyautogui.write(contact_name, interval=0.03)
            time.sleep(1.0)
            pyautogui.press("enter")
            time.sleep(1.5)

            call_icon_path = self._assets_dir / "call_icon.png"
            if not call_icon_path.exists():
                print(f"\n[CallControl] ERROR: Missing '{call_icon_path.name}'.")
                return False

            try:
                print("[CallControl] Scanning screen for the call button...")
                call_button_loc = pyautogui.locateCenterOnScreen(
                    str(call_icon_path), confidence=CALL_STATUS_CONFIDENCE
                )
                if call_button_loc:
                    pyautogui.click(call_button_loc)
                    time.sleep(1.0)
                    return True
                else:
                    print("\n[CallControl] ERROR: Could not see the call button on screen.")
                    return False
            except Exception as e:
                print(f"\n[CallControl] Image recognition failed. Ensure opencv-python is installed. Error: {e}")
                return False

        except Exception as e:
            logger.error("WhatsApp UI automation failed: %s", e)
            return False

    def _wait_for_call_connected(self, timeout_s: float = CONNECT_TIMEOUT_S) -> bool:
        """Detects pickup via the AUDIO ring-tone pattern breaking, not the screen —
        WhatsApp's ringing and active-call screens are visually identical, so the
        screen can't tell you when it was answered. The outgoing ringback tone
        (beep...silence...beep...silence) stops the instant it's picked up, so we
        watch for that cadence breaking. You can also just press Enter at any
        point to override immediately (non-blocking — doesn't stop the auto-detect
        from running in the background)."""
        if not LOOPBACK_AVAILABLE:
            print("[CallControl] `soundcard` not installed — falling back to manual confirm.")
            input("👉 Wait for the person to pick up, then press [ENTER]: ")
            return True

        try:
            speaker = sc.default_speaker()
            mic = sc.get_microphone(id=str(speaker.name), include_loopback=True)
        except Exception as e:
            logger.error("Could not open loopback device for ring detection: %s", e)
            input("👉 Wait for the person to pick up, then press [ENTER]: ")
            return True

        print(f"[CallControl] Listening for pickup (ring-tone pattern break), up to {timeout_s:.0f}s.")
        print("[CallControl] (Press ENTER anytime to override and continue immediately.)")

        deadline = time.time() + timeout_s
        chunk_frames = int(RING_CHUNK_S * LOOPBACK_SAMPLE_RATE)

        state = "gap"       # "beep" or "gap" — current stretch we're in
        state_started = time.time()

        with mic.recorder(samplerate=LOOPBACK_SAMPLE_RATE, channels=1) as rec:
            while time.time() < deadline:
                if MSVCRT_AVAILABLE and msvcrt.kbhit():
                    key = msvcrt.getch()
                    if key in (b"\r", b"\n"):
                        print("[CallControl] Manual override — treating as connected.")
                        return True

                data = rec.record(numframes=chunk_frames)
                rms = float(np.sqrt(np.mean(np.square(data))))
                is_loud = rms > RING_LOUD_RMS_THRESHOLD
                now = time.time()

                new_state = "beep" if is_loud else "gap"
                if new_state != state:
                    duration = now - state_started
                    print(f"[CallControl] [{state}] lasted {duration:.2f}s")
                    state = new_state
                    state_started = now
                else:
                    duration = now - state_started

                if state == "beep" and duration > RING_BEEP_MAX_S:
                    print(f"[CallControl] Sustained audio for {duration:.2f}s — call connected.")
                    return True
                if state == "gap" and duration > RING_GAP_MAX_S:
                    print(f"[CallControl] Silence for {duration:.2f}s — ring cadence broke, call connected.")
                    return True

        print("[CallControl] Timed out waiting for pickup.")
        return False

    def _is_call_active(self) -> bool:
        """True while the in-call UI is still on screen; False once it disappears
        (receiver hung up, call dropped, etc.)."""
        return self._locate("call_active_icon.png") is not None

    def _end_call(self):
        """Ends the call. Tries the known WhatsApp shortcut first (fast, no image
        search needed), then verifies it actually worked — since ctrl+alt+w has
        been observed to not reliably end voice calls — and falls back to
        clicking the real hang-up button via image match if the call is still
        detected as live."""
        print("[CallControl] Trying Ctrl+Alt+W hangup shortcut...")
        try:
            pyautogui.hotkey("ctrl", "alt", "w")
        except Exception as e:
            logger.debug("Hotkey hangup failed: %s", e)
        time.sleep(0.8)

        if not self._is_call_active():
            print("[CallControl] Shortcut ended the call.")
            return

        print("[CallControl] Shortcut didn't end the call — clicking hang-up button instead.")
        loc = None
        try:
            loc = pyautogui.locateCenterOnScreen(
                str(self._assets_dir / "end_call_icon.png"),
                confidence=CALL_STATUS_CONFIDENCE,
            )
        except Exception:
            pass

        if loc:
            pyautogui.click(loc)
            time.sleep(0.5)
            if not self._is_call_active():
                print("[CallControl] Clicked hang-up button — call ended.")
            else:
                print("[CallControl] Clicked hang-up button but call still appears active — check manually.")
        else:
            print("[CallControl] Could not locate end_call_icon.png — pressing Esc as last resort.")
            pyautogui.press("esc")

    # ─── AUDIO: LOOPBACK LISTEN / TTS SPEAK ──────────────────────

    def _record_loopback(self, filename: str = TEMP_AUDIO_FILE) -> str | None:
        """Records SYSTEM OUTPUT (what's playing through your speakers) rather than
        the microphone. This is what actually contains the receiver's voice during
        a WhatsApp call. Stops on silence, like the old mic-based recorder did.
        """
        if not LOOPBACK_AVAILABLE:
            logger.error("`soundcard` not installed — cannot capture call audio. pip install soundcard")
            return None

        try:
            speaker = sc.default_speaker()
            mic = sc.get_microphone(id=str(speaker.name), include_loopback=True)
        except Exception as e:
            logger.error("Could not open loopback device: %s", e)
            return None

        frames = []
        chunk = 1024
        silence_chunks_needed = int(LOOPBACK_SILENCE_LIMIT_S * LOOPBACK_SAMPLE_RATE / chunk)
        max_chunks = int(LOOPBACK_MAX_RECORD_S * LOOPBACK_SAMPLE_RATE / chunk)
        initial_max_chunks = int(LOOPBACK_INITIAL_TIMEOUT_S * LOOPBACK_SAMPLE_RATE / chunk)

        silence_streak = 0
        heard_anything = False
        i = 0

        with mic.recorder(samplerate=LOOPBACK_SAMPLE_RATE, channels=1) as rec:
            while i < max_chunks:
                data = rec.record(numframes=chunk)  # shape (chunk, 1), float32 [-1, 1]
                frames.append(data)
                rms = float(np.sqrt(np.mean(np.square(data))))

                if rms > LOOPBACK_SILENCE_RMS_THRESHOLD:
                    heard_anything = True
                    silence_streak = 0
                else:
                    silence_streak += 1

                if heard_anything and silence_streak >= silence_chunks_needed:
                    break
                if not heard_anything and i >= initial_max_chunks:
                    return None  # nobody spoke at all — nothing to transcribe
                i += 1

        if not heard_anything:
            return None

        audio = np.concatenate(frames, axis=0)
        audio_int16 = np.clip(audio * 32767, -32768, 32767).astype(np.int16)

        out_path = str(self._assets_dir / filename)
        with wave.open(out_path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(LOOPBACK_SAMPLE_RATE)
            wf.writeframes(audio_int16.tobytes())

        return out_path

    def _listen(self) -> str:
        """Captures the receiver's side of the call via loopback and transcribes it."""
        if not AURIX_NATIVE_AVAILABLE:
            return input("\n[Receiver says] >>> ")

        print("[Listening to call audio... (loopback)]")
        audio_path = self._record_loopback()

        if not audio_path or not Path(audio_path).exists():
            return ""

        text = transcribe_audio(audio_path)

        try:
            os.remove(audio_path)
        except Exception as e:
            logger.debug(f"Failed to remove temp audio: {e}")

        if text:
            print(f"[Receiver]: {text}")
            return text
        return ""

    def _speak(self, text: str):
        """Converts text to speech using Luna's native Piper ONNX pipeline."""
        if AURIX_NATIVE_AVAILABLE:
            print(f"[Luna]: {text}")
            speak(text, interruptible=False)
        else:
            print(f"[Audio Offline - Luna]: {text}")

    # ─── LLM ──────────────────────────────────────────────────────

    def _query_gemma(self, prompt: str, system_context: str) -> str:
        if not self.llm:
            return "My neural engine is disconnected."
        formatted_prompt = self.llm.format_chat_prompt(
            user_message=prompt,
            system_instruction=system_context,
        )
        return self.llm.generate_response(formatted_prompt)

    # ─── MAIN LOOP ────────────────────────────────────────────────

    def execute_call(self, contact_name: str, vague_context: str) -> str:
        """Main loop: Dials, manages synchronized duplex conversation, and summarizes."""

        if not AURIX_NATIVE_AVAILABLE:
            return f"Cannot execute live call. Native subsystem import failed with:\n\n{AURIX_IMPORT_ERROR}"

        if self.llm:
            self.llm.clear_history()

        success = self._start_whatsapp_call(contact_name)
        if not success:
            return "Failed to automate the WhatsApp call interface."

        system_instruction = (
            "You are Luna, an AI assistant calling on behalf of Huzaifa. "
            f"Your specific goal for this call is: {vague_context}. "
            "Keep your answers extremely brief, conversational, and natural. "
            "Do not output stage directions, asterisks, or actions."
        )

        self.conversation_history.append(f"System Goal: {vague_context}")

        print("\n" + "=" * 40)
        print(" CALL DIALING...")
        print("=" * 40)

        connected = self._wait_for_call_connected()
        if not connected:
            return "Call was never picked up (or connection couldn't be confirmed)."

        print("\n--- Call Connected & Active ---")

        initial_prompt = "The receiver has just picked up the call. Give a very brief, polite opening line stating who you are and why you are calling."
        reply = self._query_gemma(initial_prompt, system_instruction)
        self._speak(reply)
        self.conversation_history.append(f"Luna: {reply}")

        turn_count = 0
        ended_by_receiver = False

        while turn_count < 8:
            turn_count += 1

            # Check BEFORE listening — if the call UI is already gone, the
            # receiver hung up while Luna was talking or in the gap between turns.
            if not self._is_call_active():
                print("[CallControl] Call UI no longer detected — receiver appears to have hung up.")
                ended_by_receiver = True
                break

            receiver_text = self._listen()

            # Re-check AFTER listening too, in case they hung up mid-silence-wait.
            if not receiver_text and not self._is_call_active():
                ended_by_receiver = True
                break

            if not receiver_text:
                user_override = input(
                    "[Call Control - Type receiver text or hit Enter to keep listening, type 'end' to hang up] >>> "
                ).strip()
                if user_override.lower() in ["end", "hangup", "bye"]:
                    break
                elif user_override:
                    receiver_text = user_override
                else:
                    continue

            if any(word in receiver_text.lower() for word in ["bye", "goodbye", "hang up", "talk to you later"]):
                self._speak("Goodbye! Have a great day.")
                self.conversation_history.append(f"Receiver: {receiver_text}")
                self.conversation_history.append("Luna: Goodbye! Have a great day.")
                break

            self.conversation_history.append(f"Receiver: {receiver_text}")

            chat_context = "\n".join(self.conversation_history[-4:])
            prompt = f"The receiver just said: '{receiver_text}'. \nRecent context:\n{chat_context}\nRespond naturally and concisely."

            reply = self._query_gemma(prompt, system_instruction)
            self._speak(reply)
            self.conversation_history.append(f"Luna: {reply}")

        print("\n--- Terminating Call ---")
        if not ended_by_receiver:
            # Only try to click hang-up if the call is still actually up —
            # if the receiver already ended it, there's nothing to click.
            if self._is_call_active():
                self._end_call()
        else:
            print("[CallControl] Receiver already ended the call — nothing to hang up.")

        summary = self._generate_summary()
        return f"Call completed. Summary:\n{summary}"

    def _generate_summary(self) -> str:
        transcript = "\n".join(self.conversation_history[1:])
        prompt = (
            f"Here is the transcript of a phone call I just completed:\n\n{transcript}\n\n"
            "Please provide a 2-3 sentence summary of the outcome of this call."
        )
        return self._query_gemma(prompt, "You are an efficient executive assistant summarizing logs.")


# ─── LLM DISPATCHER INTERFACE ───────────────────────────────────────────

def call_control(parameters: dict, response=None, player=None, session_memory=None) -> str:
    params = parameters or {}
    contact = params.get("contact", "").strip()
    context = params.get("context", "").strip()

    if not contact or not context:
        return "I need both a contact name and a context for the call to proceed."

    if player:
        player.write_log(f"[CallControl] Calling {contact}. Context: {context}")

    manager = CallManager()
    result = manager.execute_call(contact, context)

    return result


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="[%(name)s] %(levelname)s: %(message)s")

    print("=" * 65)
    print("AURIX Native Call Controller -- Standalone Test Mode")
    print("Commands:")
    print("  call <Contact Name> | <Vague Context>")
    print("  exit")
    print("=" * 65)

    while True:
        try:
            raw_input = input("\n[Call Control] >>> ").strip()
            if not raw_input or raw_input.lower() in ["exit", "quit"]:
                break

            if raw_input.lower().startswith("call "):
                parts = raw_input[5:].split("|")
                if len(parts) == 2:
                    contact_name = parts[0].strip()
                    call_context = parts[1].strip()
                    print(call_control({"contact": contact_name, "context": call_context}))
                else:
                    print("Format error. Use: call Name | context")
            else:
                print("Unknown command.")

        except KeyboardInterrupt:
            break