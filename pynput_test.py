"""Test pynput key detection — writes to pynput_test.log for 15 seconds."""
import time
from pynput import keyboard as kb

LOG = r"c:\mydata\JD\Joulewarehouse\pynput_test.log"

with open(LOG, "w") as f:
    f.write("pynput test started — press Ctrl+Shift+J within 15 seconds\n")
    f.flush()

    ctrl  = set()
    shift = set()
    fired = False

    def on_press(key):
        global fired
        with open(LOG, "a") as lf:
            lf.write(f"PRESS: {repr(key)}\n")
            lf.flush()

    def on_release(key):
        with open(LOG, "a") as lf:
            lf.write(f"release: {repr(key)}\n")
            lf.flush()

    listener = kb.Listener(on_press=on_press, on_release=on_release, suppress=False)
    listener.start()
    time.sleep(15)
    listener.stop()

    with open(LOG, "a") as lf:
        lf.write("test done\n")
