import json
import subprocess
import sys
import tempfile
import threading
import ctypes
from pathlib import Path


class RecordingOverlay:
    # This manager launches the tkinter indicator in a separate Python process and updates it through a JSON file.
    def __init__(self):
        self._base_dir = Path(__file__).resolve().parent
        self._ipc_path = Path(tempfile.gettempdir()) / "whispertext_ui_ipc.json"
        self._process = None
        self._state_lock = threading.Lock()
        self._state = {
            "recording": False,
            "stop": False,
            "target_bounds": None,
        }
        self._tracker_stop = threading.Event()
        self._tracker = threading.Thread(target=self._track_target_loop, daemon=True)
        self._write_state()
        self._tracker.start()
        self._start_process()

    def _start_process(self):
        if self._process is not None and self._process.poll() is None:
            return
        script_path = self._base_dir / "indicator_window.py"
        self._process = subprocess.Popen(
            [sys.executable, str(script_path), str(self._ipc_path)],
            cwd=str(self._base_dir),
        )

    def _write_state(self):
        with self._state_lock:
            payload = dict(self._state)
        temp_path = self._ipc_path.with_suffix(".tmp")
        temp_path.write_text(json.dumps(payload), encoding="utf-8")
        temp_path.replace(self._ipc_path)

    def _set_state(self, **changes):
        with self._state_lock:
            self._state.update(changes)
        self._write_state()

    def _track_target_loop(self):
        last_bounds = object()
        while not self._tracker_stop.is_set():
            bounds = self._active_window_bounds()
            if bounds != last_bounds:
                last_bounds = bounds
                self._set_state(target_bounds=bounds)
            self._tracker_stop.wait(0.2)

    def _active_window_bounds(self):
        bounds = _focused_window_bounds()
        if bounds is None:
            return None
        x, y, width, height = bounds
        if width <= 0 or height <= 0:
            return None
        return {
            "x": int(x),
            "y": int(y),
            "width": int(width),
            "height": int(height),
        }

    def set_recording(self, is_recording: bool):
        self._start_process()
        self._set_state(recording=is_recording, stop=False)

    def run(self):
        # The actual UI loop lives in the subprocess, so there is nothing to do here.
        return

    def close(self):
        self._tracker_stop.set()
        self._set_state(recording=False, stop=True)
        if self._process is not None:
            try:
                self._process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                self._process.terminate()
                self._process.wait(timeout=1)
            finally:
                self._process = None


class _CGPoint(ctypes.Structure):
    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]


class _CGSize(ctypes.Structure):
    _fields_ = [("width", ctypes.c_double), ("height", ctypes.c_double)]


_APP_SERVICES = ctypes.cdll.LoadLibrary(
    "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices"
)
_CORE_FOUNDATION = ctypes.cdll.LoadLibrary(
    "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"
)

_APP_SERVICES.AXUIElementCreateSystemWide.restype = ctypes.c_void_p
_APP_SERVICES.AXUIElementCopyAttributeValue.restype = ctypes.c_int
_APP_SERVICES.AXUIElementCopyAttributeValue.argtypes = [
    ctypes.c_void_p,
    ctypes.c_void_p,
    ctypes.POINTER(ctypes.c_void_p),
]
_APP_SERVICES.AXValueGetValue.restype = ctypes.c_bool
_APP_SERVICES.AXValueGetValue.argtypes = [
    ctypes.c_void_p,
    ctypes.c_uint32,
    ctypes.c_void_p,
]
_CORE_FOUNDATION.CFStringCreateWithCString.restype = ctypes.c_void_p
_CORE_FOUNDATION.CFStringCreateWithCString.argtypes = [
    ctypes.c_void_p,
    ctypes.c_char_p,
    ctypes.c_uint32,
]
_CORE_FOUNDATION.CFRelease.argtypes = [ctypes.c_void_p]

_K_CFSTRING_ENCODING_UTF8 = 0x08000100
_K_AX_VALUE_CGPOINT_TYPE = 1
_K_AX_VALUE_CGSIZE_TYPE = 2
_AX_ERROR_SUCCESS = 0
_AX_KEYS = {
    name: _CORE_FOUNDATION.CFStringCreateWithCString(
        None,
        name.encode("utf-8"),
        _K_CFSTRING_ENCODING_UTF8,
    )
    for name in ("AXFocusedApplication", "AXFocusedWindow", "AXPosition", "AXSize")
}


def _copy_ax_value(element, attribute_name):
    value = ctypes.c_void_p()
    error = _APP_SERVICES.AXUIElementCopyAttributeValue(
        element,
        _AX_KEYS[attribute_name],
        ctypes.byref(value),
    )
    if error != _AX_ERROR_SUCCESS or not value.value:
        return None
    return value


def _focused_window_bounds():
    system = _APP_SERVICES.AXUIElementCreateSystemWide()
    focused_app = _copy_ax_value(system, "AXFocusedApplication")
    if focused_app is None:
        return None
    try:
        focused_window = _copy_ax_value(focused_app, "AXFocusedWindow")
        if focused_window is None:
            return None
        try:
            position_value = _copy_ax_value(focused_window, "AXPosition")
            size_value = _copy_ax_value(focused_window, "AXSize")
            if position_value is None or size_value is None:
                return None
            try:
                position = _CGPoint()
                size = _CGSize()
                if not _APP_SERVICES.AXValueGetValue(
                    position_value,
                    _K_AX_VALUE_CGPOINT_TYPE,
                    ctypes.byref(position),
                ):
                    return None
                if not _APP_SERVICES.AXValueGetValue(
                    size_value,
                    _K_AX_VALUE_CGSIZE_TYPE,
                    ctypes.byref(size),
                ):
                    return None
                return position.x, position.y, size.width, size.height
            finally:
                _CORE_FOUNDATION.CFRelease(position_value)
                _CORE_FOUNDATION.CFRelease(size_value)
        finally:
            _CORE_FOUNDATION.CFRelease(focused_window)
    finally:
        _CORE_FOUNDATION.CFRelease(focused_app)
