"""The production training controller cannot pretend to train."""
from ai_engine.training.student_qlora_loop import StudentTrainingController


def test_training_refuses_active_workstation():
    controller = StudentTrainingController(get_power_state_fn=lambda: 0)
    assert controller.start_training() is False
    assert controller.get_status()["is_running"] is False
    assert controller.get_status()["current_loss"] is None
    assert "IDLE" in controller.get_status()["last_error"]


def test_no_mock_checkpoint_loop():
    controller = StudentTrainingController(get_power_state_fn=lambda: 0)
    assert controller.get_status()["current_step"] is None
    assert controller.stop_training() is False
