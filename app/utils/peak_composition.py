import math

import numpy as np
import pyopenms as oms

FORMULA_RULES = ('hc', 'nops_c', 'nops', 'rdbe', 'integer_rdbe')
DEFAULT_RULES = frozenset(FORMULA_RULES)

ELEMENT_DB = oms.ElementDB.getInstance()
SUPPORTED_ELEMENTS = ('C', 'H', 'N', 'O', 'P', 'S', 'F', 'Cl', 'Br')
ISOTOPE_SPACING = 1.00335  # écart de masse 13C-12C (Da)

def default_max_counts(mass: float) -> dict:
    '''Bornes de comptage élémentaire selon la masse (règle 1 des Seven Golden Rules).'''
    if mass < 500:
        caps = {'C': 40, 'H': 80, 'N': 20, 'O': 20}
    elif mass < 1000:
        caps = {'C': 80, 'H': 130, 'N': 30, 'O': 30}
    elif mass < 2000:
        caps = {'C': 160, 'H': 250, 'N': 40, 'O': 70}
    else:
        caps = {'C': 180, 'H': 300, 'N': 60, 'O': 90}
    caps.update({
        'P': min(4, int(mass // 31)),
        'S': min(6, int(mass // 32)),
        'F': min(2, int(mass // 19)),
        'Cl': min(2, int(mass // 35)),
        'Br': min(1, int(mass // 79)),
    })
    return caps


def enumerate_formula_counts(mass: float, tol_da: float, max_counts: dict, min_counts: dict = None):
    '''Énumère toutes les compositions élémentaires dont la masse est à tol_da près de mass.

    Parcours récursif des éléments triés par masse décroissante (H en dernier, résolu
    directement), avec élagage sur la masse restante. Retourne (liste des comptages,
    liste des symboles dans le même ordre).'''
    min_counts = min_counts or {}
    
    order = sorted(max_counts, key=lambda s: ELEMENT_DB.getElement(s).getMonoWeight(), reverse=True)
    order = [s for s in order if s != 'H'] + ['H']
    els = [(s, ELEMENT_DB.getElement(s).getMonoWeight(), int(max_counts[s])) for s in order]
    n = len(els)
    max_fill = [0.0] * (n + 1)
    for i in range(n - 1, -1, -1):
        max_fill[i] = max_fill[i + 1] + els[i][1] * els[i][2]
    out = []
    counts = [0] * n

    def rec(i, rem):
        if i == n - 1:
            nh = int(round(rem / els[i][1]))
            if min_counts.get(els[i][0], 0) <= nh <= els[i][2] and abs(rem - nh * els[i][1]) <= tol_da:
                counts[i] = nh
                out.append(list(counts))
            return
        _, em, cap = els[i]
        kmax = min(cap, int((rem + tol_da) / em))
        kmin = max(min_counts.get(els[i][0], 0), max(0, math.ceil((rem - tol_da - max_fill[i + 1]) / em)))
        for k in range(kmin, kmax + 1):
            rem2 = rem - k * em
            if rem2 < -tol_da:
                break
            counts[i] = k
            rec(i + 1, rem2)
        counts[i] = 0

    rec(0, mass)
    return out, [e[0] for e in els]

def golden_rules_filter(counts: dict, target_mass: float, tol_ppm: float = 5.0,
                        hc_range=(0.1, 3.0), rdbe_range=(-1, 40), max_hetero_ratios=None,
                        rules=None):
    '''Filtre une composition élémentaire selon les Seven Golden Rules de Fiehn :
    erreur ppm max, ratio H/C, ratios hétéroatomes X/C, RDBE dans sa plage, et RDBE
    entier (règle LEWIS/SENIOR : H + halogènes + N + P doit être pair).

    Args:
        counts: dict {symbole: effectif}, ex. {'C': 6, 'H': 12, 'O': 6}
        target_mass: masse exacte cible (Da, monoisotopique, neutre)
        tol_ppm: erreur ppm max acceptée
        hc_range: plage du ratio H/C (appliquée si C > 0)
        rdbe_range: plage du RDBE (double bond equivalents)
        max_hetero_ratios: ratios max X/C (défaut N/C<=4, O/C<=3, P/C<=2, S/C<=3)

    Returns:
        dict {'formula', 'exact_mass',  'delta_mda', 'delta_ppm', 'rdbe', 'hc', 'counts'}, ou None si rejetée
    '''
    if rules is None:
        rules = DEFAULT_RULES
    rules = set(rules)
    if max_hetero_ratios is None:
        max_hetero_ratios = {'N': 4, 'O': 3, 'P': 2, 'S': 3}
    C = counts.get('C', 0)
    H = counts.get('H', 0)
    N = counts.get('N', 0)
    O = counts.get('O', 0)
    P = counts.get('P', 0)
    S = counts.get('S', 0)
    X = counts.get('F', 0) + counts.get('Cl', 0) + counts.get('Br', 0)
    formula_str = ''.join(f'{s}{counts[s]}' for s in SUPPORTED_ELEMENTS if counts.get(s))
    if not formula_str:
        return None
    ef = oms.EmpiricalFormula(formula_str)
    exact = ef.getMonoWeight()
    delta_da = (exact - target_mass)
    delta_ppm = delta_da / target_mass * 1e6
    if abs(delta_ppm) > tol_ppm:
        return None
        
    hc = H / C if C else float('inf')
    if C > 0:
        # check H/C rule
        if 'hc' in rules and not (hc_range[0] <= hc <= hc_range[1]):
            return None
        
        # check NOPS/C rule
        if 'nops_c' in rules:
            for el, max_ratio in max_hetero_ratios.items():
                if counts.get(el, 0) / C > max_ratio:
                    return None
    
    # check NOPS rule
    if 'nops' in rules:
        # check NOPS all > 1 rule
        if (N > 1 and O > 1 and P > 1 and S > 1):
            if N >= 10 or O >= 20 or P >= 4 or S >= 3:
                return None

        # check NOP all > 3 rule
        if (N > 3 and O > 3 and P > 3):
            if N >= 11 or O >= 22 or P >= 6:
                return None

        # check NOS all > 1 rule
        if (N > 1 and O > 1 and S > 1):
            if N >= 19 or O >= 14 or S >= 8:
                return None

        # check NPS all > 1 rule
        if (N > 1 and P > 1 and S > 1):
            if N >= 3 or P >= 3 or S >= 3:
                return None

        # check OPS all > 1 rule
        if (O > 1 and P > 1 and S > 1):
            if O >= 14 or P >= 3 or S >= 3:
                return None
    
    # Check RDBE rule
    rdbe = 1 + C + (N + P) / 2 - (H + X) / 2
    if 'rdbe' in rules and not (rdbe_range[0] <= rdbe <= rdbe_range[1]):
        return None
        
    # Check integer RDBE rule
    if 'integer_rdbe' in rules and (H + X + N + P) % 2 != 0:
        return None
    
    return {
        'formula': ef.toString(),
        'neutral_mass': exact,
        'delta_ppm': delta_ppm,
        'delta_mda': delta_da * 1000,
        'rdbe': rdbe,
        'hc': hc,
        'counts': dict(counts),
    }

def possible_formulas(mass: float, tolerance_ppm: float = 5.0, max_counts: dict = None,
                      min_counts: dict = None, limit: int = 1000, rules=None, **rule_kwargs) -> list:
    '''Formules brutes possibles pour une masse exacte (Da, monoisotopique, neutre),
    filtrées par les Seven Golden Rules de Fiehn (voir golden_rules_filter).

    Args:
        mass: masse exacte cible
        tolerance_ppm: tolérance de masse en ppm
        max_counts: bornes de comptage par élément (défaut: paliers selon la masse)
        limit: nombre max de résultats renvoyés (None = tout), triés par |ppm| croissant
        **rule_kwargs: hc_range, rdbe_range, max_hetero_ratios (voir golden_rules_filter)

    Returns:
        list de dicts {'formula', 'exact_mass', 'delta_mda', 'delta_ppm', 'rdbe', 'hc', 'counts'},
        triés par erreur ppm croissante
    '''
    tol_da = mass * tolerance_ppm * 1e-6
    if max_counts is None:
        max_counts = default_max_counts(mass)
    raw, symbols = enumerate_formula_counts(mass, tol_da, max_counts, min_counts)
    results = []
    for counts in raw:
        cd = {s: c for s, c in zip(symbols, counts) if c > 0}
        r = golden_rules_filter(cd, mass, tolerance_ppm, rules=rules, **rule_kwargs)
        if r is not None:
            results.append(r)
    results.sort(key=lambda r: abs(r['delta_ppm']))
    if limit is not None:
        results = results[:limit]
    return results

def theoretical_isotope_pattern(formula: str, max_isotopes: int = 10):
    '''Massif isotopique théorique (coarse) d'une formule neutre, via pyopenms.

    Args:
        formula: formule brute, ex. 'C8H10N4O2'
        max_isotopes: nombre max d'isotopes générés

    Returns:
        (offsets, intensities): offsets en Da par rapport au monoisotopique et
        intensités normalisées au pic monoisotopique (= 1)
    '''
    ef = oms.EmpiricalFormula(formula)
    gen = oms.CoarseIsotopePatternGenerator()
    gen.setMaxIsotope(max_isotopes)
    dist = gen.run(ef)
    mono = ef.getMonoWeight()
    peaks = sorted((p.getMZ() - mono, p.getIntensity()) for p in dist.getContainer())
    base = peaks[0][1] if peaks and peaks[0][1] > 0 else 1.0
    return [off for off, _ in peaks], [inten / base for _, inten in peaks]


def experimental_isotope_pattern(spectrum: oms.MSSpectrum, mz: float, charge: int = 1,
                                 mz_tolerance: float = 0.02, max_isotopes: int = 10) -> list:
    '''Intensités expérimentales du massif isotopique autour de mz, normalisées au
    monoisotopique. Sur spectre profile : max d'intensité dans chaque fenêtre de
    mz_tolerance ; sur spectre centroidé : pic le plus proche dans la tolérance.

    Args:
        spectrum: MSSpectrum (profile ou centroidé) contenant le pic à mz
        mz: m/z du pic monoisotopique
        charge: charge de l'ion (l'écart entre isotopes est 1.00335/|z|)
        mz_tolerance: demi-largeur de fenêtre (Da)
        max_isotopes: nombre d'isotopes extraits

    Returns:
        list d'intensités normalisées (longueur max_isotopes)
    '''
    z = abs(charge) or 1
    mzs, intens = spectrum.get_peaks()
    profile = spectrum.getType() == oms.SpectrumSettings.SpectrumType.PROFILE
    out = []
    for k in range(max_isotopes):
        target = mz + k * ISOTOPE_SPACING / z
        if profile:
            mask = (mzs >= target - mz_tolerance) & (mzs <= target + mz_tolerance)
            val = float(intens[mask].max()) if mask.any() else 0.0
        else:
            if mzs.size == 0:
                val = 0.0
            else:
                d = np.abs(mzs - target)
                val = float(intens[int(d.argmin())]) if d.min() <= mz_tolerance else 0.0
        out.append(val)
    base = out[0] if out and out[0] > 0 else (max(out) if out else 1.0)
    return [v / base for v in out]


def isotope_pattern_rms(theo_intensities: list, exp_intensities: list):
    '''RMS entre deux massifs isotopiques normalisés (tronqués à la longueur commune).
    0 = massifs identiques, plus la valeur est grande plus les massifs diffèrent.
    Retourne None si aucun isotope commun.'''
    n = min(len(theo_intensities), len(exp_intensities))
    if n == 0:
        return None
    return float(np.sqrt(np.mean([(t - e) ** 2 for t, e in zip(theo_intensities[:n], exp_intensities[:n])])))


def match_formulas_isotopes(results: list, spectrum: oms.MSSpectrum, mz: float, charge: int = 1,
                            mz_tolerance: float = 0.02, max_isotopes: int = 10) -> list:
    '''Ajoute à chaque candidat (dict de possible_formulas) le champ 'rms' : déviation
    RMS entre le massif isotopique théorique de la formule et le massif expérimental
    extrait du spectre autour de mz (équivalent pyopenms de mspy.matchpattern).

    Args:
        results: liste de dicts {'formula', ...} renvoyée par possible_formulas
        spectrum: MSSpectrum (profile ou centroidé) contenant le pic à mz
        mz: m/z du pic annoté
        charge: charge de l'ion
        mz_tolerance: tolérance d'extraction des isotopes (Da)
        max_isotopes: nombre d'isotopes comparés

    Returns:
        la liste des candidats (copiés) avec le champ 'rms', triée par rms croissant
    '''
    exp = experimental_isotope_pattern(spectrum, mz, charge, mz_tolerance, max_isotopes)
    out = []
    for r in results:
        _, theo = theoretical_isotope_pattern(r['formula'], max_isotopes)
        r = dict(r)
        rms = isotope_pattern_rms(theo, exp)
        r['rms'] = (1. - rms) * 100
        out.append(r)
    out.sort(key=lambda r: r['rms'] if r['rms'] is not None else float('inf'), reverse=True)
    return out

def isotope_ratios_by_index(formula: str, gen, max_isotopes: int = 6) -> dict:
    '''Ratios isotopiques M+k/M d'une formule, lus dans son pattern coarse pyopenms.'''
    ef = oms.EmpiricalFormula(formula)
    gen.setMaxIsotope(max_isotopes)
    dist = gen.run(ef)
    mono = ef.getMonoWeight()
    by_k = {}
    for p in dist.getContainer():
        k = int(round(p.getMZ() - mono))
        by_k[k] = by_k.get(k, 0.0) + p.getIntensity()
    base = by_k.get(0, 1.0)
    return {k: v / base for k, v in by_k.items()}


def estimate_halogens_sulfur_from_m2(ratio_m2_m: float, ratio_m1_m: float = None, nC: int = None,
                                      nC_tolerance: int = 10, max_cl: int = 4, max_br: int = 2,
                                      max_s: int = 6) -> dict:
    '''Estime les nombres de Cl, Br et S à partir du ratio isotopique M+2/M.

    Pour chaque combinaison (nC, nCl, nBr, nS), le ratio M+2/M théorique de
    C_nC Cl_nCl Br_nBr S_nS est calculé via pyopenms (CoarseIsotopePatternGenerator ;
    H/N/O négligés car leur contribution à M+2 est négligeable) ; la combinaison
    minimisant |ratio_theo - ratio_observé| est retenue.
    Si nC n'est pas fourni : estimé à partir de ratio_m1_m (M+1/M ~ nC * 0.0108),
    sinon nC = 20 par défaut. Dans les deux cas, nC est balayé dans
    [nC - nC_tolerance, nC + nC_tolerance].

    Args:
        ratio_m2_m: ratio expérimental M+2/M (ex. isotopes[2][1] / isotopes[0][1])
        ratio_m1_m: ratio expérimental M+1/M (optionnel, sert à estimer nC)
        nC: nombre de carbones connu (optionnel, prioritaire sur ratio_m1_m)
        nC_tolerance: demi-plage de balayage de nC
        max_cl, max_br, max_s: bornes supérieures de recherche

    Returns:
        {'Cl': nCl, 'Br': nBr, 'S': nS, 'nC': nC, 'ratio_theo': r, 'score': |r - ratio_m2_m|}
    '''
    gen = oms.CoarseIsotopePatternGenerator()
    if nC is None:
        if ratio_m1_m is not None:
            per_c_m1 = isotope_ratios_by_index('C1', gen).get(1, 0.0108)
            nC = int(ratio_m1_m // per_c_m1) if per_c_m1 > 0 else 20
        else:
            nC = 20
    best = None
    for c in range(max(0, nC - nC_tolerance), nC + nC_tolerance + 1):
        for cl in range(max_cl + 1):
            for br in range(max_br + 1):
                for s in range(max_s + 1):
                    parts = [f'C{c}'] if c else []
                    if cl:
                        parts.append(f'Cl{cl}')
                    if br:
                        parts.append(f'Br{br}')
                    if s:
                        parts.append(f'S{s}')
                    formula = ''.join(parts) if parts else 'C1'
                    r = isotope_ratios_by_index(formula, gen).get(2, 0.0)
                    score = abs(r - ratio_m2_m)
                    if best is None or score < best[0]:
                        best = (score, c, cl, br, s, r)
    score, c, cl, br, s, r = best
    return {'Cl': cl, 'Br': br, 'S': s, 'nC': c, 'ratio_theo': r, 'score': score}

def compute_formulas(spectrum: oms.MSSpectrum, mz: float,
                     neutral_mass: float, charge: int,
                     tolerance:int=5, tolerance_unit:str="ppm",
                     custom_composition:dict={}, limit:int=1000,
                     rules=None, min_formula:str=None, max_formula:str=None):
    # Estimate Cl/Br/S from isotopic ratios
    isotopes_int = experimental_isotope_pattern(spectrum, mz, charge=charge)
    ratio_m2_m = isotopes_int[2] / isotopes_int[0]
    ratio_m1_m = isotopes_int[1] / isotopes_int[0]
    estimated_counts = estimate_halogens_sulfur_from_m2(ratio_m2_m, ratio_m1_m)
    max_counts = default_max_counts(neutral_mass)
    for el in ('Cl', 'Br', 'S'):
        max_counts[el] = estimated_counts[el]

    # Bornes de formules brutes min/max (comparaison élément par élément)
    min_counts = oms.EmpiricalFormula(min_formula).getElementalComposition() if min_formula else None
    if max_formula:
        max_formula_counts = oms.EmpiricalFormula(max_formula).getElementalComposition()
        for el in list(max_counts):
            max_counts[el] = min(max_counts[el], max_formula_counts.get(el, 0))
       
    # Tolérance de masse : ppm par défaut, Da converti en ppm sinon
    if str(tolerance_unit).lower() == "ppm":
        tol_ppm = float(tolerance)
    else:
        tol_ppm = float(tolerance) / neutral_mass * 1e6 if neutral_mass else 5.0
    
    # Get possibles candidates
    candidates = possible_formulas(neutral_mass, tolerance_ppm=tol_ppm,
                                   max_counts=max_counts, min_counts=min_counts,
                                   limit=limit, rules=rules)
    
    # Rank formula by RMS
    ranked = match_formulas_isotopes(candidates, spectrum, mz=mz, charge=charge)
    return ranked