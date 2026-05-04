from PIL import Image
from display import WIDTH, HEIGHT

LOGO_PATH = '/home/resolut/astroscope/galloelectronics.png'

def render():
    logo = Image.open(LOGO_PATH).convert('L')
    logo = logo.point(lambda p: 255 if p>200 else 0).convert('1')
    return logo, None
