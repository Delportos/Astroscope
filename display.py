from luma.core.interface.serial import i2c
from luma.oled.device import ssd1306
from PIL import Image

#module level 

_serial = i2c(port=1, address=0x3C)
_device = ssd1306(_serial, width=128,height=64)

WIDTH =_device.width
HEIGHT = _device.height

def blank_canvas():
	"""Return a fresh blank 1bit image at display dimensions."""
	return Image.new('1',(WIDTH,HEIGHT),0)

def show(image):
	"""Push a PIL image to the OLED. Im must be mode '1' and (W,H)"""
	_device.display(image)
