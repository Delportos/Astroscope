import sys
import time
import threading
from display import show
from scenes import splash, hello, readoutv1, galesplash,boot,loading

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

    # Stop flag toggled by the input thread when user hits Enter
    stop = threading.Event()
    def wait_for_enter():
        input("Press Enter to clear and exit...")
        stop.set()
    threading.Thread(target=wait_for_enter, daemon=True).start()

    while not stop.is_set():
        image, delay = render()
        show(image)
        if delay is None:
            stop.wait()  # static scene: just block until Enter
            break
        stop.wait(delay)  # animated: sleep, but wake early on Enter

if __name__ == '__main__':
    main()
