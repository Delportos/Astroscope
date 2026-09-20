from datetime import datetime, timezone
import math


def julian_date(utc: datetime):
    jd = 0
    if utc.tzinfo is None:
        utc = utc.replace(tzinfo=timezone.utc)
        
    y,m = utc.year, utc.month
    d = (utc.day
         + utc.hour/24
         +utc.minute / 1440
         + utc.second / 86400)
    if m <= 2:
        y -= 1
        m += 12
    a = y//100
    b = 2 - a + a//4
    jd = (math.floor(365.25 * (y+4716))
                +math.floor(30.6001 *(m+1))
                + d + b - 1524.5)
    return jd



if __name__ == "__main__":
    now = datetime.now(timezone.utc)
    today = julian_date(now)
    print(f"The current julian date is: {today} ")