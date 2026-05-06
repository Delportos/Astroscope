"""
Mac-side entry point. Runs scenes against the pygame virtual OLED instead
of real hardware. Mirrors main.py's dispatcher shape but uses display.virtual
for show/wait so the pygame window stays responsive.

Run from project root:
    python -m display.virtualmain          # default scene
    python -m display.virtualmain boot
    python -m display.virtualmain load

Quit: press Enter in the terminal, close the pygame window, or hit Esc in it.
"""
import sys
import threading

# Import the virtual display BEFORE scenes so any 'from display import WIDTH, HEIGHT'
# inside scene modules resolves against the virtual module's constants.
# (Constants happen to match the real display, but this keeps the import order honest.)
from virtualdisplay import virtual as display

from scenes import splash, hello, readoutv1, galesplash, boot, loading

SCENES = {
    'splash': splash.render,
    'hello': hello.render,
    'readout': readoutv1.render,
    'gale': galesplash.render,
    'boot': boot.render,
    'load': loading.render,
}


def main():
    name = sys.argv[1] if len(sys.argv) > 1 else 'splash'
    if name not in SCENES:
        print(f"Unknown scene: {name}. Available: {list(SCENES)}")
        sys.exit(1)
    render = SCENES[name]

    stop = threading.Event()

    def wait_for_enter():
        try:
            input("Press Enter to clear and exit...")
        except EOFError:
            pass
        stop.set()

    threading.Thread(target=wait_for_enter, daemon=True).start()

    try:
        while not stop.is_set():
            image, delay = render()
            display.show(image)
            if delay is None:
                display.wait(stop, None)
                break
            display.wait(stop, delay)
    finally:
        display.shutdown()


if __name__ == '__main__':
    main()