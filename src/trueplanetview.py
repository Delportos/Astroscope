"""
Night sky visualizer based upon current location, date and time. Displays planets and stars.
"""
import math
from datetime import datetime, timezone
from pathlib import Path

import pygame

import planets
import starfinder

from imu_link import IMULink

# explorer/display configurations
LAT_DEG,LONG_DEG, ELEV_M = 41.495, -81.535, 220 
BASE_DIR = Path(__file__).resolve().parent
CATALOG_PATH = BASE_DIR / "stars.csv"
PLANETS_PATH = BASE_DIR / "planets.csv"
PLANET_REFRESH_S = 1.0

PLANET_STYLE = {
    "mercury": ((200,190,170),0.0),
    "venus": ((255,245,200),-4.0),
    "mars": ((235,110,70),0.5),
    "jupiter": ((240,215,170),-2.3),
    "saturn": ((230,205,130),0.6),
    "uranus": ((150,220,230),3.5), 
    "neptune": ((110,140,255),4.0),
}

WIDTH, HEIGHT = 800,480
FPS = 60
FOV_DEG = 30.0 
FOV_MIN, FOV_MAX = 5.0, 120.0
LABEL_MAG_LIMIT = 3.5       #label stars brighter than this
MATCH_SEP_DEG = getattr(starfinder, "MATCH_MAX_SEP_DEG", 2.0)

# --- Polaris sync config -------
POLARIS_NAME = "Polaris"
POLARIS_FALLBACK = (2.53031,89.2644109) #J2000 RA (h), Dec (deg) if not in stars.csv
ALT_OFFSET_MAX_DEG = 8.0 # bigger than this = probably not Polaris; don't apply
STATUS_SECONDS = 6.0 # how long sync messages stay on screen

BG = (44, 54, 105)
MATCH = (255, 200, 60)
RETICLE = (200, 60, 60)
HUD = (170, 190, 220)
DIM = (90, 100, 120)
OK = (120, 220, 140)
WARN = (255, 120, 90)

# -- coordinates -- -
def radec_to_altaz(ra_h, dec_deg, lat_deg, lst_h):
    """
    Inverse of starfinder.altaz_to_radec: where a fixed RA/Dec sits in the local
    sky right now. Hour angle H = LST - RA;
    az is measured from N thru East
    """
    H = math.radians((lst_h - ra_h) * 15.0)
    d = math.radians(dec_deg)
    phi = math.radians(lat_deg)
    sin_alt = math.sin(d) * math.sin(phi) + math.cos(d) * math.cos(phi) * math.cos(H)
    alt = math.asin(max(-1.0, min(1.0, sin_alt)))
    az = math.atan2(-math.cos(d) * math.sin(H),
                    math.sin(d) * math.cos(phi) - math.cos(d) * math.sin(phi) * math.cos(H))
    return math.degrees(alt), math.degrees(az) % 360.0

def angular_sep_deg(ra1_h, dec1,ra2_h,dec2):
    r1, r2 = math.radians(ra1_h * 15), math.radians(ra2_h * 15)
    d1, d2 = math.radians(dec1), math.radians(dec2)
    c = math.sin(d1) * math.sin(d2) + math.cos(d1) * math.cos(d2) * math.cos(r1 - r2)
    return math.degrees(math.acos(max(-1.0,min(1.0,c))))

def find_polaris(catalog):
    """Take Polaris from the catalog so it uses the same epoch / data as every other star."""
    for s in catalog:
        if s.name and s.name.strip().lower() == POLARIS_NAME.lower():
            return s.ra_hours, s.dec_degrees, "catalog"
        return (*POLARIS_FALLBACK, "built-in J2000")

def polaris_altaz(ra_h,dec_deg,utc):
    """"""
    lst = starfinder.local_sidereal_time(utc, LONG_DEG)
    return radec_to_altaz(ra_h, dec_deg, LAT_DEG,lst)


def self_check(ra_h,dec_deg):
    """
    Round-trip Polaris through radec_to_altaz -> starfinder.altaz_to_radec.
    If the two disagree, the sync azimuth would be wrong
    """
    utc = datetime.now(timezone.utc)
    lst = starfinder.local_sidereal_time(utc,LONG_DEG)
    alt,az = radec_to_altaz(ra_h,dec_deg,LAT_DEG,lst)
    ra_b,dec_b = starfinder.altaz_to_radec(alt,az LAT_DEG,lst)
    sep = angular_sep_deg(ra_h,dec_deg,ra_b,dec_b)
    status = "OK" if sep < 0.05 else "MISMATCH - check LST unit/az convetion"
    print(f"[polaris] alt {alt:.3f} az {az:.3f} round-trip error {sep:.4f} deg {status}")

# -- planets ---
def planet_positions(pcat, utc):
    """
    The ONLY function that touches planets.py's API
    Returns [(display_name,ra_hours,dec_deg,distance_au), ...]
    """
    jd = planets.julian_date(utc)
    earth = pcat["earth"]
    out = []
    for key, planet in pcat.items():
        if key = "earth":
            continue
        ra_h, dec, dist = planets.planet_radec(planet, earth, jd)
        out.append((key.capitalize(), ra_h, dec, dist))
    return out

def nearest_planet(ra_h, dec_deg, bodies):
    """((name,ra,dec,dist),sep_deg) for the closest planet inside match radius"""
    best = None
    for b in bodies:
        sep = angular_sep_deg(ra_h, dec_deg,b[1],b[2])
        if sep <= MATCH_SEP_DEG and (best is None or sep < best[1]):
            best = (b, sep)
    return best

# projection
def project(ra0, sin_d0, cos_d0, ra, sin_d, cos_d):
    """
    Gnomonic projection of a star onto a plane touching
    the sky in the pointing direction. 
    """
    dra = ra - ra0
    cos_dra = math.cos(dra)
    cos_c = sin_d0 * sin_d + cos_d0 * cos_d * cos_dra
    if cos_c <= 0.0:
        return None
    xi = cos_d * math.sin(dra) / cos_c
    eta = (cos_d0 * sin_d - sin_d0 * cos_d * cos_dra) / cos_c
    return -xi, eta

def view_rotation(alt, az, lst, ra0, sin_d0, cos_d0):
    """
    Angle that rotates the celestial north up proj so the zenith is up
    Trick: convert a ppoint slightly above the pointing direction to RA/Dec,
    project it, and see which way it lands. Reuses starfinder's own math, so
    the view can't disagree with the identification.
    """

    near_zenith = alt >= 89.0
    up_alt = alt - 0.5 if near_zenith else alt + 0.5
    ura_h, udec = starfinder.altaz_to_radec(up_alt, az, LAT_DEG, lst)
    ud = math.radians(udec)
    u = project(ra0, sin_d0, cos_d0, math.radians(ura_h * 15), math.sin(ud), math.cos(ud))
    if u is None:
        return 0.0
    ux, uy = u
    if near_zenith:
        ux, uy = -ux, -uy
    return math.atan2(ux, uy)

def star_radius(mag):
    return max(1, round(4.5 - 0.8 * mag)) # mag -1.5 > 6 px, mag 4.5 > 1 px

def star_color(mag):
    b = int(max(110,min(255,255 - 25 * mag)))
    return (b, b, min(255, b + 15))

# drawing helpers

def draw_line(surface, font, lines, x, y, color, line_h = 17):
    for i, line in enumerate(lines):
        surface.blit(font.render(line, True, color), (x,y + i * line_h))
        