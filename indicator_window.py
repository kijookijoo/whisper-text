#!/usr/bin/env python3

import ctypes
import ctypes.util
import json
import math
import random
import sys
import tkinter as tk
from pathlib import Path
from tkinter import Canvas


IPC_FILE = Path(sys.argv[1])


class _CGPoint(ctypes.Structure):
    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]


class _CGSize(ctypes.Structure):
    _fields_ = [("width", ctypes.c_double), ("height", ctypes.c_double)]


class _CGRect(ctypes.Structure):
    _fields_ = [("origin", _CGPoint), ("size", _CGSize)]


class WaveformWindow:
    # This is a tiny floating tkinter window that reads recording state from a JSON file.
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Recording Indicator")

        self.width = 260
        self.height = 64
        self.recording = False
        self._frame = 0
        self._phase_offsets = [random.uniform(0.0, math.tau) for _ in range(25)]
        self._last_target_bounds = None
        self._current_screen = None
        self._anchor_offset_x = 0
        self._anchor_offset_y = 0
        self._drag_start_pointer = None
        self._drag_start_window = None

        # Start hidden so geometry and macOS window flags are applied before the window is shown.
        self.root.withdraw()
        self.root.overrideredirect(True)
        self.root.attributes("-alpha", 0.94)
        self.root.attributes("-topmost", True)
        self.root.resizable(False, False)
        self.root.configure(bg="#000000")

        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        x = (screen_w - self.width) // 2
        y = screen_h - self.height - 60
        self.root.geometry(f"{self.width}x{self.height}+{x}+{y}")

        self.canvas = Canvas(
            self.root,
            width=self.width,
            height=self.height,
            bg="#000000",
            highlightthickness=0,
            bd=0,
        )
        self.canvas.pack()
        self.canvas.bind("<ButtonPress-1>", self._start_drag)
        self.canvas.bind("<B1-Motion>", self._drag)
        self.canvas.bind("<ButtonRelease-1>", self._end_drag)

        # Dense bar layout similar to the waveform style you pasted.
        self.levels = [0.0] * 25
        self.root.update_idletasks()
        self._configure_macos_window()
        self.root.overrideredirect(False)
        self.root.overrideredirect(True)
        self.root.deiconify()
        self.root.lift()
        self.root.after(200, lambda: self.root.attributes("-topmost", True))

        self.update()

    def update(self):
        try:
            if IPC_FILE.exists():
                data = json.loads(IPC_FILE.read_text(encoding="utf-8"))
                if data.get("stop"):
                    self.root.quit()
                    return
                self.recording = data.get("recording", False)
                if self.recording:
                    self.levels = self._animated_levels()
                else:
                    self.levels = [0.0] * 25
                self._apply_target_bounds(data.get("target_bounds"))
                self.draw_waveform()
        except Exception:
            # Ignore transient IPC read errors and try again on the next frame.
            pass

        self._frame += 1
        self.root.after(33, self.update)

    def _animated_levels(self):
        # Build a moving waveform so the overlay looks alive while recording.
        t = self._frame / 8
        levels = []
        center_bias = (len(self._phase_offsets) - 1) / 2
        for i, phase in enumerate(self._phase_offsets):
            distance_from_center = abs(i - center_bias) / center_bias
            center_gain = 1.0 - (distance_from_center * 0.45)
            wave = (
                math.sin(t + phase) * 0.45
                + math.sin((t * 1.7) - phase * 0.6) * 0.25
                + math.sin((t * 0.45) + i * 0.55) * 0.2
            )
            level = max(0.12, min(1.0, (wave + 1) * 0.5 * center_gain + 0.12))
            levels.append(level)
        return levels

    def _apply_target_bounds(self, bounds):
        if not bounds or bounds == self._last_target_bounds:
            return
        self._last_target_bounds = bounds
        screen = _screen_frame_for_target(bounds)
        if screen is None:
            x = bounds["x"]
            y = bounds["y"]
            width = bounds["width"]
            height = bounds["height"]
        else:
            self._current_screen = screen
            x = screen["x"]
            y = screen["y"]
            width = screen["width"]
            height = screen["height"]
        anchor_x = x + max(0, (width - self.width) // 2)
        anchor_y = y + max(24, height - self.height - 48)
        self._move_window(anchor_x + self._anchor_offset_x, anchor_y + self._anchor_offset_y)
        self.root.lift()
        self.root.after(50, lambda: self.root.attributes("-topmost", True))

    def _move_window(self, x, y):
        self.root.geometry(f"{self.width}x{self.height}+{int(x)}+{int(y)}")

    def _start_drag(self, _event):
        self._drag_start_pointer = (self.root.winfo_pointerx(), self.root.winfo_pointery())
        self._drag_start_window = (self.root.winfo_x(), self.root.winfo_y())

    def _drag(self, _event):
        if self._drag_start_pointer is None or self._drag_start_window is None:
            return
        pointer_x, pointer_y = self.root.winfo_pointerx(), self.root.winfo_pointery()
        start_pointer_x, start_pointer_y = self._drag_start_pointer
        start_window_x, start_window_y = self._drag_start_window
        self._move_window(
            start_window_x + (pointer_x - start_pointer_x),
            start_window_y + (pointer_y - start_pointer_y),
        )

    def _end_drag(self, _event):
        if self._drag_start_pointer is None or self._drag_start_window is None:
            return
        if self._current_screen is not None:
            anchor_x = self._current_screen["x"] + max(0, (self._current_screen["width"] - self.width) // 2)
            anchor_y = self._current_screen["y"] + max(24, self._current_screen["height"] - self.height - 48)
            self._anchor_offset_x = self.root.winfo_x() - anchor_x
            self._anchor_offset_y = self.root.winfo_y() - anchor_y
        self._drag_start_pointer = None
        self._drag_start_window = None

    def _configure_macos_window(self):
        try:
            self.root.tk.call(
                "::tk::unsupported::MacWindowStyle",
                "style",
                self.root._w,
                "help",
                "noActivates",
            )
        except tk.TclError:
            pass
        try:
            _set_window_collection_behavior()
        except Exception:
            pass

    def draw_waveform(self):
        self.canvas.delete("all")
        self.canvas.create_rectangle(0, 0, self.width, self.height, fill="#000000", outline="")

        num_bars = 25
        padding = self.width * 0.07
        usable_width = self.width - (padding * 2)
        bar_spacing = usable_width * 0.02
        total_spacing = bar_spacing * (num_bars - 1)
        bar_width = (usable_width - total_spacing) / num_bars
        start_x = padding
        center_y = self.height / 2

        if self.recording:
            outline = "#ff6a6a"
            self.canvas.create_rectangle(
                6,
                6,
                self.width - 6,
                self.height - 6,
                fill="#170404",
                outline=outline,
                width=1,
            )
            for i in range(num_bars):
                level = self.levels[i] if i < len(self.levels) else 0.0
                x = start_x + i * (bar_width + bar_spacing)
                min_height = max(4, self.height * 0.18)
                bar_height = max(min_height, level * self.height * 0.68)
                bar_height = min(bar_height, self.height * 0.76)
                y1 = center_y - bar_height / 2
                y2 = center_y + bar_height / 2
                glow_pad = 2
                self.canvas.create_rectangle(
                    x - glow_pad,
                    y1 - glow_pad,
                    x + bar_width + glow_pad,
                    y2 + glow_pad,
                    fill="#662020",
                    outline="",
                )
                self.canvas.create_rectangle(
                    x, y1, x + bar_width, y2,
                    fill="#ff3b30",
                    outline=""
                )
        else:
            outline = "#3d2424"
            self.canvas.create_rectangle(
                6,
                6,
                self.width - 6,
                self.height - 6,
                fill="#090909",
                outline=outline,
                width=1,
            )
            min_height = max(3, self.height * 0.12)
            for i in range(num_bars):
                x = start_x + i * (bar_width + bar_spacing)
                self.canvas.create_rectangle(
                    x, center_y - min_height / 2, x + bar_width, center_y + min_height / 2,
                    fill="#452626", outline=""
                )

    def run(self):
        self.root.mainloop()


def main():
    window = WaveformWindow()
    window.run()


_LIBOBJC = ctypes.cdll.LoadLibrary(ctypes.util.find_library("objc"))
ctypes.cdll.LoadLibrary("/System/Library/Frameworks/AppKit.framework/AppKit")
_CORE_GRAPHICS = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")

_LIBOBJC.objc_getClass.restype = ctypes.c_void_p
_LIBOBJC.objc_getClass.argtypes = [ctypes.c_char_p]
_LIBOBJC.sel_registerName.restype = ctypes.c_void_p
_LIBOBJC.sel_registerName.argtypes = [ctypes.c_char_p]

_CORE_GRAPHICS.CGGetActiveDisplayList.restype = ctypes.c_int32
_CORE_GRAPHICS.CGGetActiveDisplayList.argtypes = [
    ctypes.c_uint32,
    ctypes.POINTER(ctypes.c_uint32),
    ctypes.POINTER(ctypes.c_uint32),
]
_CORE_GRAPHICS.CGDisplayBounds.restype = _CGRect
_CORE_GRAPHICS.CGDisplayBounds.argtypes = [ctypes.c_uint32]

_NS_WINDOW_COLLECTION_BEHAVIOR_CAN_JOIN_ALL_SPACES = 1 << 0
_NS_WINDOW_COLLECTION_BEHAVIOR_MOVE_TO_ACTIVE_SPACE = 1 << 1
_NS_WINDOW_COLLECTION_BEHAVIOR_FULL_SCREEN_AUXILIARY = 1 << 8


def _objc_send(receiver, selector, *args, restype=ctypes.c_void_p, argtypes=None):
    msg_send = _LIBOBJC.objc_msgSend
    msg_send.restype = restype
    msg_send.argtypes = [ctypes.c_void_p, ctypes.c_void_p] + (argtypes or [])
    return msg_send(
        receiver,
        _LIBOBJC.sel_registerName(selector.encode("utf-8")),
        *args,
    )


def _set_window_collection_behavior():
    ns_application = _LIBOBJC.objc_getClass(b"NSApplication")
    app = _objc_send(ns_application, "sharedApplication")
    if not app:
        return
    windows = _objc_send(app, "windows")
    if not windows:
        return
    count = _objc_send(windows, "count", restype=ctypes.c_ulong)
    if count == 0:
        return
    window = _objc_send(
        windows,
        "objectAtIndex:",
        0,
        restype=ctypes.c_void_p,
        argtypes=[ctypes.c_ulong],
    )
    if not window:
        return
    behavior = _objc_send(
        window,
        "collectionBehavior",
        restype=ctypes.c_ulonglong,
    )
    behavior &= ~_NS_WINDOW_COLLECTION_BEHAVIOR_CAN_JOIN_ALL_SPACES
    behavior |= _NS_WINDOW_COLLECTION_BEHAVIOR_MOVE_TO_ACTIVE_SPACE
    behavior |= _NS_WINDOW_COLLECTION_BEHAVIOR_FULL_SCREEN_AUXILIARY
    _objc_send(
        window,
        "setCollectionBehavior:",
        behavior,
        restype=None,
        argtypes=[ctypes.c_ulonglong],
    )


def _screen_frame_for_target(bounds):
    midpoint_x = bounds["x"] + (bounds["width"] / 2)
    midpoint_y = bounds["y"] + (bounds["height"] / 2)
    max_displays = 16
    active_displays = (ctypes.c_uint32 * max_displays)()
    display_count = ctypes.c_uint32()
    error = _CORE_GRAPHICS.CGGetActiveDisplayList(
        max_displays,
        active_displays,
        ctypes.byref(display_count),
    )
    if error != 0:
        return None
    fallback = None
    for index in range(display_count.value):
        rect = _CORE_GRAPHICS.CGDisplayBounds(active_displays[index])
        frame = {
            "x": int(rect.origin.x),
            "y": int(rect.origin.y),
            "width": int(rect.size.width),
            "height": int(rect.size.height),
        }
        if fallback is None:
            fallback = frame
        if (
            frame["x"] <= midpoint_x < frame["x"] + frame["width"]
            and frame["y"] <= midpoint_y < frame["y"] + frame["height"]
        ):
            return frame
    return fallback


if __name__ == "__main__":
    main()
