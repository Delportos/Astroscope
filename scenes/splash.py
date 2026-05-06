from PIL import Image
from display import WIDTH, HEIGHT
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_HERE)  # scenes/ is one level below root
LOGO_PATH = os.path.join(_PROJECT_ROOT, 'Astroscope1.png')
def render():
	logo = Image.open(LOGO_PATH).convert('L')
	logo = logo.point(lambda p: 255 if p>200 else 0).convert('1')
	return logo, None

