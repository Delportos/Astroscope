import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timezone
from PIL import ImageDraw, ImageFont
from display import blank_canvas
from starfinder import stars_i_can_look_at, load_catalog
from planets import planet_radec,load_catalog
from PIL import ImageFont


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
planets = load_catalog(os.path.join(PROJECT_ROOT, "planets.csv"))
_font = ImageFont.load_default()
#_font = ImageFont.truetype("/System/Library/Fonts/Menlo.ttc", size=12)



def render():
    image = blank_canvas()
    draw = ImageDraw.Draw(image)

    ra,dec,distance = planet_radec(planets["jupiter"], planets["earth"], jd=2461169.54167)

    display = [ra,dec,distance]

    h = int(ra)
    m = int((ra - h) * 60)
    s = ((ra - h) * 60 - m) * 60


    draw.text((0, 0), "Where is JUPITER?", font=_font, fill=1)
    yval = []
    for i in range(3):
        y = (i + 1) * 14
        yval.append(y)
    linera = f"RA: {h:02d}h {m:02d}m {s:04.1f}s"
    linedec = f"Dec: {display[1]:.3f} deg"
    linedis = f"Dist: {display[2]:.3f} AU"
    draw.text((0, yval[0]), linera, font=_font, fill=1)
    draw.text((0, yval[1]), linedec, font=_font, fill=1)
    draw.text((0, yval[2]), linedis, font=_font, fill=1)
    return image,None
