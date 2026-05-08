import csv
import math
from pathlib import Path
from dataclasses import dataclass


@dataclass
class Planet:
    name: str
    e: float
    i_deg: float
    o_deg: float
    a_au: float
    n_degday: float
    p_deg: float
    L_deg: float
    epoch_jd_tdb: float


def load_catalog(path) -> dict[str, Planet]:
    planets = {}
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            p = Planet(
                name=row["name"],
                e=float(row["e"]),
                i_deg=float(row["i_deg"]),
                o_deg=float(row["o_deg"]),
                a_au=float(row["a_au"]),
                n_degday=float(row["n_degday"]),
                p_deg=float(row["p_deg"]),
                L_deg=float(row["L_deg"]),
                epoch_jd_tdb=float(row["epoch_jd_tdb"]),
            )
            planets[p.name] = p
    return planets


def heliocentric_xyz(planet: Planet, d: float) -> tuple[float, float, float]:
    e = planet.e
    a = planet.a_au
    n = planet.n_degday
    L = planet.L_deg
    p = planet.p_deg
    o = planet.o_deg
    i = planet.i_deg

    # Mean anomaly (degrees, then radians)
    M_deg = (n * d + L - p) % 360
    M = math.radians(M_deg)

    # True anomaly via Equation of Centre (radians)
    v = M + (
        (2*e - e**3/4) * math.sin(M)
        + (5/4) * e**2 * math.sin(2*M)
        + (13/12) * e**3 * math.sin(3*M)
    )

    # Radius vector
    r = a * (1 - e**2) / (1 + e * math.cos(v))

    # Convert remaining angles to radians
    o_rad = math.radians(o)
    i_rad = math.radians(i)
    p_rad = math.radians(p)
    u = v + p_rad - o_rad   # argument of latitude

    x = r * (math.cos(o_rad) * math.cos(u) - math.sin(o_rad) * math.sin(u) * math.cos(i_rad))
    y = r * (math.sin(o_rad) * math.cos(u) + math.cos(o_rad) * math.sin(u) * math.cos(i_rad))
    z = r * math.sin(u) * math.sin(i_rad)
    return x, y, z


def planet_radec(planet: Planet, earth: Planet, jd: float) -> tuple[float, float, float]:
    """Returns (RA in hours, Dec in degrees, geocentric distance in AU)."""
    d_planet = jd - planet.epoch_jd_tdb
    d_earth  = jd - earth.epoch_jd_tdb

    px, py, pz = heliocentric_xyz(planet, d_planet)
    ex, ey, ez = heliocentric_xyz(earth, d_earth)

    # Geocentric ecliptic
    gx, gy, gz = px - ex, py - ey, pz - ez

    # Rotate by obliquity to equatorial
    OBLIQ = math.radians(23.439292)
    xq = gx
    yq = gy * math.cos(OBLIQ) - gz * math.sin(OBLIQ)
    zq = gy * math.sin(OBLIQ) + gz * math.cos(OBLIQ)

    ra_deg   = math.degrees(math.atan2(yq, xq)) % 360
    ra_hours = ra_deg / 15
    dec_deg  = math.degrees(math.atan2(zq, math.sqrt(xq**2 + yq**2)))
    distance = math.sqrt(xq**2 + yq**2 + zq**2)
    return ra_hours, dec_deg, distance


if __name__ == "__main__":
    SCRIPT_DIR = Path(__file__).parent
    planets = load_catalog(SCRIPT_DIR / "planets.csv")
    print("Keys:", list(planets.keys()))
    print("Repr:", [repr(k) for k in planets.keys()])
    ra, dec, dist = planet_radec(planets["venus"], planets["earth"], jd=2461169.54167)
    print(f"Venus:   RA = {ra:.4f} hr  Dec = {dec:.4f}°  dist = {dist:.4f} AU")

    ra, dec, dist = planet_radec(planets["jupiter"], planets["earth"], jd=2461169.54167)
    print(f"Jupiter: RA = {ra:.4f} hr  Dec = {dec:.4f}°  dist = {dist:.4f} AU")