import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timezone
from PIL import ImageDraw, ImageFont
from display import blank_canvas
from starfinder import stars_i_can_look_at, load_catalog

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_catalog = load_catalog(os.path.join(PROJECT_ROOT, "stars.csv"))
_font = ImageFont.load_default()

TEST_INPUT = (
    41.495,
    -81.535,
    220,
    datetime(2026, 5, 2, 1, 40, 0, tzinfo=timezone.utc),
    41,
    359,
)


def render():
    image = blank_canvas()
    draw = ImageDraw.Draw(image)

    visible = stars_i_can_look_at(*TEST_INPUT, catalog=_catalog)
    top3 = sorted(visible, key=lambda s: s.magnitude)[:3]

    draw.text((0, 0), "BRIGHTEST:", font=_font, fill=1)
    for i, star in enumerate(top3):
        y = (i + 1) * 14
        line = f"{star.name} {star.magnitude} {star.ra_hours:.1f}/{star.dec_degrees:.1f}"
        draw.text((0, y), line, font=_font, fill=1)

    return image,None
