"""
pp3_renderer.py

Generates PP3 (.pp3) input scripts for arbitrary sky pointings and drives
them through the PP3 -> LaTeX -> dvips pipeline to produce a chart image.

Why this exists
----------------
PP3's input format is a small scripting language read from a text file --
there's no CLI flag for "give me a chart at RA 5.5h, Dec +20, 9 degree FOV".
To drive it from a pointing loop (Astroscope's RA/Dec -> nearest star ->
render step), we need to:

    1. Translate (RA, Dec, FOV) into PP3's actual parameters
    2. Write that out as a .pp3 script
    3. Invoke the pp3 binary against it, with PP3DATA set correctly
    4. Return the resulting chart file, or a clear error if the LaTeX
       stage failed (which, per your build, is the most likely failure
       point -- missing packages, not PP3 itself).

FOV translation
----------------
PP3 has two relevant settings:
    grad_per_cm  : degrees of sky represented per cm of paper
    box_width / box_height : physical plot size, in cm

There's no direct "FOV" knob. We fix a physical box size (box_size_cm)
and solve for the scale that makes that box span your desired FOV:

    grad_per_cm = fov_deg / box_size_cm

This keeps box_size_cm constant across calls (so output files are
consistently sized/proportioned) while letting the caller reason in
degrees, which is what actually matters when you're pointing a device
at the sky.
"""

import os
import subprocess
import tempfile
from pathlib import Path


class PP3Error(RuntimeError):
    """Raised when script generation or any pipeline stage fails."""


class PP3Renderer:
    # Abbreviation -> Latin name, from PP3's own manual (Appendix C).
    # This is what lets label_constellation="LEO" turn into an actual
    # printed name -- PP3 itself has no such lookup built in, it only
    # knows abbreviations internally (for boundaries/highlighting).
    CONSTELLATION_NAMES = {
        "AND": "Andromeda", "ANT": "Antlia", "APS": "Apus", "AQR": "Aquarius",
        "AQL": "Aquila", "ARA": "Ara", "ARI": "Aries", "AUR": "Auriga",
        "BOO": "Bo\\\"otes", "CAE": "Caelum", "CAM": "Camelopardalis",
        "CNC": "Cancer", "CVN": "Canes Venatici", "CMA": "Canis Major",
        "CMI": "Canis Minor", "CAP": "Capricornus", "CAR": "Carina",
        "CAS": "Cassiopeia", "CEN": "Centaurus", "CEP": "Cepheus",
        "CET": "Cetus", "CHA": "Chamaeleon", "CIR": "Circinus",
        "COL": "Columba", "COM": "Coma Berenices", "CRA": "Corona Australis",
        "CRB": "Corona Borealis", "CRV": "Corvus", "CRT": "Crater",
        "CRU": "Crux", "CYG": "Cygnus", "DEL": "Delphinus", "DOR": "Dorado",
        "DRA": "Draco", "EQU": "Equuleus", "ERI": "Eridanus", "FOR": "Fornax",
        "GEM": "Gemini", "GRU": "Grus", "HER": "Hercules", "HOR": "Horologium",
        "HYA": "Hydra", "HYI": "Hydrus", "IND": "Indus", "LAC": "Lacerta",
        "LEO": "Leo", "LMI": "Leo Minor", "LEP": "Lepus", "LIB": "Libra",
        "LUP": "Lupus", "LYN": "Lynx", "LYR": "Lyra", "MEN": "Mensa",
        "MIC": "Microscopium", "MON": "Monoceros", "MUS": "Musca",
        "NOR": "Norma", "OCT": "Octans", "OPH": "Ophiuchus", "ORI": "Orion",
        "PAV": "Pavo", "PEG": "Pegasus", "PER": "Perseus", "PHE": "Phoenix",
        "PIC": "Pictor", "PSC": "Pisces", "PSA": "Pisces Austrinus",
        "PUP": "Puppis", "PYX": "Pyxis", "RET": "Reticulum", "SGE": "Sagitta",
        "SGR": "Sagittarius", "SCO": "Scorpius", "SCL": "Sculptor",
        "SCT": "Scutum", "SER1": "Serpens Caput", "SER2": "Serpens Cauda",
        "SEX": "Sextans", "TAU": "Taurus", "TEL": "Telescopium",
        "TRI": "Triangulum", "TRA": "Triangulum Australe", "TUC": "Tucana",
        "UMA": "Ursa Major", "UMI": "Ursa Minor", "VEL": "Vela",
        "VIR": "Virgo", "VOL": "Volans", "VUL": "Vulpecula",
    }

    def __init__(self, pp3_binary, pp3_data_dir):
        """
        pp3_binary   : path to the compiled `pp3` executable
        pp3_data_dir : directory containing PP3's .dat files (stars,
                       nebulae, milky way, etc). This becomes PP3DATA.
        """
        self.pp3_binary = Path(pp3_binary).resolve()
        self.pp3_data_dir = Path(pp3_data_dir).resolve()

        if not self.pp3_binary.exists():
            raise FileNotFoundError(f"pp3 binary not found: {self.pp3_binary}")
        if not self.pp3_data_dir.is_dir():
            raise FileNotFoundError(f"PP3 data dir not found: {self.pp3_data_dir}")

    # PP3 colors are `color <object> R G B`, each channel 0-1. Object colors
    # aren't independent of each other -- they're calibrated as a set against
    # a particular background. Swap background alone and stars/labels using
    # PP3's defaults (meant for dark blue) become invisible or nearly so
    # against white. So these are defined as complete palettes, not
    # individual overridable knobs.
    #
    # "dark" reproduces PP3's original night-sky-planetarium look.
    # "white" is a print-style palette (black ink on white) -- this is the
    # one you want for a sunlight-readable Sharp Memory LCD, since that
    # display is reflective and works like paper, not like a backlit screen.
    COLOR_SCHEMES = {
        "dark": {
            "background": (0.0, 0.0, 0.55),
            "stars": (1.0, 1.0, 1.0),
            "labels": (1.0, 1.0, 1.0),
            "constellation_lines": (0.5, 0.5, 0.7),
            "grid": (0.3, 0.3, 0.5),
            "ecliptic": (0.7, 0.5, 0.2),
            "boundaries": (0.3, 0.3, 0.45),
            "milky_way": (0.15, 0.15, 0.35),
        },
        "white": {
            "background": (1.0, 1.0, 1.0),
            "stars": (0.0, 0.0, 0.0),
            "labels": (0.0, 0.0, 0.0),
            "constellation_lines": (0.7, 0.7, 0.7),
            "grid": (0.5, 0.5, 0.5),
            "ecliptic": (0.3, 0.3, 0.3),
            "boundaries": (0.8, 0.8, 0.8),
            "milky_way": (0.5, 0.5, 0.5),
        },
    }

    def _build_script(self, ra_hours, dec_deg, fov_deg, box_size_cm, name, output_format, color_scheme, label_constellation):
        grad_per_cm = fov_deg / box_size_cm

        if color_scheme not in self.COLOR_SCHEMES:
            raise ValueError(f"color_scheme must be one of {list(self.COLOR_SCHEMES)}, got {color_scheme!r}")
        palette = self.COLOR_SCHEMES[color_scheme]

        if label_constellation is not None and label_constellation not in self.CONSTELLATION_NAMES:
            raise ValueError(
                f"Unknown constellation abbreviation {label_constellation!r}. "
                f"Must be one of: {sorted(self.CONSTELLATION_NAMES)}"
            )

        lines = [
            f"# auto-generated for RA={ra_hours}h Dec={dec_deg}deg FOV={fov_deg}deg",
            f"set center_rectascension {ra_hours:.6f}",
            f"set center_declination {dec_deg:.6f}",
            f"set grad_per_cm {grad_per_cm:.6f}",
            f"set box_width {box_size_cm:.3f}",
            f"set box_height {box_size_cm:.3f}",
            "switch milky_way on",
        ]

        # White-on-black-ink printing doesn't need colored stars -- PP3's
        # colored_stars switch tints stars by spectral type, which reads
        # fine on a dark background but looks muddy/low-contrast in a
        # print-style palette. Turn it off for "white", leave it on for "dark".
        lines.append("switch colored_stars " + ("off" if color_scheme == "white" else "on"))

        for obj, (r, g, b) in palette.items():
            lines.append(f"color {obj} {r:.2f} {g:.2f} {b:.2f}")

        # The switch controls what PP3 asks LaTeX to produce. Omit both
        # for "tex" so PP3 stops after writing the .tex file -- useful
        # for debugging script generation without paying the LaTeX
        # compile cost every time.
        if output_format == "pdf":
            lines.append("switch pdf_output on")
        elif output_format == "eps":
            lines.append("switch eps_output on")

        if label_constellation is not None:
            # `set constellation` only recolors that constellation's
            # boundary line -- it does NOT print its name anywhere. The
            # actual visible name has to be placed by hand as a "flex"
            # text label (PP3's term for text that curves along a
            # declination circle -- meant for exactly this purpose).
            lines.append(f"set constellation {label_constellation}")

        lines.append(f"filename output {name}.tex")

        if label_constellation is not None:
            const_name = self.CONSTELLATION_NAMES[label_constellation]
            # Placed at the chart's own center rather than the
            # constellation's catalog center: at a small FOV pointed at
            # one star, the catalog center could easily fall outside the
            # visible box. Using the chart center guarantees the label
            # actually lands on the page.
            lines.append("objects_and_labels")
            lines.append(
                f'text "\\\\bfseries {const_name}" at {ra_hours:.6f} {dec_deg:.6f} '
                f"along declination towards N ;"
            )

        return "\n".join(lines) + "\n"

    def render(self, ra_hours, dec_deg, fov_deg=9.0, box_size_cm=10.0,
               name="chart", output_format="pdf", work_dir=None, timeout=60,
               color_scheme=None, label_constellation=None):
        """
        Render a chart centered at (ra_hours, dec_deg).

        ra_hours      : 0-24, decimal hours (PP3's native RA unit -- not degrees)
        dec_deg       : -90 to 90, decimal degrees
        fov_deg       : desired angular field of view in degrees. Since
                        PP3's scale is linear (deg/cm, not a true sky
                        projection), this is reliable for the FOV sizes
                        relevant to a star-ID device (a handful to a few
                        tens of degrees) but shouldn't be trusted near
                        180 degrees.
        box_size_cm   : physical page size PP3 renders to. Larger values
                        give more label/detail resolution at the same
                        FOV, at the cost of render time.
        output_format : "pdf", "eps", or "tex" (tex = skip LaTeX entirely)
        work_dir      : directory to render in. Defaults to a fresh temp
                        directory that is NOT auto-deleted, since the
                        caller needs the output file to still exist after
                        this call returns. Pass your own path if you want
                        to control/clean up scratch files yourself.
        timeout       : seconds before the pp3/LaTeX subprocess is killed.
                        Matters more once you're timing this on a Pi Zero
                        rather than your Mac.
        color_scheme  : "white" (black-on-white, print-style -- default,
                        good for the Sharp Memory LCD) or "dark" (PP3's
                        original white-on-dark-blue planetarium look).
        label_constellation : optional 3-letter abbreviation (e.g. "LEO",
                        "ORI", "UMA" -- see PP3Renderer.CONSTELLATION_NAMES
                        for the full list) of the constellation the current
                        pointing falls in. If given, its boundary gets
                        highlighted and its full name is printed on the
                        chart. PP3 itself has no notion of "the current
                        constellation" -- this is meant to be fed by
                        whatever step in your pipeline already knows which
                        constellation the nearest-star lookup landed in.

        Returns: Path to the rendered output file.
        """
        if not (0 <= ra_hours < 24):
            raise ValueError(f"ra_hours must be in [0, 24), got {ra_hours}")
        if not (-90 <= dec_deg <= 90):
            raise ValueError(f"dec_deg must be in [-90, 90], got {dec_deg}")
        if output_format not in ("pdf", "eps", "tex"):
            raise ValueError("output_format must be 'pdf', 'eps', or 'tex'")

        work_dir = Path(work_dir) if work_dir else Path(tempfile.mkdtemp(prefix="pp3_"))
        work_dir.mkdir(parents=True, exist_ok=True)

        script_text = self._build_script(
            ra_hours, dec_deg, fov_deg, box_size_cm, name, output_format,
            color_scheme, label_constellation,
        )
        script_path = work_dir / f"{name}.pp3"
        script_path.write_text(script_text)

        env = os.environ.copy()
        env["PP3DATA"] = str(self.pp3_data_dir)

        try:
            result = subprocess.run(
                [str(self.pp3_binary), script_path.name],
                cwd=work_dir,
                env=env,
                timeout=timeout,
                capture_output=True,
                text=True,
                # Feed EOF instead of leaving stdin attached to your
                # terminal. If LaTeX hits a missing-package prompt like
                # you saw earlier ("Type X to quit..."), EOF makes it
                # abort immediately with a fatal error instead of
                # hanging the pipeline waiting for input that will
                # never come in an automated context.
                stdin=subprocess.DEVNULL,
            )
        except subprocess.TimeoutExpired as e:
            raise PP3Error(
                f"pp3 render timed out after {timeout}s for RA={ra_hours} Dec={dec_deg}"
            ) from e

        output_path = work_dir / f"{name}.{output_format}"

        if result.returncode != 0 or not output_path.exists():
            log_path = work_dir / f"{name}.log"
            log_tail = ""
            if log_path.exists():
                log_tail = "\n".join(log_path.read_text(errors="replace").splitlines()[-25:])
            raise PP3Error(
                f"PP3 render failed (exit {result.returncode}) for "
                f"RA={ra_hours} Dec={dec_deg} FOV={fov_deg}.\n"
                f"--- stderr ---\n{result.stderr}\n"
                f"--- tail of {name}.log ---\n{log_tail}"
            )

        return output_path


if __name__ == "__main__":
    # Example usage -- adjust paths to match your build.
    renderer = PP3Renderer(
    pp3_binary="/Users/frankgallo/pp3/pp3",
    pp3_data_dir="/Users/frankgallo/pp3", 
    )

    # Simulated pointing loop: RA/Dec (and the constellation abbreviation)
    # would come from your nearest-star-lookup step instead of being
    # hardcoded here.
    chart_path = renderer.render(
        ra_hours=6.75,      # Leo region, roughly
        dec_deg=-15,
        fov_deg=35.0,
        color_scheme="dark",
        output_format="pdf",
        label_constellation="CMA",
        work_dir="./render_test",  # kept around so you can inspect it
    )

    print(f"Chart rendered to: {chart_path}")