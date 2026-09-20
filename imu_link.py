"""
Mac side: launch the IMU script on the Pi over SSH and keep the latest reading.

The Pi script must print one JSON object per line, e.g.
    print(json.dumps({"t": time.time(), "alt": alt, "az": az, "q": q}), flush=True)

Usage from your viewer / starfinder code:
    from imu_link import IMULink

    imu = IMULink()          # starts ssh in the background
    reading = imu.latest     # dict or None; never blocks
"""
import json
import subprocess
import threading
import time
from pathlib import Path
import starfinder
from datetime import datetime, timezone

PI = "resolut@lars.local"
REMOTE_CMD = "cd ~/astroscope && ~/astroscope-venv/bin/python3 -u imu_stream.py"  # venv python; -u: no buffering
BASE_DIR = Path(__file__).resolve().parent
DEFAULT_CATALOG = BASE_DIR / "stars.csv"
catalog = starfinder.load_catalog(DEFAULT_CATALOG)

class IMULink:
    def __init__(self, host: str = PI, cmd: str = REMOTE_CMD):
        self.latest = None          # most recent parsed reading
        self.needs_sync = True      # set again whenever the Pi reports a sensor reset
        self.offset = 0.0           # degrees added to raw az to get true az
        self.received_at = None     # Mac-side time it arrived (for staleness checks)
        self._proc = subprocess.Popen(
            ["ssh", "-o", "ServerAliveInterval=5", host, cmd],
            stdout=subprocess.PIPE,
            text=True,
            bufsize=1,              # line-buffered on our end
        )
        threading.Thread(target=self._reader, daemon=True).start()

    def _reader(self):
        for line in self._proc.stdout:          # blocks here, not in your main loop
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue                        # driver debug dumps, warnings, etc.
            if msg.get("event") == "reset":
                self.needs_sync = True          # heading reference is gone; old offset is invalid
            elif "alt" in msg:
                self.latest = msg
                self.received_at = time.monotonic()

    def sync(self, true_az: float = 180.0) -> None:
        """Call while the tube points at a known azimuth (default: due south).
        Stores the offset between what the IMU reads and the truth."""
        if self.latest is None:
            raise RuntimeError("no IMU reading yet")
        self.offset = (true_az - self.latest["az"]) % 360
        self.needs_sync = False

    def pointing(self):
        """(alt, true_az) with the sync offset applied, or None if unusable."""
        if self.latest is None or self.stale or self.needs_sync:
            return None
        return self.latest["alt"], (self.latest["az"] + self.offset) % 360

    @property
    def stale(self) -> bool:
        """True if nothing has arrived for 1 s (Pi script died, Wi-Fi hiccup...)."""
        return self.received_at is None or time.monotonic() - self.received_at > 1.0

    def close(self):
        self._proc.terminate()


if __name__ == "__main__":
    # Demo: press Enter while the tube points due south to sync.
    last_name = None
    last_print = 0.0
    PRINT_INTERVAL = 1.5   # seconds
    imu = IMULink()

    def wait_for_enter():
        while True:
            input()
            try:
                imu.sync(180.0)
                print(">>> synced to south")
            except RuntimeError:
                print(">>> no IMU data yet, try again")

    threading.Thread(target=wait_for_enter, daemon=True).start()
    try:
        while True:
            p = imu.pointing()
            if imu.stale:
                print("waiting for IMU...")
            elif imu.needs_sync:
                print(f"NOT SYNCED - point due south, press Enter   (raw az={imu.latest['az']:6.2f})")
            else:
                now = time.monotonic()
                if now - last_print >= PRINT_INTERVAL:
                    print(f"alt={p[0]:6.2f}  az={p[1]:6.2f}")
                    last_print = now

                curr_input = (
                    41.495, #lat
                    -81.535, #lon
                    220, #elev
                    datetime.now(timezone.utc), #utc
                    p[0], #pointing altitude
                    p[1], # pointing azimuth
                )
                result = starfinder.identify_star(*curr_input, catalog=catalog)
                name = result.star.name if result.matched else None
                if name != last_name:
                    print(starfinder.format_result(result))
                    last_name = name


            

            time.sleep(0.5)
    except KeyboardInterrupt:
        imu.close()
        