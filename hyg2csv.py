"""
Pulls data from hyg and puts into my stars.csv. 

Columns: self (source)
hip (hip) -- acts as a join key back to any future data bases so this is very helpful
name (proper-> bayer+con -> flam + con -> HR + nn)
ra_hours(ra)
dec_degrees (dec)
pmra_mas (pmra)
pmdec_mas (pmdec)
distance_ly = (dist * 3.26156) ignore anything over 100000 pc because this is not a real reading
ap_mag (mag)
constellation (con)
c_index (ci)
"""
import csv
import re

INFILE = '/Users/frankgallo/Desktop/astroscopeonmac/astroscope/hyglike_from_athyg_v32.csv'
OUTFILE = 'astroscope/stars.csv'
MAGLIM = 4.5
PC_TO_LY = 3.26156
OUT_FIELDS = ["hip","name","ra_hours","dec_degrees","pmra_mas",
              "pmdec_mas","distance_ly","ap_mag","constellation","c_index"]
GREEK = {

    "Alp": "Alpha",   "Bet": "Beta",    "Gam": "Gamma",   "Del": "Delta",
    "Eps": "Epsilon", "Zet": "Zeta",    "Eta": "Eta",     "The": "Theta",
    "Iot": "Iota",    "Kap": "Kappa",   "Lam": "Lambda",  "Mu":  "Mu",
    "Nu":  "Nu",      "Xi":  "Xi",      "Omi": "Omicron", "Pi":  "Pi",
    "Rho": "Rho",     "Sig": "Sigma",   "Tau": "Tau",     "Ups": "Upsilon",
    "Phi": "Phi",     "Chi": "Chi",     "Psi": "Psi",     "Ome": "Omega",
}
CON_GENITIVE = {
    "And": "Andromedae",        "Ant": "Antliae",
    "Aps": "Apodis",            "Aqr": "Aquarii",
    "Aql": "Aquilae",           "Ara": "Arae",
    "Ari": "Arietis",           "Aur": "Aurigae",
    "Boo": "Bootis",            "Cae": "Caeli",
    "Cam": "Camelopardalis",    "Cnc": "Cancri",
    "CVn": "Canum Venaticorum", "CMa": "Canis Majoris",
    "CMi": "Canis Minoris",     "Cap": "Capricorni",
    "Car": "Carinae",           "Cas": "Cassiopeiae",
    "Cen": "Centauri",          "Cep": "Cephei",
    "Cet": "Ceti",              "Cha": "Chamaeleontis",
    "Cir": "Circini",           "Col": "Columbae",
    "Com": "Comae Berenices",   "CrA": "Coronae Australis",
    "CrB": "Coronae Borealis",  "Crv": "Corvi",
    "Crt": "Crateris",          "Cru": "Crucis",
    "Cyg": "Cygni",             "Del": "Delphini",
    "Dor": "Doradus",           "Dra": "Draconis",
    "Equ": "Equulei",           "Eri": "Eridani",
    "For": "Fornacis",          "Gem": "Geminorum",
    "Gru": "Gruis",             "Her": "Herculis",
    "Hor": "Horologii",         "Hya": "Hydrae",
    "Hyi": "Hydri",             "Ind": "Indi",
    "Lac": "Lacertae",          "Leo": "Leonis",
    "LMi": "Leonis Minoris",    "Lep": "Leporis",
    "Lib": "Librae",            "Lup": "Lupi",
    "Lyn": "Lyncis",            "Lyr": "Lyrae",
    "Men": "Mensae",            "Mic": "Microscopii",
    "Mon": "Monocerotis",       "Mus": "Muscae",
    "Nor": "Normae",            "Oct": "Octantis",
    "Oph": "Ophiuchi",          "Ori": "Orionis",
    "Pav": "Pavonis",           "Peg": "Pegasi",
    "Per": "Persei",            "Phe": "Phoenicis",
    "Pic": "Pictoris",          "Psc": "Piscium",
    "PsA": "Piscis Austrini",   "Pup": "Puppis",
    "Pyx": "Pyxidis",           "Ret": "Reticuli",
    "Sge": "Sagittae",          "Sgr": "Sagittarii",
    "Sco": "Scorpii",           "Scl": "Sculptoris",
    "Sct": "Scuti",             "Ser": "Serpentis",
    "Sex": "Sextantis",         "Tau": "Tauri",
    "Tel": "Telescopii",        "Tri": "Trianguli",
    "TrA": "Trianguli Australis", "Tuc": "Tucanae",
    "UMa": "Ursae Majoris",     "UMi": "Ursae Minoris",
    "Vel": "Velorum",           "Vir": "Virginis",
    "Vol": "Volantis",          "Vul": "Vulpeculae",
}

SUPERSCRIPT = str.maketrans("0123456789", "⁰¹²³⁴⁵⁶⁷⁸⁹")

_BAYER_RE = re.compile(r"^([A-Za-z]+)\s*(\d*)$")

def expand_bayer(raw, use_superscript=False):
    """'Alp' -> 'Alpha';  'Alp1' -> 'Alpha1' or 'Alpha¹'."""
    if not raw:
        return None
    m = _BAYER_RE.match(raw.strip())
    if not m:
        return raw.strip()
    letter, sup = m.group(1), m.group(2)
    name = GREEK.get(letter, letter)
    if not sup:
        return name
    return name + (sup.translate(SUPERSCRIPT) if use_superscript else sup)
def transform(row):
    return {
        "hip": row["hip"],
        "name": make_name(row),
        "ra_hours": row["ra"],
        "dec_degrees": row["dec"],
        "pmra_mas": row["pmra"],
        "pmdec_mas": row["pmdec"],
        "distance_ly": to_ly(row["dist"]),
        "ap_mag": row["mag"],
        "constellation": row["con"],
        "c_index": row["ci"],
    }

def make_name(row):
    if row["proper"]:
        return row["proper"]

    con = CON_GENITIVE.get(row["con"], row["con"])

    if row["bayer"]:
        return f"{expand_bayer(row['bayer'])} {con}"
    if row["flam"]:
        return f"{row['flam']} {con}"
    if row["hr"]:
        return f"HR {row['hr']}"
    if row["hip"]:
        return f"HIP {row['hip']}"
    return f"HYG {row['id']}"

def to_float(s):
    return float(s) if s not in ("", None) else None

def keep(row):
    if row["id"] == '0':
        return False
    mag = to_float(row["mag"])
    if mag > MAGLIM:
        return False
    if to_float(row["ra"]) is None or to_float(row["dec"]) is None:
        return False
    return True

def to_ly(dist_str):
    pc = to_float(dist_str)
    if pc is None or pc >= 100000:
        return ""
    return round(pc * PC_TO_LY, 3)

with open(INFILE, mode='r',newline='',encoding='utf-8') as infile:
    with open(OUTFILE,mode='w',newline='',encoding='utf-8') as outfile:
        reader = csv.DictReader(infile)
        writer = csv.DictWriter(outfile,fieldnames=OUT_FIELDS,extrasaction='ignore')
        writer.writeheader()
        for row in reader:
            if keep(row):
                writer.writerow(transform(row))