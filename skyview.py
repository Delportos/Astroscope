"""
sky_view.py - live pygame finder view of the stars the IMU is pointing at.

Runs on the Mac, in the same folder as starfinder.py, stars.csv and imu_link.py.
Pointing comes from the Pi via IMULink; starfinder turns it into RA/Dec; the
catalog stars around that point are drawn as you would see them on the sky
(zenith up, east to the left).

Keys:  S = sync (tube pointing due south)   + / - = zoom
       L = toggle labels                    Esc / Q = quit
"""
import math
from datetime import datetime, timezone
from pathlib import Path

import pygame

import starfinder
from imu_link import IMULink

# ---- observer / display config ------------------------------------------------
LAT_DEG, LON_DEG, ELEV_M = 41.495, -81.535, 220
BASE_DIR = Path(__file__).resolve().parent
CATALOG_PATH = BASE_DIR / "stars.csv"

WIDTH, HEIGHT = 1500, 980
FPS = 60
FOV_DEG = 30.0                  # field of view across the window width
FOV_MIN, FOV_MAX = 5.0, 120.0
LABEL_MAG_LIMIT = 3.5           # label stars brighter than this (the match is always labeled)
MATCH_SEP_DEG = getattr(starfinder, "MATCH_MAX_SEP_DEG", 2.0)

BG = (5, 8, 20)
MATCH = (255, 200, 60)
RETICLE = (200, 60, 60)
HUD = (170, 190, 220)
DIM = (90, 100, 120)


# ---- projection ------------------------------------------------------------------
def project(ra0, sin_d0, cos_d0, ra, sin_d, cos_d):
    """
    Gnomonic (tangent-plane) projection of a star onto a plane touching the sky
    at the pointing direction. It is what a camera/eyepiece does: straight lines
    on the sky stay straight, and distortion is small near the center.
    Returns (x, y) in tangent-plane units with east to the LEFT (as seen looking
    up at the sky) and celestial north up, or None if the star is behind us.
    """
    dra = ra - ra0
    cos_dra = math.cos(dra)
    cos_c = sin_d0 * sin_d + cos_d0 * cos_d * cos_dra   # cos of angle from center
    if cos_c <= 0.0:
        return None
    xi = cos_d * math.sin(dra) / cos_c
    eta = (cos_d0 * sin_d - sin_d0 * cos_d * cos_dra) / cos_c
    return -xi, eta


def view_rotation(alt, az, lst, ra0, sin_d0, cos_d0):
    """
    Angle that rotates the celestial-north-up projection so the ZENITH is up.
    Trick: convert a point slightly above the pointing direction to RA/Dec,
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
    if near_zenith:                 # we sampled below the center, so flip
        ux, uy = -ux, -uy
    return math.atan2(ux, uy)       # rotating by this puts (ux, uy) straight up


def star_radius(mag):
    return max(1, round(4.5 - 0.8 * mag))       # mag -1.5 -> 6 px, mag 4.5 -> 1 px


def star_color(mag):
    b = int(max(110, min(255, 255 - 25 * mag)))
    return (b, b, min(255, b + 15))


# ---- drawing helpers -------------------------------------------------------------
def draw_lines(surface, font, lines, x, y, color, line_h=17):
    for i, line in enumerate(lines):
        surface.blit(font.render(line, True, color), (x, y + i * line_h))


def main():
    pygame.init()
    screen = pygame.display.set_mode((WIDTH, HEIGHT))
    pygame.display.set_caption("Astroscope - live sky view")
    font = pygame.font.SysFont("menlo", 14)
    small = pygame.font.SysFont("menlo", 12)
    clock = pygame.time.Clock()
    cx, cy = WIDTH // 2, HEIGHT // 2

    catalog = starfinder.load_catalog(CATALOG_PATH)
    # Precompute per-star trig once; only the pointing changes per frame.
    stars = []
    for s in catalog:
        d = math.radians(s.dec_degrees)
        stars.append((s, math.radians(s.ra_hours * 15), math.sin(d), math.cos(d)))

    imu = IMULink()
    fov = FOV_DEG
    show_labels = True
    running = True

    while running:
        # -- input --
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_ESCAPE, pygame.K_q):
                    running = False
                elif event.key == pygame.K_s:
                    try:
                        imu.sync(180.0)
                    except RuntimeError:
                        pass                        # no data yet
                elif event.key in (pygame.K_EQUALS, pygame.K_PLUS, pygame.K_KP_PLUS):
                    fov = max(FOV_MIN, fov / 1.25)
                elif event.key in (pygame.K_MINUS, pygame.K_KP_MINUS):
                    fov = min(FOV_MAX, fov * 1.25)
                elif event.key == pygame.K_l:
                    show_labels = not show_labels

        screen.fill(BG)
        p = imu.pointing()

        if p is None:
            if imu.stale:
                msg = ["Waiting for IMU..."]
            else:
                msg = ["NOT SYNCED",
                       "Point the tube due south, hold still, press S"]
            draw_lines(screen, font, msg, 20, 20, HUD)

        else:
            alt, az = p
            utc = datetime.now(timezone.utc)
            lst = starfinder.local_sidereal_time(utc, LON_DEG)
            ra0_h, dec0 = starfinder.altaz_to_radec(alt, az, LAT_DEG, lst)
            ra0 = math.radians(ra0_h * 15)
            d0 = math.radians(dec0)
            sin_d0, cos_d0 = math.sin(d0), math.cos(d0)

            result = starfinder.identify_star(LAT_DEG, LON_DEG, ELEV_M, utc,
                                              alt, az, catalog)

            theta = view_rotation(alt, az, lst, ra0, sin_d0, cos_d0)
            cos_t, sin_t = math.cos(theta), math.sin(theta)
            scale = (WIDTH / 2) / math.tan(math.radians(fov / 2))   # px per tangent unit

            # -- stars --
            for star, ra, sin_d, cos_d in stars:
                pr = project(ra0, sin_d0, cos_d0, ra, sin_d, cos_d)
                if pr is None:
                    continue
                x, y = pr
                xr = x * cos_t - y * sin_t
                yr = x * sin_t + y * cos_t
                sx, sy = cx + xr * scale, cy - yr * scale
                if not (-20 <= sx <= WIDTH + 20 and -20 <= sy <= HEIGHT + 20):
                    continue

                r = star_radius(star.ap_mag)
                pygame.draw.circle(screen, star_color(star.ap_mag), (int(sx), int(sy)), r)

                is_match = result.matched and star is result.star
                if is_match:
                    pygame.draw.circle(screen, MATCH, (int(sx), int(sy)), r + 6, 2)
                if show_labels and (is_match or star.ap_mag <= LABEL_MAG_LIMIT):
                    color = MATCH if is_match else DIM
                    screen.blit(small.render(star.name, True, color), (sx + r + 4, sy - 7))

            # -- reticle: circle = match radius --
            rr = int(math.tan(math.radians(MATCH_SEP_DEG)) * scale)
            pygame.draw.circle(screen, RETICLE, (cx, cy), max(rr, 4), 1)
            pygame.draw.line(screen, RETICLE, (cx - rr - 10, cy), (cx - rr - 2, cy))
            pygame.draw.line(screen, RETICLE, (cx + rr + 2, cy), (cx + rr + 10, cy))
            pygame.draw.line(screen, RETICLE, (cx, cy - rr - 10), (cx, cy - rr - 2))
            pygame.draw.line(screen, RETICLE, (cx, cy + rr + 2), (cx, cy + rr + 10))

            # -- HUD --
            draw_lines(screen, font, [
                f"Alt {alt:6.2f}   Az {az:6.2f}",
                f"RA  {ra0_h:6.3f}h  Dec {dec0:+6.2f}",
                f"FOV {fov:5.1f} deg",
                f"UTC {utc:%H:%M:%S}",
            ], 20, 20, HUD)
            info = starfinder.format_result(result).splitlines()
            draw_lines(screen, font, info, 20, HEIGHT - 20 - 17 * len(info),
                       MATCH if result.matched else HUD)

        draw_lines(screen, small, ["S sync south   +/- zoom   L labels   Q quit"],
                   WIDTH - 330, HEIGHT - 24, DIM)
        pygame.display.flip()
        clock.tick(FPS)

    imu.close()
    pygame.quit()


if __name__ == "__main__":
    main()