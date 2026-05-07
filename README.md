# WhisperText

WhisperText is a macOS push-to-talk transcription tool.

It stays running in the background, listens for a global hotkey, records from the microphone while the hotkey is held, transcribes speech locally with `faster-whisper`, copies the result to the clipboard, and pastes it into the currently focused app.

It also keeps a small floating waveform overlay visible while the process is running so you can see recording state without switching back to the terminal.

## What It Does

- Hold a global hotkey to start recording.
- Release the hotkey to stop recording and queue the audio for transcription.
- Run Whisper locally on the recorded audio.
- Copy the final text to the clipboard.
- Attempt to paste the text into the active field with a synthetic `Cmd+V`.
- Show a floating borderless overlay that follows the active display/Space.
- Let the user drag the overlay to adjust its position.

## Why This Exists

The goal is speed.

This is not a batch transcription app and not a full dictation product. It is a narrow tool for short speech-to-text bursts while you are already working somewhere else: an editor, terminal, browser, chat app, or AI assistant.

## Runtime Model

The app is long-running. You start it once:

```bash
python3 main.py
```

Then it keeps running until interrupted.

Default hotkey:

- `Ctrl+Shift`

Behavior:

1. Press and hold the hotkey.
2. Speak.
3. Release the hotkey.
4. The app transcribes the captured audio.
5. The text is copied and pasted into the active app.

## macOS Requirements

This project is macOS-specific in its current form.

It depends on:

- `pynput` for global hotkeys
- `sounddevice` for microphone capture
- `faster-whisper` for local transcription
- `tkinter` for the floating overlay
- macOS Accessibility APIs for active-window tracking and synthetic paste
- `afplay` for start/stop sounds

You will likely need to grant Accessibility permission to the terminal app that launches WhisperText so it can:

- monitor global keyboard input
- inspect the focused window
- send paste keystrokes

## High-Level Architecture

The app is split into a few small components with clear responsibilities.

### `main.py`

Entry point.

- creates `HoldToRecordApp`
- starts the long-running loop
- ensures shutdown cleanup runs

### `hotkey_app.py`

The orchestration layer.

- installs the global hotkey listener
- starts recording on key-down
- stops recording on key-up
- updates the overlay state
- plays start/stop sounds
- pushes finished audio into a worker queue
- keeps Whisper work off the hotkey thread

### `recorder.py`

Microphone capture.

- opens a live `sounddevice.InputStream`
- buffers incoming audio chunks while recording is active
- concatenates them into one NumPy array on stop
- returns mono float32 audio shaped for transcription

### `transcriber.py`

Speech-to-text and paste behavior.

- owns the `WhisperModel`
- flattens the captured waveform into a 1-D array
- runs local transcription with `faster-whisper`
- disables unnecessary progress-bar machinery
- joins transcribed segments into one string
- copies the result with `pyperclip`
- triggers paste with macOS `System Events`

### `overlay.py`

Overlay manager and native target tracking.

- launches the Tkinter overlay as a separate Python process
- maintains a small JSON IPC file in the temp directory
- publishes recording state into that file
- continuously tracks the focused window bounds through macOS Accessibility APIs
- writes updated target bounds atomically so the UI process can react safely

### `indicator_window.py`

Floating overlay UI.

- creates the borderless waveform window
- reads overlay state from the JSON IPC file
- renders idle and recording visuals
- moves to the active display based on the published target bounds
- applies Cocoa window behavior so the overlay can follow the active Space
- supports drag repositioning while preserving the chosen offset

## End-to-End Flow

```text
Hotkey press
  -> hotkey_app starts recorder + marks overlay as recording
  -> recorder buffers live microphone chunks
Hotkey release
  -> recorder stops and returns captured audio
  -> hotkey_app enqueues audio
  -> worker thread runs transcriber
  -> transcriber runs Whisper locally
  -> text copied to clipboard
  -> paste sent to active app

In parallel:
  -> overlay tracker publishes focused-window bounds
  -> indicator window reads IPC updates
  -> overlay follows the active display and updates waveform state
```

## Concurrency Model

There are several independent execution paths:

- the global keyboard listener thread from `pynput`
- the `sounddevice` audio callback thread
- the transcription worker thread
- the overlay tracking thread
- the separate Tkinter subprocess for the overlay UI

This separation matters because recording, keyboard handling, transcription, and UI updates all have different latency requirements.

## Design Notes

- Transcription is local-first.
- Recording is hold-to-talk rather than fixed-duration.
- Overlay rendering is decoupled from the main process through file-based IPC.
- Active-window tracking is native macOS API based rather than AppleScript polling.
- The overlay follows the user’s active display instead of attaching itself visually to a specific app window.

## Repository Layout

```text
main.py               App entry point
hotkey_app.py         Hotkey, orchestration, worker queue
recorder.py           Live microphone capture
transcriber.py        Whisper inference, clipboard, paste
overlay.py            Overlay process manager and target tracking
indicator_window.py   Floating Tkinter overlay UI
architecture-notes.md Implementation notes and earlier design decisions
voice-transcription-model.md Product and workflow notes
```

## Limitations

- Current implementation is macOS-oriented.
- Paste behavior depends on Accessibility permission and the target app accepting synthetic `Cmd+V`.
- The overlay follows the active display, not exact text caret position.
- Audio is buffered in memory until recording stops.
- The default model is CPU `base`, which favors simplicity over maximum accuracy.

## Development

Useful sanity check:

```bash
python3 -m py_compile main.py hotkey_app.py recorder.py transcriber.py overlay.py indicator_window.py
```

If you are changing overlay behavior, keep in mind that the visible UI lives in a separate subprocess and receives state through the JSON IPC file, not direct function calls from the main app.
