"""
Annotation automatique des pics d'un spectre de masse.

Deux modes :
- masse théorique M fournie par l'utilisateur : un pic est annoté par un adduit
  si son m/z correspond au m/z théorique de cet adduit dans la polarité du spectre ;
- repli si rien ne correspond (ou si M est inconnue) : annotation fondée uniquement
  sur les différences de masse entre deux pics du même spectre — si l'écart entre
  deux pics correspond à l'écart entre deux adduits de même polarité
  (ex. [M+Na]+ - [M+H]+ = 21.9819 Da), le pic le plus bas reçoit l'adduit le plus
  léger et le pic le plus haut l'adduit le plus lourd.
"""

from .adducts import ADDUCTS, neutral_mass

DEFAULT_TOLERANCE_PPM = 10.0


def theoretical_mz(mass: float, adduct: dict) -> float:
    """m/z théorique de l'ion formé par l'adduit pour une masse neutre M."""
    z = abs(adduct.get("z", 1))
    n = adduct.get("n", 1)
    return (n * mass + adduct["mass"]) / z


def ppm_error(mz: float, mz_theoretical: float) -> float:
    return abs(mz - mz_theoretical) / mz_theoretical * 1e6


def _annotation(polarity: str, mz: float, adduct: dict) -> dict:
    mz = round(float(mz), 4)
    return {
        "polarity": polarity,
        "charge": adduct["z"],
        "mz": mz,
        "adduct": adduct["code"],
        "neutral_mass": neutral_mass(mz, adduct),
    }


def annotate_with_theoretical_mass(peaks, polarity: str, mass: float,
                                   tolerance_ppm: float = DEFAULT_TOLERANCE_PPM) -> list:
    """Annote, pour chaque adduit de la polarité, le pic le plus proche du m/z théorique de M."""
    claimed = {}
    for adduct in ADDUCTS.get(polarity, []):
        mz_th = theoretical_mz(mass, adduct)
        best_mz, best_err = None, None
        for mz in peaks:
            err = ppm_error(mz, mz_th)
            if best_mz is None or err < best_err:
                best_mz, best_err = mz, err
        if best_mz is not None and best_err <= tolerance_ppm:
            if best_mz not in claimed or best_err < claimed[best_mz][0]:
                claimed[best_mz] = (best_err, adduct)
    return [_annotation(polarity, mz, adduct) for mz, (_, adduct) in sorted(claimed.items())]


def annotate_with_mass_differences(peaks, polarity: str,
                                   tolerance_ppm: float = DEFAULT_TOLERANCE_PPM) -> list:
    """Annote les paires de pics dont l'écart de m/z correspond à l'écart entre deux adduits de même polarité."""
    adducts = [a for a in ADDUCTS.get(polarity, []) if a.get("n", 1) == 1]
    candidates = []
    ordered = sorted(float(mz) for mz in peaks)
    for i, mz_low in enumerate(ordered):
        for mz_high in ordered[i + 1:]:
            delta = mz_high - mz_low
            for adduct_low in adducts:
                for adduct_high in adducts:
                    if adduct_high["mass"] <= adduct_low["mass"] or adduct_high["z"] != adduct_low["z"]:
                        continue
                    expected = (adduct_high["mass"] - adduct_low["mass"]) / abs(adduct_low["z"])
                    err = ppm_error(delta, expected)
                    if err <= tolerance_ppm:
                        candidates.append((err, mz_low, adduct_low, mz_high, adduct_high))
    assigned = {}
    for err, mz_low, adduct_low, mz_high, adduct_high in sorted(candidates, key=lambda c: c[0]):
        if mz_low in assigned or mz_high in assigned:
            continue
        assigned[mz_low] = adduct_low
        assigned[mz_high] = adduct_high
    return [_annotation(polarity, mz, adduct) for mz, adduct in sorted(assigned.items())]


def annotate_peaks(peaks_by_polarity: dict, theoretical_mass: float = None,
                   tolerance_ppm: float = DEFAULT_TOLERANCE_PPM) -> list:
    """
    Annote automatiquement les pics d'un spectre.

    Args:
        peaks_by_polarity: dict {'positive': [m/z, ...], 'negative': [m/z, ...]}
        theoretical_mass: masse théorique M fournie par l'utilisateur (None si inconnue)
        tolerance_ppm: tolérance de correspondance en ppm

    Returns:
        liste d'annotations {'polarity', 'charge', 'mz', 'adduct', 'neutral_mass'} ;
        si la masse théorique ne correspond à aucun pic (ou est absente), repli sur
        les différences de masse entre deux pics.
    """
    annotations = []
    if theoretical_mass is not None:
        for polarity, peaks in peaks_by_polarity.items():
            annotations.extend(annotate_with_theoretical_mass(peaks, polarity, theoretical_mass, tolerance_ppm))
    if not annotations:
        for polarity, peaks in peaks_by_polarity.items():
            annotations.extend(annotate_with_mass_differences(peaks, polarity, tolerance_ppm))
    return annotations