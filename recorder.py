import sounddevice as sd
import numpy as np
import threading

fs = 16000

class AudioRecorder:
    def __init__(self):
        # `_chunks` stores small NumPy arrays coming from the live microphone stream callback.
        self._chunks: list[np.ndarray] = []
        # `_lock` protects `_chunks` because the callback runs on a different thread from the caller.
        self._lock = threading.Lock()
        # `_stream` will hold the active `sounddevice.InputStream` object while recording is running.
        self._stream = None
        # `_recording` is a simple guard so `start()`/`stop()` can ignore duplicate calls safely.
        self._recording = False

    def _callback(self, indata, _frames, _time, status):
        # `sounddevice` passes a status object if PortAudio noticed an overflow/underflow or similar issue.
        if status:
            print(f"Audio status: {status}")
        # We lock before appending because the callback thread and the stop logic can touch `_chunks` concurrently.
        with self._lock:
            # `indata.copy()` stores a stable copy of the current audio block before `sounddevice` reuses its buffer.
            self._chunks.append(indata.copy())

    def start(self):
        # Ignore repeated start requests if recording is already active.
        if self._recording:
            return
        print("recording...")
        # Reset any old buffered audio so each push-to-talk session starts fresh.
        with self._lock:
            self._chunks = []
        # `InputStream` opens the microphone as a live stream instead of recording a fixed number of seconds.
        self._stream = sd.InputStream(
            # Ask PortAudio for 16 kHz input to match the transcription model.
            samplerate=fs,
            # Use one channel because this app only needs mono speech input.
            channels=1,
            # Store samples as 32-bit floats because that is the format Whisper expects later.
            dtype="float32",
            # `sounddevice` will call `_callback` each time a new audio block arrives from the mic.
            callback=self._callback,
        )
        # Actually begin pulling audio from the microphone.
        self._stream.start()
        # Mark recording as active only after the stream has started successfully.
        self._recording = True

    def stop(self) -> np.ndarray | None:
        # If recording is already stopped, there is nothing to return.
        if not self._recording:
            return None

        # Flip the flag first so any later calls see the recorder as stopped.
        self._recording = False
        # At this point `_stream` must exist because `_recording` was true.
        assert self._stream is not None
        # Stop the live microphone stream so no more callbacks arrive.
        self._stream.stop()
        # Close the PortAudio stream and release the OS audio resource.
        self._stream.close()
        # Drop the reference so the recorder is back in the idle state.
        self._stream = None

        # Lock while reading and clearing `_chunks` so the callback cannot append while we combine the buffers.
        with self._lock:
            # If no chunks were collected, return `None` instead of an empty audio array.
            if not self._chunks:
                print("Done! No audio captured.")
                return None
            # Join all captured blocks into one continuous NumPy array shaped like `(samples, 1)`.
            recording = np.concatenate(self._chunks, axis=0)
            # Clear the internal buffer so old audio is not reused accidentally next time.
            self._chunks = []

        print("Done!")
        # Return the full recorded waveform to the caller.
        return recording

    def close(self):
        # If the app is shutting down while the stream is still open, stop it cleanly.
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        # Make sure the state flag also resets during shutdown.
        self._recording = False
