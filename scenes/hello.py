from PIL import ImageDraw, ImageFont
from display import blank_canvas

_font = ImageFont. load_default()

def render():
	image = blank_canvas()
	draw = ImageDraw.Draw(image)
	draw.text((10,25),"hello astro!", font=_font,fill=1)
	return image, None
