"""Unified Python Test Runner for LUNA Subsystems."""

import os
import sys
import unittest

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from tests.python.test_gemma_model import (
    test_gemma_runner_initialization,
    test_gemma_runner_effective_params_toggle,
    test_gemma_chat_prompt_formatting,
    test_gemma_fallback_generation,
)
from tests.python.test_checkpoint_manager import (
    test_checkpoint_save_and_load_roundtrip,
    test_checkpoint_load_without_extra_state,
    test_checkpoint_automatic_rollback_on_corruption,
    test_load_checkpoint_by_id_success,
    test_load_checkpoint_by_id_failure,
    get_temp_ckpt_dir,
)
from tests.python.test_secret_scrubber import (
    test_secret_scrubber_api_keys,
    test_secret_scrubber_private_keys,
    test_secret_scrubber_password_parameters,
    test_secret_scrubber_dict,
)
from tests.python.test_permissions import (
    test_permission_manager_requires_trust_token,
    test_permission_manager_token_issuance_and_consumption,
    test_permission_manager_rejects_mismatched_resource,
)
from tests.python.test_data_pipeline import (
    test_telemetry_ingestion_and_secret_scrubbing,
    test_self_healing_traceback_parser,
    test_self_healing_max_retries_ceiling,
    get_temp_db_path,
)
from tests.python.test_synthetic_generator import (
    test_training_weights_loaded_from_config,
    test_synthetic_general_source_tagging,
    test_synthetic_general_zero_project_file_reads,
    test_fail_closed_governor_gating,
    test_live_generation_path_with_mock_gemma_runner,
    test_live_generation_fallback_on_model_exception,
    test_replay_buffer_weights_from_config,
    test_replay_buffer_sampling_rebalance,
    test_dynamic_loader_supports_synthetic_general,
    test_student_controller_wires_synthetic_generator_and_power_query,
)


class LunaTestSuite(unittest.TestCase):
    """Test case executing all subsystem unit and integration tests."""

    def test_gemma_suite(self):
        test_gemma_runner_initialization()
        test_gemma_runner_effective_params_toggle()
        test_gemma_chat_prompt_formatting()
        test_gemma_fallback_generation()

    def test_checkpoint_suite(self):
        with get_temp_ckpt_dir() as d:
            test_checkpoint_save_and_load_roundtrip(d)
            test_checkpoint_load_without_extra_state(d)
            test_checkpoint_automatic_rollback_on_corruption(d)
            test_load_checkpoint_by_id_success(d)
            test_load_checkpoint_by_id_failure(d)

    def test_security_scrubber_suite(self):
        test_secret_scrubber_api_keys()
        test_secret_scrubber_private_keys()
        test_secret_scrubber_password_parameters()
        test_secret_scrubber_dict()

    def test_permissions_suite(self):
        test_permission_manager_requires_trust_token()
        test_permission_manager_token_issuance_and_consumption()
        test_permission_manager_rejects_mismatched_resource()

    def test_data_pipeline_suite(self):
        with get_temp_db_path() as db_file:
            test_telemetry_ingestion_and_secret_scrubbing(db_file)
            test_self_healing_traceback_parser()
            test_self_healing_max_retries_ceiling()

    def test_synthetic_generator_suite(self):
        test_training_weights_loaded_from_config()
        test_synthetic_general_source_tagging()
        test_synthetic_general_zero_project_file_reads()
        test_fail_closed_governor_gating()
        test_live_generation_path_with_mock_gemma_runner()
        test_live_generation_fallback_on_model_exception()
        test_replay_buffer_weights_from_config()
        test_replay_buffer_sampling_rebalance()
        test_dynamic_loader_supports_synthetic_general()
        test_student_controller_wires_synthetic_generator_and_power_query()


if __name__ == "__main__":
    unittest.main(verbosity=2)
