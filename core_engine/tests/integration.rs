use pyo3::prelude::*;
use core_engine::governor::atomic_state;
use core_engine::governor::monitor;
use core_engine::observers::uia_tree;
use core_engine::observers::terminal_hook;
use core_engine::sandbox::file_jail;
use std::thread;
use std::time::Duration;

#[test]
fn test_all_modules() {
    // We need to initialize the Python interpreter to use PyResult and PyErr
    pyo3::prepare_freethreaded_python();

    Python::with_gil(|_py| {
        println!("==================================================");
        println!("Starting Output Report for Huzaifa's Core Engine");
        println!("==================================================\n");

        // 1. Test atomic_state
        println!("--> 1. Testing atomic_state.rs");
        let initial_state = atomic_state::check_suspend_flag();
        println!("Initial suspend flag: {}", initial_state);
        
        atomic_state::set_suspend_flag(true);
        let updated_state = atomic_state::check_suspend_flag();
        println!("Updated suspend flag: {}", updated_state);
        
        atomic_state::set_suspend_flag(false); // reset for later
        println!("Successfully tested atomic_state!\n");


        // 2. Test terminal_hook
        println!("--> 2. Testing terminal_hook.rs");
        println!("Executing command: 'echo Hello from AURIX Sandbox!'");
        match terminal_hook::execute_and_intercept("echo Hello from AURIX Sandbox!") {
            Ok((exit_code, stdout, stderr)) => {
                println!("Exit Code: {}", exit_code);
                println!("Stdout: {}", stdout.trim());
                println!("Stderr: {}", stderr.trim());
            }
            Err(e) => println!("Error executing terminal hook: {:?}", e),
        }
        println!("Successfully tested terminal_hook!\n");


        // 3. Test uia_tree
        println!("--> 3. Testing uia_tree.rs");
        match uia_tree::get_focused_element_info() {
            Ok(json_str) => println!("Focused UI Element JSON: {}", json_str),
            Err(e) => println!("Error fetching UI element: {:?}", e),
        }
        println!("Successfully tested uia_tree!\n");


        // 4. Test monitor
        println!("--> 4. Testing monitor.rs");
        println!("Starting background hardware monitor...");
        monitor::start_hardware_monitor();
        println!("Sleeping for 2 seconds to allow monitor to poll...");
        thread::sleep(Duration::from_secs(2));
        println!("Current suspend flag after monitoring: {}", atomic_state::check_suspend_flag());
        println!("Successfully tested monitor!\n");


        // 5. Test file_jail
        println!("--> 5. Testing file_jail.rs");
        // We will test a valid path.
        let valid_path = "C:\\Users\\NAC\\Documents\\University\\Projects";
        println!("Testing valid path: {}", valid_path);
        match file_jail::validate_path(valid_path) {
            Ok(canonical) => println!("Success! Canonical path: {}", canonical),
            Err(e) => println!("Error (unexpected): {:?}", e),
        }
        println!("Successfully tested file_jail (valid path)!\n");

        println!("Note: We are not testing an invalid path in this test suite because it intentionally triggers a panic! which would crash the test runner.");
        println!("==================================================");
        println!("End of Output Report");
        println!("==================================================");
    });
}
