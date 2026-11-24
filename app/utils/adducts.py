"""
Adduits usuels en spectrométrie de masse (masses monoisotopiques de l'ion adduit, en Da).
mass = masse ajoutée à la masse neutre M pour former l'ion (négative pour [M-H]-).
Formule : m/z = (n * M + mass) / |z|   =>   M = (|z| * m/z - mass) / n
"""

ADDUCTS = {
    "+": [
        {"code": "M+H",         "label": "[M+H]⁺",       "mass": 1.007276,  "z": 1},
        {"code": "M+NH4",       "label": "[M+NH4]⁺",     "mass": 18.033823, "z": 1},
        {"code": "M+Na",        "label": "[M+Na]⁺",      "mass": 22.989218, "z": 1},
        {"code": "M+K",         "label": "[M+K]⁺",       "mass": 38.963158, "z": 1},
        {"code": "M+MeOH+H",    "label": "[M+MeOH+H]⁺",  "mass": 33.033491, "z": 1},
        {"code": "M+ACN+H",     "label": "[M+ACN+H]⁺",   "mass": 42.033823, "z": 1},
        {"code": "2M+H",        "label": "[2M+H]⁺",      "mass": 1.007276,  "z": 1, "n": 2},
        {"code": "2M+Na",       "label": "[2M+Na]⁺",     "mass": 22.989218, "z": 1, "n": 2},
    ],
    "-": [
        {"code": "M-H",         "label": "[M-H]⁻",       "mass": -1.007276,  "z": -1},
        {"code": "M+HCOO",      "label": "[M+HCOO]⁻",    "mass": 44.998201,  "z": -1},   # acide formique
        {"code": "M+Cl",        "label": "[M+Cl]⁻",      "mass": 34.969402,  "z": -1},
        {"code": "2M-H",        "label": "[2M-H]⁻",      "mass": -1.007276,  "z": -1, "n": 2},
    ],
}

def neutral_mass(mz: float, adduct: dict) -> float:
    """Masse neutre M correspondant à un pic m/z attribué à un adduit."""
    z = abs(adduct.get("z", 1))
    n = adduct.get("n", 1)
    return (z * mz - adduct["mass"]) / n

def find_adduct(polarity, key):
    """Match par code ('M+H')"""
    for adduct in ADDUCTS.get(polarity, []):
        if adduct["code"] == key:
            return adduct
    return None