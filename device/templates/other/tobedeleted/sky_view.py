"""
sky_view.py - live pygame finder view of the stars the IMU is pointing at.

Runs on the Mac OR on the Pi (Lars), in the same folder as starfinder.py,
planets.py, stars.csv, planets.csv and imu_link.py.

  Mac: normal window, MAC_SIZE.
  Pi (headless, console boot): fullscreen on the HDMI panel through KMS/DRM,
       plus an MJPEG stream of the same frames at http://lars.local:5001/stream

Pointing comes from IMULink; starfinder turns it into RA/Dec; the catalog stars
around that point are drawn as you would see them on the sky (zenith up, east left).

Keys:  S = sync (tube pointing due south)   P = sync on Polaris (az + alt)
       C = clear altitude offset            + / - = zoom
       L = toggle labels                    Esc / Q = quit
"""
import io
import math
import os
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

# ---- platform detection (must happen BEFORE pygame/SDL initializes) -------------
# Linux with no X11/Wayland session = the headless Pi. SDL then has no window
# system to talk to, so tell it to drive the display directly through KMS/DRM.
ON_PI = sys.platform.startswith("linux") and not (
    os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
if ON_PI:
    os.environ.setdefault("SDL_VIDEODRIVER", "kmsdrm")

import pygame  # noqa: E402  (import after SDL env is set)

import planets  # noqa: E402
import starfinder  # noqa: E402
from imu_link import IMULink  # noqa: E402

# ---- observer / display config ------------------------------------------------
LAT_DEG, LON_DEG, ELEV_M = 41.495, -81.535, 220
BASE_DIR = Path(__file__).resolve().parent
CATALOG_PATH = BASE_DIR / "stars.csv"
PLANETS_PATH = BASE_DIR / "planets.csv"
PLANET_REFRESH_S = 1.0          # planets move < 1 arcsec/s; no need to recompute every frame
# display color + a typical magnitude (only used for dot size, not physics)
PLANET_STYLE = {
    "mercury": ((200, 190, 170), 0.0),
    "venus":   ((255, 245, 200), -4.0),
    "mars":    ((235, 110, 70), 0.5),
    "jupiter": ((240, 215, 170), -2.3),
    "saturn":  ((230, 205, 130), 0.6),
    "uranus":  ((150, 220, 230), 3.5),   # drawn a bit bigger than true mag so you can see it
    "neptune": ((110, 140, 255), 4.0),
}

MAC_SIZE = (1700, 1080)         # Pi uses the panel's native mode instead
ROTATE = 0                      # Pi only: 0 = panel as-is (480x800 portrait); 90/270 = landscape
FPS = 30 if ON_PI else 60       # leave Pi CPU for JPEG encoding + IMU
FONT_NAMES = "menlo,dejavusansmono,liberationmono"   # first one installed wins
FOV_DEG = 30.0                  # field of view across the window width
FOV_MIN, FOV_MAX = 5.0, 120.0
LABEL_MAG_LIMIT = 3.5           # label stars brighter than this (the match is always labeled)
MATCH_SEP_DEG = getattr(starfinder, "MATCH_MAX_SEP_DEG", 2.0)
NARROW_PX = 900                 # below this width, stack the HUD instead of using corners

# ---- stream config (Pi only) ------------------------------------------------------
STREAM = ON_PI
STREAM_PORT = 5001              # 5000 is left for the /api/point server
STREAM_EVERY = 3                # encode every Nth rendered frame (30 fps -> 10 fps stream)
STREAM_QUALITY = 70

# ---- Polaris sync config --------------------------------------------------------
POLARIS_NAME = "Polaris"
POLARIS_FALLBACK = (2.530301, 89.264109)   # J2000 RA (h), Dec (deg) if not in stars.csv
ALT_OFFSET_MAX_DEG = 8.0        # bigger than this = probably not on Polaris; don't apply
STATUS_SECONDS = 6.0            # how long sync messages stay on screen

BG = (44, 54, 105)
MATCH = (255, 200, 60)
RETICLE = (200, 60, 60)
HUD = (170, 190, 220)
DIM = (90, 100, 120)
OK = (120, 220, 140)
WARN = (255, 120, 90)

# pygame 2.1.3 renamed tostring -> tobytes; apt's python3-pygame on Bookworm is 2.1.2
_tobytes = getattr(pygame.image, "tobytes", None) or pygame.image.tostring


# ---- coordinates -----------------------------------------------------------------
def radec_to_altaz(ra_h, dec_deg, lat_deg, lst_h):
    """
    Inverse of starfinder.altaz_to_radec: where a fixed RA/Dec sits in the local
    sky right now. Hour angle H = LST - RA; azimuth is measured from north
    through east, same convention the IMU sync uses (south = 180).
    """
    H = math.radians((lst_h - ra_h) * 15.0)
    d = math.radians(dec_deg)
    phi = math.radians(lat_deg)
    sin_alt = math.sin(d) * math.sin(phi) + math.cos(d) * math.cos(phi) * math.cos(H)
    alt = math.asin(max(-1.0, min(1.0, sin_alt)))
    az = math.atan2(-math.cos(d) * math.sin(H),
                    math.sin(d) * math.cos(phi) - math.cos(d) * math.sin(phi) * math.cos(H))
    return math.degrees(alt), math.degrees(az) % 360.0


def angular_sep_deg(ra1_h, dec1, ra2_h, dec2):
    r1, r2 = math.radians(ra1_h * 15), math.radians(ra2_h * 15)
    d1, d2 = math.radians(dec1), math.radians(dec2)
    c = math.sin(d1) * math.sin(d2) + math.cos(d1) * math.cos(d2) * math.cos(r1 - r2)
    return math.degrees(math.acos(max(-1.0, min(1.0, c))))


def find_polaris(catalog):
    """Take Polaris from the catalog so it uses the same epoch/data as every other star."""
    for s in catalog:
        if s.name and s.name.strip().lower() == POLARIS_NAME.lower():
            return s.ra_hours, s.dec_degrees, "catalog"
    return (*POLARIS_FALLBACK, "built-in J2000")


def polaris_altaz(ra_h, dec_deg, utc):
    lst = starfinder.local_sidereal_time(utc, LON_DEG)
    return radec_to_altaz(ra_h, dec_deg, LAT_DEG, lst)


def self_check(ra_h, dec_deg):
    """
    Round-trip Polaris through radec_to_altaz -> starfinder.altaz_to_radec.
    If the two disagree, the sync azimuth would silently be wrong (e.g. an LST
    unit mismatch), so shout about it once at startup.
    """
    utc = datetime.now(timezone.utc)
    lst = starfinder.local_sidereal_time(utc, LON_DEG)
    alt, az = radec_to_altaz(ra_h, dec_deg, LAT_DEG, lst)
    ra_b, dec_b = starfinder.altaz_to_radec(alt, az, LAT_DEG, lst)
    sep = angular_sep_deg(ra_h, dec_deg, ra_b, dec_b)
    status = "OK" if sep < 0.05 else "MISMATCH - check LST units/az convention"
    print(f"[polaris] alt {alt:.3f}  az {az:.3f}  round-trip error {sep:.4f} deg  {status}")


# ---- planets ------------------------------------------------------------------------
def planet_positions(pcat, utc):
    """
    The ONLY function that touches planets.py's API. Returns
    [(display_name, ra_hours, dec_deg, distance_au), ...] for everything except Earth.
    """
    jd = planets.julian_date(utc)
    earth = pcat["earth"]
    out = []
    for key, planet in pcat.items():
        if key == "earth":
            continue
        ra_h, dec, dist = planets.planet_radec(planet, earth, jd)
        out.append((key.capitalize(), ra_h, dec, dist))
    return out


def nearest_planet(ra_h, dec_deg, bodies):
    """((name, ra, dec, dist), sep_deg) for the closest planet inside the match radius, else None."""
    best = None
    for b in bodies:
        sep = angular_sep_deg(ra_h, dec_deg, b[1], b[2])
        if sep <= MATCH_SEP_DEG and (best is None or sep < best[1]):
            best = (b, sep)
    return best


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


# ---- display + stream ------------------------------------------------------------
def open_display():
    """
    Returns (physical, canvas). Everything is drawn on `canvas`. On the Mac, and
    on the Pi with ROTATE = 0, canvas IS the screen. With ROTATE set, canvas is an
    offscreen surface with swapped dimensions that present() rotates onto the
    panel, because KMS/DRM always scans out in the panel's native orientation.
    """
    pygame.init()
    if ON_PI:
        physical = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)  # (0,0) = native mode
        pygame.mouse.set_visible(False)
    else:
        physical = pygame.display.set_mode(MAC_SIZE)
    pygame.display.set_caption("Astroscope - live sky view")

    rotate = ROTATE if ON_PI else 0
    pw, ph = physical.get_size()
    if rotate == 0:
        canvas = physical
    elif rotate in (90, 270):
        canvas = pygame.Surface((ph, pw))
    else:
        canvas = pygame.Surface((pw, ph))
    print(f"[display] {'Pi/KMSDRM' if ON_PI else 'window'} {pw}x{ph}, "
          f"canvas {canvas.get_width()}x{canvas.get_height()}, rotate {rotate}")
    return physical, canvas, rotate


def present(physical, canvas, rotate):
    if canvas is not physical:
        physical.blit(pygame.transform.rotate(canvas, rotate), (0, 0))
    pygame.display.flip()


class FrameStream:
    """
    Serves the most recent rendered frame as MJPEG at http://<host>:<port>/stream.
    The render loop calls publish(); Flask runs in a daemon thread and only ever
    reads the finished JPEG bytes, so the lock is held for a pointer swap, not
    for the encode.
    """

    def __init__(self, port):
        from flask import Flask, Response   # imported here so the Mac doesn't need them
        from PIL import Image
        self._Image = Image
        self._jpeg = None
        self._lock = threading.Lock()

        app = Flask(__name__)

        @app.route("/stream")
        def stream():
            return Response(self._frames(),
                            mimetype="multipart/x-mixed-replace; boundary=frame")

        threading.Thread(
            target=lambda: app.run(host="0.0.0.0", port=port, threaded=True,
                                   use_reloader=False),
            daemon=True).start()

    def publish(self, surface):
        raw = _tobytes(surface, "RGB")
        buf = io.BytesIO()
        self._Image.frombytes("RGB", surface.get_size(), raw).save(
            buf, "JPEG", quality=STREAM_QUALITY)
        with self._lock:
            self._jpeg = buf.getvalue()

    def _frames(self):
        while True:
            with self._lock:
                frame = self._jpeg
            if frame:
                yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"
            time.sleep(1 / 15)


# ---- drawing helpers -------------------------------------------------------------
def draw_lines(surface, font, lines, x, y, color, line_h=17):
    for i, line in enumerate(lines):
        surface.blit(font.render(line, True, color), (x, y + i * line_h))


def main():
    physical, screen, rotate = open_display()      # `screen` = the canvas we draw on
    WIDTH, HEIGHT = screen.get_size()
    narrow = WIDTH < NARROW_PX
    font = pygame.font.SysFont(FONT_NAMES, 14)
    small = pygame.font.SysFont(FONT_NAMES, 12)
    clock = pygame.time.Clock()
    cx, cy = WIDTH // 2, HEIGHT // 2

    # Corner layout on a wide window; stacked layout on the portrait panel.
    if narrow:
        hint_lines = ["S south  P Polaris  C clear alt", "+/- zoom  L labels  Q quit"]
        hint_pos = (20, HEIGHT - 20 - 15 * len(hint_lines))
        bottom_reserved = 15 * len(hint_lines) + 6
        status_pos = (20, 20 + 17 * 6)                  # below the 5-line HUD
    else:
        hint_lines = ["S south   P Polaris   C clear alt   +/- zoom   L labels   Q quit"]
        hint_pos = (WIDTH - 470, HEIGHT - 24)
        bottom_reserved = 0
        status_pos = (cx - 220, 20)

    streamer = None
    if STREAM:
        try:
            streamer = FrameStream(STREAM_PORT)
            print(f"[stream] http://{os.uname().nodename.lower()}.local:{STREAM_PORT}/stream")
        except ImportError as e:
            print(f"[stream] disabled ({e}) - install flask and pillow to enable")

    catalog = starfinder.load_catalog(CATALOG_PATH)
    # Precompute per-star trig once; only the pointing changes per frame.
    stars = []
    for s in catalog:
        d = math.radians(s.dec_degrees)
        stars.append((s, math.radians(s.ra_hours * 15), math.sin(d), math.cos(d)))

    pol_ra_h, pol_dec, pol_src = find_polaris(catalog)
    print(f"[polaris] RA {pol_ra_h:.4f}h  Dec {pol_dec:+.4f}  ({pol_src})")
    self_check(pol_ra_h, pol_dec)

    pcat = planets.load_catalog(PLANETS_PATH)
    planet_cache, planet_time = [], -math.inf

    imu = IMULink()
    fov = FOV_DEG
    show_labels = True
    running = True
    frame = 0
    sync_source = None              # "south" / "Polaris" once synced
    alt_offset = 0.0                # IMU-to-tube pitch misalignment, measured on Polaris
    status_lines, status_color, status_until = [], HUD, 0.0

    def set_status(lines, color):
        nonlocal status_lines, status_color, status_until
        status_lines, status_color = lines, color
        status_until = pygame.time.get_ticks() / 1000.0 + STATUS_SECONDS

    def sync_polaris():
        nonlocal sync_source, alt_offset
        # 1) Where is Polaris right now? (computed at the moment of the keypress)
        p_alt, p_az = polaris_altaz(pol_ra_h, pol_dec, datetime.now(timezone.utc))
        if p_alt <= 0.0:
            set_status(["Polaris is below the horizon here - use S"], WARN)
            return
        # 2) Tell the IMU that its current heading IS Polaris's azimuth.
        try:
            imu.sync(p_az)
        except RuntimeError:
            set_status(["No IMU data yet - can't sync"], WARN)
            return
        sync_source = "Polaris"
        # 3) Altitude: gravity makes the IMU's altitude absolute, so any leftover
        #    difference here is the IMU sitting tilted relative to the tube.
        #    Measure it once and remove it from every later reading.
        p = imu.pointing()                      # raw IMU altitude, synced azimuth
        lines = [f"Synced on Polaris: az {p_az:.2f}  alt {p_alt:.2f}"]
        color = OK
        if p is not None:
            residual = p_alt - p[0]             # + means the IMU under-reads altitude
            if abs(residual) <= ALT_OFFSET_MAX_DEG:
                alt_offset = residual
                lines.append(f"Altitude offset set to {alt_offset:+.2f} deg")
            else:
                lines += [f"Altitude off by {residual:+.2f} deg - too large, not applied",
                          "Are you really on Polaris?"]
                color = WARN
        set_status(lines, color)

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
                        sync_source = "south"
                        set_status(["Synced: due south (az 180)"], OK)
                    except RuntimeError:
                        set_status(["No IMU data yet - can't sync"], WARN)
                elif event.key == pygame.K_p:
                    sync_polaris()
                elif event.key == pygame.K_c:
                    alt_offset = 0.0
                    set_status(["Altitude offset cleared"], HUD)
                elif event.key in (pygame.K_EQUALS, pygame.K_PLUS, pygame.K_KP_PLUS):
                    fov = max(FOV_MIN, fov / 1.25)
                elif event.key in (pygame.K_MINUS, pygame.K_KP_MINUS):
                    fov = min(FOV_MAX, fov * 1.25)
                elif event.key == pygame.K_l:
                    show_labels = not show_labels

        screen.fill(BG)
        p = imu.pointing()
        if p is not None:                       # tube altitude = IMU altitude + mount offset
            p = (max(-90.0, min(90.0, p[0] + alt_offset)), p[1])

        if p is None:
            if imu.stale:
                msg = ["Waiting for IMU..."]
            else:
                p_alt, p_az = polaris_altaz(pol_ra_h, pol_dec, datetime.now(timezone.utc))
                msg = ["NOT SYNCED",
                       "Point the tube due south,",
                       "hold still, press S",
                       "  - or -",
                       "Center Polaris in the tube,",
                       "hold still, press P",
                       f"  Polaris now: alt {p_alt:.2f}  az {p_az:.2f}"]
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

            def to_screen(ra, sin_d, cos_d):
                """Same path for stars and planets: project, rotate zenith-up, scale."""
                pr = project(ra0, sin_d0, cos_d0, ra, sin_d, cos_d)
                if pr is None:
                    return None
                x, y = pr
                xr = x * cos_t - y * sin_t
                yr = x * sin_t + y * cos_t
                sx, sy = cx + xr * scale, cy - yr * scale
                if not (-20 <= sx <= WIDTH + 20 and -20 <= sy <= HEIGHT + 20):
                    return None
                return sx, sy

            # -- planets: refresh, then decide whether a planet beats the star match --
            now_s = pygame.time.get_ticks() / 1000.0
            if now_s - planet_time >= PLANET_REFRESH_S:
                planet_cache = planet_positions(pcat, utc)
                planet_time = now_s
            planet_hit = nearest_planet(ra0_h, dec0, planet_cache)
            star_sep = (angular_sep_deg(ra0_h, dec0, result.star.ra_hours, result.star.dec_degrees)
                        if result.matched else math.inf)
            planet_wins = planet_hit is not None and planet_hit[1] < star_sep

            # -- stars --
            for star, ra, sin_d, cos_d in stars:
                pos = to_screen(ra, sin_d, cos_d)
                if pos is None:
                    continue
                sx, sy = pos

                r = star_radius(star.ap_mag)
                pygame.draw.circle(screen, star_color(star.ap_mag), (int(sx), int(sy)), r)

                is_match = result.matched and star is result.star and not planet_wins
                if is_match:
                    pygame.draw.circle(screen, MATCH, (int(sx), int(sy)), r + 6, 2)
                if show_labels and (is_match or star.ap_mag <= LABEL_MAG_LIMIT):
                    color = MATCH if is_match else DIM
                    screen.blit(small.render(star.name, True, color), (sx + r + 4, sy - 7))

            # -- planets (drawn over stars; always labeled - there are only seven) --
            for name, ra_h, dec, dist in planet_cache:
                d = math.radians(dec)
                pos = to_screen(math.radians(ra_h * 15), math.sin(d), math.cos(d))
                if pos is None:
                    continue
                sx, sy = int(pos[0]), int(pos[1])
                color, mag = PLANET_STYLE.get(name.lower(), ((220, 220, 220), 1.0))
                r = star_radius(mag) + 1
                pygame.draw.circle(screen, color, (sx, sy), r)
                pygame.draw.circle(screen, color, (sx, sy), r + 3, 1)     # halo = "not a star"
                hit = planet_wins and planet_hit[0][0] == name
                if hit:
                    pygame.draw.circle(screen, MATCH, (sx, sy), r + 8, 2)
                if show_labels or hit:
                    screen.blit(small.render(name, True, MATCH if hit else color),
                                (sx + r + 6, sy - 7))

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
                f"Sync {sync_source or '?'}   alt offset {alt_offset:+.2f}",
            ], 20, 20, HUD)
            if planet_wins:
                (name, ra_h, dec, dist), sep = planet_hit
                info = [f"Pointing at: {name}",
                        f"  RA {ra_h:.3f}h  Dec {dec:+.2f}",
                        f"  distance {dist:.3f} AU",
                        f"  off-axis {sep:.2f} deg"]
                info_color = MATCH
            else:
                info = starfinder.format_result(result).splitlines()
                info_color = MATCH if result.matched else HUD
            draw_lines(screen, font, info, 20,
                       HEIGHT - 20 - bottom_reserved - 17 * len(info), info_color)

        # -- transient sync status --
        if status_lines and pygame.time.get_ticks() / 1000.0 < status_until:
            draw_lines(screen, font, status_lines, *status_pos, status_color)

        draw_lines(screen, small, hint_lines, *hint_pos, DIM, line_h=15)

        if streamer and frame % STREAM_EVERY == 0:
            streamer.publish(screen)            # canvas, so the Mac sees it upright
        present(physical, screen, rotate)
        frame += 1
        clock.tick(FPS)

    imu.close()
    pygame.quit()


if __name__ == "__main__":
    main()