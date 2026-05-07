import queue
import threading
from pathlib import Path
from recorder import AudioRecorder
from overlay import RecordingOverlay
from transcriber import Transcriber
from pynput import keyboard
import subprocess



class HoldToRecordApp:
    def __init__(self, hotkey: str = "f8"):
        self.recorder = AudioRecorder()
        self.overlay = RecordingOverlay()
        self.transcriber = Transcriber()
        self._base_dir = Path(__file__).resolve().parent
        # Convert a string like `"f8"` or `"cmd+shift+x"` into the concrete key objects `pynput` emits.
        self._hotkey = self._parse_hotkey(hotkey)
        # `_pressed` tracks which keys are currently being held down.
        self._pressed: set[object] = set()
        self._is_recording = False
        # `_jobs` queues finished audio buffers for the transcription worker.
        self._jobs: queue.Queue = queue.Queue()
        # `_worker` runs `_worker_loop` in the background so transcription does not block keyboard handling.
        self._worker = threading.Thread(target=self._worker_loop, daemon=True)
        # Start the background transcription thread immediately.
        self._worker.start()
        # `pynput` runs the global key listener in its own thread so the overlay can keep the main thread.
        self._listener = keyboard.Listener(
            on_press=self._on_press,
            on_release=self._on_release,
        )

    def _parse_hotkey(self, hotkey: str) -> set[object]:
        # `aliases` maps human-friendly names to the special key constants `pynput` uses.
        aliases = {
            "ctrl": keyboard.Key.ctrl,
            "ctrl_l": keyboard.Key.ctrl_l,
            "ctrl_r": keyboard.Key.ctrl_r,
            "alt": keyboard.Key.alt,
            "alt_l": keyboard.Key.alt_l,
            "alt_r": keyboard.Key.alt_r,
            "shift": keyboard.Key.shift,
            "shift_l": keyboard.Key.shift_l,
            "shift_r": keyboard.Key.shift_r,
            "cmd": keyboard.Key.cmd,
            "cmd_l": keyboard.Key.cmd_l,
            "cmd_r": keyboard.Key.cmd_r,
            "option": keyboard.Key.alt,
            "space": keyboard.Key.space,
        }

        # `parsed` will become the set of keys that must all be held at once for the hotkey to match.
        parsed: set[object] = set()
        for part in hotkey.lower().split("+"):
            key_name = part.strip()
            if not key_name:
                continue
            if key_name in aliases:
                parsed.add(aliases[key_name])
            # If this looks like a function key such as `f8`, fetch `keyboard.Key.f8`.
            elif key_name.startswith("f") and key_name[1:].isdigit():
                parsed.add(getattr(keyboard.Key, key_name))
            # If it is a single character like `x`, convert it into a `KeyCode`.
            elif len(key_name) == 1:
                parsed.add(keyboard.KeyCode.from_char(key_name))
            else:
                raise ValueError(f"Unsupported hotkey part: {part}")

        if not parsed:
            raise ValueError("Hotkey cannot be empty")
        return parsed

    def _canonical(self, key):
        if isinstance(key, keyboard.KeyCode) and key.char:
            return keyboard.KeyCode.from_char(key.char.lower())
        return key

    def _matches_hotkey(self) -> bool:
        return self._hotkey.issubset(self._pressed)

    def _worker_loop(self):
        while True:
            audio = self._jobs.get()
            if audio is None:
                break
            try:
                self.transcriber.transcribe(audio)
            finally:
                self._jobs.task_done()

    def _play_sound(self, filename: str):
        sound_path = self._base_dir / filename
        if not sound_path.exists():
            print(f"Sound file not found: {sound_path}")
            return
        try:
            subprocess.run(["afplay", str(sound_path)], check=True)
        except subprocess.CalledProcessError as exc:
            print(f"Failed to play sound {sound_path.name}: {exc}")

    def _start_recording(self):
        if self._is_recording:
            return
        self._is_recording = True
        # Light the overlay before starting the mic so the user sees immediate feedback.
        self.overlay.set_recording(True)
        self._play_sound("play-sound.mp3")
        self.recorder.start()

    def _stop_recording(self):
        if not self._is_recording:
            return
        self._is_recording = False
        # Dim the overlay as soon as recording stops.
        self.overlay.set_recording(False)
        audio = self.recorder.stop()
        self._play_sound("stop-sound.mp3")
        if audio is not None and audio.size > 0:
            self._jobs.put(audio)

    def _on_press(self, key):
        self._pressed.add(self._canonical(key))
        if self._matches_hotkey():
            self._start_recording()

    def _on_release(self, key):
        canonical = self._canonical(key)
        if canonical in self._pressed:
            self._pressed.remove(canonical)
        if self._is_recording and not self._matches_hotkey():
            self._stop_recording()

    def run(self):
        print("Hold the hotkey to record, release to transcribe.")
        print("Press Ctrl+C in this terminal to exit.")
        print("A small red overlay bar will light up while recording.")
        # Start the hotkey listener; the overlay now lives in a separate process.
        self._listener.start()
        try:
            self._listener.join()
        except KeyboardInterrupt:
            pass
        finally:
            self._listener.stop()
            self._listener.join(0.5)

    def close(self):
        self._stop_recording()
        # Send the shutdown sentinel to the worker thread.
        self._jobs.put(None)
        self.recorder.close()
        self.transcriber.close()
        self.overlay.close()
