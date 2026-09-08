from flask import Flask, request, jsonify, render_template
from datetime import datetime, timezone

from starfinder import(
    load_catalog,
    local_sidereal_time,
    altaz_to_radec,
    identify_star
)

app = Flask(__name__)

CATALOG = load_catalog("stars.csv")

DEFAULT_LAT = 41.3286
DEFAULT_LON = 81.6919
DEFAULT_ELEV=350

@app.route("/")
def index():
    return render_template(
        "index.html",
        default_lat = DEFAULT_LAT,
        default_lon = DEFAULT_LON
    )

@app.route("/api/point", methods=["POST"])
def point():
    data = request.get_json(force=True)

    try: 
        alt = float(data["alt"])
        az = float(data["az"])
        lat = float(data.get("lat", DEFAULT_LAT))
        lon = float(data.get("lon", DEFAULT_LON))
    except (KeyError,TypeError,ValueError):
        return jsonify({"error": "alt/az/lat/lon must all be numbers"}), 400

    utc_now = datetime.now(timezone.utc)

    lst = local_sidereal_time(utc_now,lon)
    ra_hours, dec_degrees = altaz_to_radec(alt,az, lat, lst)


    result_text = identify_star(lat,lon,DEFAULT_ELEV,utc_now,alt,az,catalog=CATALOG)

    return jsonify({
        "utc": utc_now.strftime("%Y-%m-%d %H:%M:%S UTC"),
        "ra_hours": ra_hours,
        "dec_degrees": dec_degrees,
        "result_text": result_text,
    })
 
 
if __name__ == "__main__":
    app.run(debug=True, port=5050)
 
