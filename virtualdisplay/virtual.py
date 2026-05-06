"""
Virtual SSD1306 display backend using pygame.

Drop-in replacement for the real `display` module when prototyping on a laptop.
Exposes the same surface as the real display module: WIDTH, HEIGHT, show(image),
plus wait(stop, delay) which the dispatcher uses instead of stop.wait(delay)
so the pygame window stays responsive between frames.

Usage from main.py:
    if args.virtual:
        from display import virtual as display
    else:
        import display   # the existing real-hardware module
"""
import time
import pygame
from PIL import Image

WIDTH = 128
HEIGHT = 64
SCALE = 8  # 128x64 -> 1024x512, big enough to see on a Retina display

# OLED color palette: white-on-black, like the real SSD1306
FG = (255, 255, 255)
BG = (0, 0, 0)

_screen = None
_initialized = False
_closed = False


def _ensure_window():
    """Lazy-init pygame on first show() so importing is side-effect free."""
    global _screen, _initialized
    if _initialized:
        return
    pygame.init()
    pygame.display.set_caption("Astroscope virtual OLED")
    _screen = pygame.display.set_mode((WIDTH * SCALE, HEIGHT * SCALE))
    _initialized = True


def _pump_events():
    """Drain the event queue. Sets _closed if user closes the window or hits Esc."""
    global _closed
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            _closed = True
        elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            _closed = True


def _pil_to_surface(image):
    """Convert a PIL image (any mode) to a scaled-up pygame Surface."""
    # Scenes return mode '1' (1-bit); map that to white-on-black RGB so it
    # actually looks like the OLED instead of pygame's default 1-bit handling.
    if image.mode == '1':
        rgb = Image.new('RGB', image.size, BG)
        white = Image.new('RGB', image.size, FG)
        rgb.paste(white, mask=image)
        image = rgb
    elif image.mode != 'RGB':
        image = image.convert('RGB')

    raw = image.tobytes()
    surf = pygame.image.fromstring(raw, image.size, 'RGB')
    # pygame.transform.scale is nearest-neighbor, which is what we want for
    # 1-bit graphics — bilinear smoothing makes pixel art look wrong.
    return pygame.transform.scale(surf, (WIDTH * SCALE, HEIGHT * SCALE))


def show(image):
    """Render a PIL image to the virtual OLED window."""
    _ensure_window()
    _pump_events()
    if _closed:
        return
    surf = _pil_to_surface(image)
    _screen.blit(surf, (0, 0))
    pygame.display.flip()


def wait(stop_event, delay):
    """
    Sleep up to `delay` seconds, but:
      - return early if stop_event is set (user hit Enter in the dispatcher)
      - return early if the user closes the pygame window (also sets stop_event
        so the dispatcher exits cleanly)
      - keep the pygame event queue pumped so the window stays responsive

    If delay is None, wait indefinitely (static scene). Mirrors stop.wait(delay)
    semantics but with event pumping mixed in.
    """
    global _closed
    poll_interval = 0.02  # 50 Hz event pump is plenty for a 128x64 display

    if delay is None:
        while not stop_event.is_set() and not _closed:
            _pump_events()
            if stop_event.wait(poll_interval):
                return
        if _closed:
            stop_event.set()
        return

    deadline = time.monotonic() + delay
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        _pump_events()
        if _closed:
            stop_event.set()
            return
        # stop_event.wait returns True the moment Enter is pressed in the
        # dispatcher's input thread — gives us the snappy mid-animation quit.
        if stop_event.wait(min(poll_interval, remaining)):
            return


def shutdown():
    """Tear down pygame cleanly. Optional; call on dispatcher exit."""
    global _initialized, _closed
    if _initialized:
        pygame.quit()
        _initialized = False
        _closed = True