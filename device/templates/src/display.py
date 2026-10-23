from luma.core.interface.serial import i2c
from luma.oled.device import ssd1306
from PIL import Image

WIDTH = 128
HEIGHT = 64

# Try to bring up the real OLED. On the Pi this succeeds and we draw to hardware.
# On a Mac (no /dev/i2c-1) the open fails; we fall back to no-op show() so the
# module still imports cleanly and virtualdisplay can take over the rendering.
try:
    _serial = i2c(port=1, address=0x3C)
    _device = ssd1306(_serial, width=WIDTH, height=HEIGHT)
    _HARDWARE = True
except Exception:
    _device = None
    _HARDWARE = False


def blank_canvas():
    """Return a fresh blank 1-bit image at display dimensions."""
    return Image.new('1', (WIDTH, HEIGHT), 0)


def show(image):
    """Push a PIL image to the OLED. Image must be mode '1' and (WIDTH, HEIGHT).
    On Mac (no hardware), this is a no-op — virtualdisplay/virtual.py is what
    actually renders during prototyping."""
    if _HARDWARE:
        _device.display(image)