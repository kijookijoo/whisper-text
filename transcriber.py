from faster_whisper import WhisperModel
from faster_whisper import transcribe as fw_transcribe
import numpy as np
import pyperclip
import subprocess


class _DisabledProgressBar:
    # `faster-whisper` expects the progress object to have an `update()` method, so this no-op method matches that API.
    def update(self, *_args, **_kwargs):
        return None

    # `faster-whisper` also calls `close()`, so we provide the same method and do nothing.
    def close(self):
        return None


# Save the original `tqdm` function so we can still call it when progress bars are actually enabled.
_REAL_TQDM = fw_transcribe.tqdm


def _safe_tqdm(*args, **kwargs):
    # When progress is disabled, return our no-op object instead of constructing a real `tqdm` progress bar.
    if kwargs.get("disable", False):
        return _DisabledProgressBar()
    # Otherwise keep the library's original behavior.
    return _REAL_TQDM(*args, **kwargs)


# Replace `faster-whisper`'s internal `tqdm` reference with our wrapper.
fw_transcribe.tqdm = _safe_tqdm

class Transcriber:
    def __init__(self):
        self.model = WhisperModel("base", device="cpu", compute_type="int8")

    def _paste_clipboard(self):
        script = 'tell application "System Events" to keystroke "v" using command down'
        subprocess.run(["osascript", "-e", script], check=True)

    def transcribe(self, input: np.ndarray):
        audio = np.asarray(input, dtype=np.float32).reshape(-1)
        segments,info = self.model.transcribe(audio, beam_size=5)
        # `segments` is an iterator of transcribed chunks, so print each chunk line by line.
        texts = []
        for segment in segments:
            print(f"Duration: [{segment.start:.2f} -> {segment.end:.2f}]")
            texts.append(segment.text.strip())
        full_text = " ".join(texts).strip()
        print(full_text)
        pyperclip.copy(full_text)
        try:
            self._paste_clipboard()
        except subprocess.CalledProcessError as exc:
            print(f"Paste failed: {exc}")
    def close(self):
        self.model.model.unload_model()
