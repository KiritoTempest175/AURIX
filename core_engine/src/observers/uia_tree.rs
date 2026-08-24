use pyo3::prelude::*;
use uiautomation::UIAutomation;
use serde::Serialize;

/// Represents a node in the Windows Accessibility (UIA) Tree.
/// This data structure is serialized and passed back to the Python telemetry pipeline.
#[derive(Serialize)]
pub struct UiaNode {
    pub name: String,
    pub control_type: String,
    pub is_focused: bool,
    pub bounding_rectangle: Option<(i32, i32, i32, i32)>,
}

/// Fetches the currently focused element from the OS accessibility API.
/// 
/// This is used by the observer daemon to synchronize UI states with 
/// terminal output in the continuous learning pipeline.
#[pyfunction]
pub fn get_focused_element_info() -> PyResult<String> {
    // Initialize the UIAutomation COM wrapper
    let automation = UIAutomation::new().map_err(|e| {
        pyo3::exceptions::PyRuntimeError::new_err(format!("Failed to init UIA: {}", e))
    })?;

    // Attempt to get the element that currently has keyboard focus
    if let Ok(element) = automation.get_focused_element() {
        let name = element.get_name().unwrap_or_else(|_| String::from("Unknown"));
        let control_type = element.get_control_type()
            .map(|t| format!("{:?}", t))
            .unwrap_or_else(|_| String::from("Unknown"));
        
        let rect_opt = element.get_bounding_rectangle().ok();
        let bounding_rectangle = rect_opt.map(|r| (r.get_left(), r.get_top(), r.get_right(), r.get_bottom()));

        let node = UiaNode {
            name,
            control_type,
            is_focused: true, // Inherently true since we queried focused element
            bounding_rectangle,
        };

        // Serialize to JSON string for easy parsing on the Python side
        let json_str = serde_json::to_string(&node).unwrap_or_else(|_| "{}".to_string());
        Ok(json_str)
    } else {
        Ok("{}".to_string())
    }
}
