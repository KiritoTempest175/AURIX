// ─────────────────────────────────────────────────────────────────────────────
// core_engine/src/observers/uia_tree.rs
// ─────────────────────────────────────────────────────────────────────────────
// Windows UI Accessibility Observer — captures the focused UI element tree.
//
// This module wraps the Windows UI Automation (UIA) COM API via the
// `uiautomation` crate.  It provides a `UIATreeObserver` PyO3 class that
// Python can instantiate and poll to discover what application, control,
// and screen region currently has keyboard focus.
//
// The telemetry pipeline feeds this data into the semantic compiler
// (`data_pipeline/compiler/semantic_parser.py`) which correlates UI state
// with terminal output to produce grounded training examples.
//
// Blueprint invariant: All observation is local, read-only, and requires
// no network sockets — the UIA COM interface is an in-process call.
// ─────────────────────────────────────────────────────────────────────────────

use pyo3::prelude::*;
use uiautomation::UIAutomation;
use serde::Serialize;

// ─── UIA Node Data Transfer Object ──────────────────────────────────────────
// A lightweight struct capturing one UI element's identifying properties.
// Serialized to JSON for the Python side.
// ─────────────────────────────────────────────────────────────────────────────

/// A node in the Windows Accessibility tree, representing a single UI element.
///
/// Fields:
/// - `name`:  The human-readable label of the element (e.g., "Save" button).
/// - `control_type`:  The UIA control type as a debug string (e.g., "Button").
/// - `class_name`:  The Win32 window class name (e.g., "Chrome_WidgetWin_1").
/// - `is_focused`:  Whether this element currently holds keyboard focus.
/// - `bounding_rect`:  Screen coordinates as `(left, top, right, bottom)`.
/// - `automation_id`:  The developer-assigned automation ID, if any.
#[derive(Serialize, Debug, Clone)]
pub struct UiaNode {
    pub name: String,
    pub control_type: String,
    pub class_name: String,
    pub is_focused: bool,
    pub bounding_rect: Option<(i32, i32, i32, i32)>,
    pub automation_id: String,
}

// ─── Legacy PyFunction Export ───────────────────────────────────────────────
// Kept for backward compatibility with existing Python code that calls
// `aurix_core.get_focused_element_info()` as a free function.
// ─────────────────────────────────────────────────────────────────────────────

/// Fetch the currently focused UI element as a JSON string.
///
/// Returns `"{}"` if no element can be retrieved (e.g., locked desktop).
#[pyfunction]
pub fn get_focused_element_info() -> PyResult<String> {
    let observer = UIATreeObserver::new();
    observer.capture_focused_element()
}

// ─── UIATreeObserver PyClass ────────────────────────────────────────────────
// A stateful observer that Python can hold across multiple poll cycles.
// ─────────────────────────────────────────────────────────────────────────────

/// Windows UI Automation observer for capturing focused element data.
///
/// # Usage from Python
/// ```python
/// from aurix_core import UIATreeObserver
///
/// observer = UIATreeObserver()
/// json_data = observer.capture_focused_element()
/// print(json_data)
/// ```
///
/// Each call to `capture_focused_element()` performs a fresh COM query.
/// The observer itself is lightweight (~0 bytes of heap state) and can be
/// created once and reused for the lifetime of the agent.
#[pyclass]
#[derive(Clone)]
pub struct UIATreeObserver {
    // Currently stateless — the UIAutomation COM handle is created per-call
    // because COM apartment threading constraints make it unsafe to cache
    // across thread boundaries.  If profiling shows this is a bottleneck
    // we can add thread-local caching later.
    _private: (),
}

#[pymethods]
impl UIATreeObserver {
    /// Create a new UIATreeObserver instance.
    #[new]
    pub fn new() -> Self {
        UIATreeObserver { _private: () }
    }

    /// Capture the currently focused UI element and return its properties
    /// as a JSON-serialized string.
    ///
    /// The returned JSON has the shape:
    /// ```json
    /// {
    ///   "name": "File",
    ///   "control_type": "MenuItem",
    ///   "class_name": "MenuItemView",
    ///   "is_focused": true,
    ///   "bounding_rect": [120, 30, 180, 55],
    ///   "automation_id": "file-menu"
    /// }
    /// ```
    ///
    /// Returns `"{}"` if no focused element is available.
    pub fn capture_focused_element(&self) -> PyResult<String> {
        // Initialise the UIAutomation COM wrapper.
        // This creates a new COM apartment-threaded instance.
        let automation = UIAutomation::new().map_err(|e| {
            pyo3::exceptions::PyRuntimeError::new_err(format!(
                "Failed to initialise Windows UI Automation: {}",
                e
            ))
        })?;

        // Query the element that currently holds keyboard focus.
        match automation.get_focused_element() {
            Ok(element) => {
                // ── Extract element properties ───────────────────────────
                // Each getter can independently fail (e.g., if the element
                // is destroyed between our query and the property read),
                // so we provide safe fallbacks.

                let name = element
                    .get_name()
                    .unwrap_or_else(|_| String::from("Unknown"));

                let control_type = element
                    .get_control_type()
                    .map(|ct| format!("{:?}", ct))
                    .unwrap_or_else(|_| String::from("Unknown"));

                let class_name = element
                    .get_classname()
                    .unwrap_or_else(|_| String::from("Unknown"));

                let automation_id = element
                    .get_automation_id()
                    .unwrap_or_else(|_| String::new());

                // Bounding rectangle: screen-space pixel coordinates.
                let bounding_rect = element.get_bounding_rectangle().ok().map(|r| {
                    (
                        r.get_left(),
                        r.get_top(),
                        r.get_right(),
                        r.get_bottom(),
                    )
                });

                let node = UiaNode {
                    name,
                    control_type,
                    class_name,
                    is_focused: true, // Tautologically true: we queried the focused element.
                    bounding_rect,
                    automation_id,
                };

                // Serialize to compact JSON for the Python pipeline.
                let json_str = serde_json::to_string(&node)
                    .unwrap_or_else(|_| "{}".to_string());

                Ok(json_str)
            }
            Err(_) => {
                // No focused element available — return empty JSON object.
                // This can happen if the desktop is locked or no window
                // has focus.
                Ok("{}".to_string())
            }
        }
    }

    /// Python `__repr__` for debugging.
    fn __repr__(&self) -> String {
        "UIATreeObserver()".to_string()
    }
}

impl Default for UIATreeObserver {
    fn default() -> Self {
        Self::new()
    }
}
