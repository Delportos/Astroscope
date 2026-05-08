import numpy as np
import csv
import math
from datetime import datetime, timezone
from dataclasses import dataclass

@dataclass
class Star:
    name: str
    ra_hours: float
    dec_degrees: float
    distance_ly: float
    magnitude: float
    constellation: str

def load_catalog(path):
    stars = []
    with open(path, newline="",encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            stars.append(Star(
                name=row["name"],
                ra_hours=float(row["ra_hours"]),
                dec_degrees=float(row["dec_degrees"]),
                distance_ly=float(row["distance_ly"]),
                magnitude=float(row["magnitude"]),
                constellation=row["constellation"],
                ))
    return stars

# step 1: local sidereal time

def local_sidereal_time(utc: datetime, longitude_deg: float) -> float:
    if utc.tzinfo is None:
        utc = utc.replace(tzinfo=timezone.utc)

    y,m = utc.year, utc.month
    d = (utc.day 
             + utc.hour / 24 
             + utc.minute / 1440 
             + utc.second / 86400)
    if m <= 2:
            y -= 1
            m += 12
    a = y//100
    b = 2 - a + a//4
    jd = (math.floor(365.25 * (y+4716))
              +math.floor(30.6001 *(m+1))
              + d + b - 1524.5)
        
        # Centuries since J2000
    t = (jd - 2451545.0) / 36525.0

        #Greenwich mean sidereal time in degrees
    gmst_deg = (280.46061837
                    + 360.98564736629 * (jd - 2451545.0)
                    + 0.000387933 * t * t
                    - t * t * t / 38710000.0)
        
        #normalize to [0,360]
    gmst_deg %= 360
    if gmst_deg < 0:
            gmst_deg += 360
        
        #observers longitude  (east positive)
    lst_deg = (gmst_deg + longitude_deg) % 360

        #convert to hours
    return lst_deg / 15.0

# Alt/Az -> RA/Dec
def altaz_to_radec(alt_deg: float, az_deg: float, lat_deg: float, lst_hours:float) -> tuple[float,float]:

    """
    Converting horizontal coordinates (alt, az) to equatorial (ra_hours, dec_degrees)
    Azimuth is measured clockwise from north (0 = N, 90 = E, 180 = S, 270 = W).

    
    Azimuth is θ
    Altitude is φ 

    Derivation: spherical triangle with vertices at the celestial pole, the zenith, and the star. Standard Transform

    This takes you azimuth and your altitude where you're pointing, and translates them to the absolute right ascension and declination on the celestial sphere
    """

    alt = math.radians(alt_deg) #a
    az = math.radians(az_deg) #A
    lat = math.radians(lat_deg) #phi

    # Declination: 
    sin_dec = (math.sin(alt) * math.sin(lat)
               + math.cos(alt) * math.cos(lat) * math.cos(az)) #sin(δ) = sin(a)sin(A)+cos(a)cos(φ)cos(A)
    dec = math.asin(sin_dec) # δ = arcsin(sin(δ))

    #Hour angle, atan2 handles the quadrant correctly,
    #bug prone part of doing this with plan atan

    sin_h = -math.sin(az) * math.cos(alt)
    cos_h = (math.sin(alt) - math.sin(lat) * sin_dec) / math.cos(lat)
    hour_angle = math.atan2(sin_h, cos_h) # radians

    #RA = LST - hour angle. Convert hour angle from rad -> hours.
    ha_hours = math.degrees(hour_angle) / 15.0
    ra_hours = (lst_hours - ha_hours) % 24

    return ra_hours, math.degrees(dec)



# step 3: Angular Distance

def angular_distance(ra1_h: float, dec1_d: float,
                     ra2_h: float, dec2_d: float) -> float:
    """
    Great-circle angular distance between two sky points, in degrees.
    Uses the dot-product method on unit vectors - numerically robust and
    avoids the precision problems the haversine has near 0 or 180
    """
    # RA in hours -> degrees -> radians
    ra1 = math.radians(ra1_h * 15)
    ra2 = math.radians(ra2_h * 15)
    dec1 = math.radians(dec1_d)
    dec2 = math.radians(dec2_d)

    #convert each to a 3d unit vector on the celestial sphere!
    x1 = math.cos(dec1) * math.cos(ra1)
    y1 = math.cos(dec1) * math.sin(ra1)
    z1 = math.sin(dec1)

    x2 = math.cos(dec2) * math.cos(ra2)
    y2 = math.cos(dec2) * math.sin(ra2)
    z2 = math.sin(dec2)

    dot = max(-1.0,min(1.0,x1*x2 + y1*y2 + z1*z2))
    return math.degrees(math.acos(dot))

#step 4: find our nearest star

def find_nearest_star(catalog: list[Star],
                      ra_hours:float, dec_degrees: float,
                      tolerance_deg: float = 10.0
                    ) -> tuple[Star, float] | None:
    
    """
    Return (star, angular_distance_deg) of the closest catalog mathc,
    or None if nothing is within our tolerance.
    """

    best = None
    best_dist=float("inf")
    for star in catalog:
        d = angular_distance(ra_hours,dec_degrees,
                             star.ra_hours,star.dec_degrees) #finds the distance between where you're pointing, and then nearest star
        if d < best_dist:
            best_dist = d
            best = star
    if best_dist > tolerance_deg:
        return None
    return best, best_dist
    

# step 5: End to end Identify

def identify_star(lat_deg: float, lon_deg: float, alt_m: float,
                  utc:datetime,
                  pointing_alt_deg: float, pointing_az_deg: float,
                  catalog: list[Star]
) -> str:
    """
    Top level: take our observerstat and pointing direction, return a human string!
    NoteL alt_m(elevation) is not used in this prototype - it woudl only matter if we corrected 
    for atmospheric refraction or parallax for nearby objects
    """

    lst = local_sidereal_time(utc, lon_deg)
    ra, dec = altaz_to_radec(pointing_alt_deg, pointing_az_deg,
                             lat_deg, lst)
    result = find_nearest_star(catalog,ra, dec)
    if result is None:
        return f"No bright star is within your point.\n" \
        f" (Pointing at RA {ra:0.2f}h, Dec{dec:+0.2f}°)"
    
    star, dist = result
    light_year_to_year_string = (
        f"Light from this star left in {utc.year - int(star.distance_ly)}"
        if star.distance_ly < 3000 else
        f"Light from this star left ~{int(star.distance_ly)} years ago"
    )

    return (
        f"Pointing at: {star.name}\n"
        f" Constellation: {star.constellation}\n "
        f" Apparent mag: {star.magnitude:+.2f}\n "
        f" Distance: {star.distance_ly:0.1f} ly " 
        f"({star.distance_ly / 3.262:.1f} pc)\n"
        f" RA/Dec: {star.ra_hours:.3f}h/{star.dec_degrees:+.3f}°\n"
        f" Off-axis by: {dist:.2f}°\n"
        f" {light_year_to_year_string}"
    )

def stars_i_can_look_at(lat_deg:float,lon_deg:float, alt_m: float, utc:datetime, pointing_alt_deg:float, pointing_az_deg:float, catalog:list[Star])->str:
    lst = local_sidereal_time(utc,lon_deg)
    visible = []
    for star in catalog:
        H_hours = (lst - star.ra_hours) % 24
        H_rad = math.radians(H_hours * 15)

        lat_rad = math.radians(lat_deg)
        dec_rad = math.radians(star.dec_degrees)
        sin_alt = (math.sin(lat_rad) * math.sin(dec_rad)
                   + math.cos(lat_rad) * math.cos(dec_rad) * math.cos(H_rad)
                   )
        if sin_alt > 0:
            visible.append(star)
    return visible


# demo
if __name__ == "__main__":
    catalog = load_catalog("astroscope/stars.csv")

    test_input = (
        41.495, #lat
        -81.535, #lon
        220, #elev
        datetime(2026,4,29,1,38,0,tzinfo=timezone.utc), #utc
        7.5, #pointing altitude
        43.35, # pointing azimuth
    ) #should return vega

    test_input2 = (
        41.495, #lat
        -81.535, #lon
        220, #elev
        datetime(2026,5,2,1,40,0,tzinfo=timezone.utc), #utc
        41, #pointing altitude
        359, # pointing azimuth
    )

    print(identify_star(*test_input,catalog=catalog))
    print(identify_star(*test_input2,catalog=catalog))
    visible = stars_i_can_look_at(*test_input,catalog=catalog)
    print(f"{len(visible)} stars are currently above the horizon:")
    for star in visible:
        print(f"{star.name} ({star.constellation}) ")
 


"""
#debug

    lat, lon, alt_m, utc, p_alt, p_az = test_input
    lst = local_sidereal_time(utc, lon)
    ra, dec = altaz_to_radec(p_alt, p_az, lat, lst)
    print(f"Pointing at: RA {ra:.4f}h, Dec {dec:+.4f}°")
    print()
    print("Distance to each cataloged star:")
    for star in catalog:
        d = angular_distance(ra, dec, star.ra_hours, star.dec_degrees)
        print(f"  {star.name:<12} RA {star.ra_hours:6.3f}h  "
              f"Dec {star.dec_degrees:+6.2f}°  -->  {d:6.2f}° away")
    print()
    print(identify_star(*test_input, catalog=catalog))
"""