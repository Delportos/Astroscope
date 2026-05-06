from PIL import Image, ImageSequence, ImageDraw, ImageFont
from display import WIDTH, HEIGHT
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_HERE)  # scenes/ is one level below root
LOGO_PATH = os.path.join(_PROJECT_ROOT, 'galloelectronics.png')

_frames = None
_idx = 0

def _load():
    global _frames
    gif = Image.open('loadingscreen1.gif')
    _frames = []
    font = ImageFont.load_default()
    for i, frame in enumerate(ImageSequence.Iterator(gif)):
        f = frame.convert('L').resize((WIDTH, HEIGHT))
        f = f.point(lambda p: 255 if p > 200 else 0).convert('1')
        if i % 6 < 3:
            draw = ImageDraw.Draw(f)
            text = "loading"
            bbox = draw.textbbox((0, 0), text, font=font)
            text_w = bbox[2] - bbox[0]
            draw.text((WIDTH - text_w - 2, 2), text, fill=255, font=font)
        delay = frame.info.get('duration', 100) / 1000.0
        _frames.append((f, delay))
    _frames = _frames[:-1]
def render():
    global _idx
    if _frames is None:
        _load()
    img, delay = _frames[_idx % len(_frames)]
    _idx += 1
    return img, delay
