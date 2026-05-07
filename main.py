# Import the long-running app that coordinates hotkeys, recording, and transcription.
from hotkey_app import HoldToRecordApp


def main():
    # Create the app and configure the hold-to-record hotkey as `Ctrl+Shift`.
    app = HoldToRecordApp(hotkey="ctrl+shift")

    try:
        # Start the global hotkey listener and keep the process alive until interrupted.
        app.run()
    finally:
        # Always release audio/model resources even if the program exits with Ctrl+C or an error.
        app.close()


if __name__ == "__main__":
    main()
