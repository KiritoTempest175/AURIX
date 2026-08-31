import os
import sys
import time
import datetime
import threading
import queue
import psutil
import slint

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Ensure project root is in python path
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from ai_engine.llm_inference import QwenModelRunner
from data_pipeline.storage.telemetry_daemon import TelemetryIngestionDaemon
from data_pipeline.self_healing.self_healing_hook import SelfHealingHook
from data_pipeline.compiler.semantic_parser import SemanticCompiler


class AurixController:
    """Bridges the AURIX AI Engine, Data Pipeline, and Hardware Telemetry to the Slint GUI."""

    def __init__(self, app):
        self.app = app
        self.start_time = time.time()
        self.cmd_count = 0
        self.response_queue = queue.Queue()

        # Initialize AI Engine & Data Pipeline Core Modules
        print("[AURIX Controller] Initializing Qwen 3:4B Local Inference Engine...")
        self.llm_runner = QwenModelRunner(config_path=os.path.join(ROOT_DIR, "config.toml"))

        print("[AURIX Controller] Initializing Telemetry Ingestion Daemon...")
        db_dir = os.path.join(ROOT_DIR, "databases", "telemetry")
        os.makedirs(db_dir, exist_ok=True)
        self.telemetry = TelemetryIngestionDaemon(db_path=os.path.join(db_dir, "aurix_session.db"))

        print("[AURIX Controller] Initializing Self-Healing Diagnostic Hook...")
        self.self_healing = SelfHealingHook(max_retries=3)

        print("[AURIX Controller] Initializing Semantic Compiler...")
        self.compiler = SemanticCompiler()

        # Bind UI Callbacks
        self._bind_callbacks()

        # Start 1-second Telemetry Timer
        self.timer = slint.Timer()
        self.timer.start(
            slint.TimerMode.Repeated,
            datetime.timedelta(seconds=1),
            self._update_telemetry
        )

        # Start 100ms Queue Poll Timer for AI Responses
        self.poll_timer = slint.Timer()
        self.poll_timer.start(
            slint.TimerMode.Repeated,
            datetime.timedelta(milliseconds=100),
            self._poll_response_queue
        )

        print("✅ [AURIX Controller] All backend subsystems integrated with Frontend UI!")

    def _bind_callbacks(self):
        """Binds Slint GUI events to Python handlers."""
        self.app.send_message = self._handle_send_message
        self.app.clear_conversation = self._handle_clear_conversation
        self.app.export_conversation = self._handle_export_conversation
        self.app.review_approve = self._handle_review_approve
        self.app.review_reject = self._handle_review_reject
        self.app.alert_retry = self._handle_alert_retry
        self.app.alert_cancel = self._handle_alert_cancel
        self.app.alert_close = self._handle_alert_close

    def _get_time_str(self) -> str:
        return datetime.datetime.now().strftime("%H:%M:%S")

    def _handle_send_message(self, text: str):
        if not text.strip():
            return

        now_str = self._get_time_str()
        self.cmd_count += 1
        self.app.commands_count = str(self.cmd_count)

        # 1. Update UI with User Message
        current_msgs = list(self.app.messages)
        current_msgs.append({"sender": "USER", "text": text, "time": now_str})
        self.app.messages = slint.ListModel(current_msgs)

        # 2. Log Execution Telemetry
        try:
            self.telemetry.ingest_execution_log(
                session_id="session_gui",
                action_type="UI_COMMAND",
                target_command=text,
                status="EXECUTING",
                return_code=0
            )
        except Exception as e:
            print(f"⚠️ [Telemetry Error]: {e}")

        # 3. Parameterize if command
        compiled = self.compiler.compile_command(text)
        if compiled.get("default_parameters"):
            print(f"🧩 [Semantic Compiler]: Extracted parameters {compiled['default_parameters']}")

        # 4. Dispatch Async AI Inference Thread
        def generate_job():
            try:
                reply = self.llm_runner.generate(instruction=text)
            except Exception as err:
                reply = f"[Error]: {err}"
            self.response_queue.put((reply, self._get_time_str()))

        threading.Thread(target=generate_job, daemon=True).start()

    def _poll_response_queue(self):
        """Polls queue for async AI response and appends to Slint UI model."""
        while not self.response_queue.empty():
            reply_text, timestamp = self.response_queue.get_nowait()
            current_msgs = list(self.app.messages)
            current_msgs.append({"sender": "AURIX", "text": reply_text, "time": timestamp})
            self.app.messages = slint.ListModel(current_msgs)

    def _handle_clear_conversation(self):
        welcome = {
            "sender": "AURIX",
            "text": "A.U.R.I.X modular dashboard initialized. All subsystems online and ready for your command.",
            "time": self._get_time_str()
        }
        self.app.messages = slint.ListModel([welcome])
        self.app.toast_message = "Conversation history cleared."
        self.app.toast_visible = True

    def _handle_export_conversation(self):
        try:
            log_path = os.path.join(ROOT_DIR, "logs", "chat_export.txt")
            os.makedirs(os.path.dirname(log_path), exist_ok=True)
            with open(log_path, "w", encoding="utf-8") as f:
                for msg in list(self.app.messages):
                    f.write(f"[{msg.time}] {msg.sender}: {msg.text}\n")
            self.app.toast_message = "Saved conversation to logs/chat_export.txt"
            self.app.toast_visible = True
        except Exception as e:
            self.app.toast_message = f"Export failed: {e}"
            self.app.toast_visible = True

    def _handle_review_approve(self):
        print("✔ [Review Card] Action Approved by User")
        self.app.toast_message = "Security Approval Granted"
        self.app.toast_visible = True

    def _handle_review_reject(self):
        print("❌ [Review Card] Action Rejected by User")
        self.app.toast_message = "Security Directive Rejected"
        self.app.toast_visible = True

    def _handle_alert_retry(self):
        print("🔄 [Self-Healing Alert] Retry Action Initiated")

    def _handle_alert_cancel(self):
        print("⏹ [Self-Healing Alert] Action Cancelled")

    def _handle_alert_close(self):
        print("ℹ [Self-Healing Alert] Modal Closed")

    def _update_telemetry(self):
        """Updates real-time system metrics (CPU, RAM, Disk, Load, Uptime) on Slint UI."""
        now = datetime.datetime.now()
        self.app.live_time = now.strftime("%H:%M:%S")

        # Compute Uptime
        uptime_sec = int(time.time() - self.start_time)
        hrs, rem = divmod(uptime_sec, 3600)
        mins, secs = divmod(rem, 60)
        self.app.uptime_display = f"{hrs:02d}:{mins:02d}:{secs:02d}"

        # Real Hardware Metrics
        try:
            cpu_pct = psutil.cpu_percent(interval=None)
            mem = psutil.virtual_memory()
            disk = psutil.disk_usage("/")

            ram_used_gb = mem.used / (1024 ** 3)
            ram_total_gb = mem.total / (1024 ** 3)

            self.app.cpu_usage = cpu_pct / 100.0
            self.app.cpu_display = f"{int(cpu_pct)}%"

            self.app.ram_usage = mem.percent / 100.0
            self.app.ram_display = f"{ram_used_gb:.1f} / {ram_total_gb:.1f} GB"

            self.app.disk_usage = disk.percent / 100.0
            self.app.disk_display = f"{int(disk.percent)}%"

            self.app.system_load = cpu_pct / 100.0
            self.app.system_load_display = f"{int(cpu_pct)}%"

            # Save frame to SQLite telemetry DB
            self.telemetry.ingest_hardware_metrics(
                ram_gb=round(ram_used_gb, 2),
                vram_gb=0.0,
                training_state="NOMINAL"
            )
        except Exception as err:
            pass


def main():
    slint_file = os.path.join(os.path.dirname(__file__), "ui", "main.slint")
    print(f"Loading Slint UI from {slint_file}...")
    ui = slint.load_file(slint_file)
    app = ui.AurixCommandCenter()

    # Instantiate Controller to integrate Python Backend & Slint UI
    controller = AurixController(app)

    print("🚀 Launching A.U.R.I.X Command Center GUI with active Python backend integration...")
    app.run()


if __name__ == "__main__":
    main()
