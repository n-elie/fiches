import mspy

def estimate_halogens_sulfur_composition(isotopes, nC_tolerance=5):
    """
    Estimates the number of halogen and sulfur atoms from the (M+2)/M intensity ratio.
    """
    composition = {}

    ratio_m2_m_xp = isotopes[2][1] / isotopes[0][1]
    ratio_m1_m_xp = isotopes[1][1] / isotopes[0][1]

    # Estimate number of Carbons bases on [M+1]/M ratio
    C_pattern = [intensity for mass, intensity in mspy.compound("C").pattern()]
    ratio_m1_m_C = C_pattern[1] / C_pattern[0]
    nC = int(ratio_m1_m_xp // ratio_m1_m_C)
    
    try:
        Cs_pattern = [intensity for mass, intensity in mspy.compound("C" + str(nC)).pattern()]
        ratio_m2_m_Cs = Cs_pattern[2] / Cs_pattern[0]
    except IndexError:
        ratio_m2_m_Cs = 0.
    
    for element in ("Br", "Cl"):
        # Natural isotope abundance ratios (Isotope+2 / Isotope)
        # Chlorine: 37Cl / 35Cl ≈ 24.24% / 75.76% ≈ 0.320
        # Bromine: 81Br / 79Br ≈ 50.69% / 49.31% ≈ 1.028
        el_pattern = [intensity for mass, intensity in mspy.compound(element).pattern()]
        ratio_m2_m_el = el_pattern[1] / el_pattern[0]
        n_estimated = int((ratio_m2_m_xp - ratio_m2_m_Cs) // ratio_m2_m_el)
        composition[element] = [n_estimated, n_estimated]
        
    # Estimate "S" number
    composition["S"] = []
    S_pattern = [intensity for mass, intensity in mspy.compound("S").pattern()]
    ratio_m2_m_S = S_pattern[1] / S_pattern[0]
    for num_C in (nC - nC_tolerance, nC + nC_tolerance):
        try:
            halogens_Cs_pattern = [intensity for mass, intensity in mspy.compound(
                                       "C" + str(max(0, num_C)) + "Cl" + str(composition["Cl"][0]) + "Br" + str(composition["Br"][0])).pattern()
                                  ]
            if num_C > 0:
                ratio_m2_m_halogens_Cs = halogens_Cs_pattern[2] / halogens_Cs_pattern[0]
            else:
                ratio_m2_m_halogens_Cs = halogens_Cs_pattern[1] / halogens_Cs_pattern[0]
        except IndexError:
            ratio_m2_m_halogens_Cs = 0.
        n_estimated = round((ratio_m2_m_xp - ratio_m2_m_halogens_Cs) / ratio_m2_m_S)
        composition["S"].append(max(0, n_estimated))
    composition["S"] = sorted(composition["S"])
    
    return composition
    
def compute_formulas(scan: mspy.scan, mz: float, neutral_mass: float, charge: int, isotopes: dict,
                     tolerance:int=5, tolerance_unit:str="ppm",
                     agentFormula:str="H", agentCharge:int=1,
                     custom_composition:dict={}, limit:int=1000):
    # mass = mspy.mz(mass=mz, charge=0, currentCharge=charge,
                   # agentFormula=agentFormula, agentCharge=agentCharge)
    if neutral_mass < 500:
        composition = {
            "C": [0, 40],
            "H": [0, 80],
            "N": [0, 20],
            "O": [0, 20],
        }
    elif neutral_mass < 1000:
        composition = {
            "C": [0, 80],
            "H": [0, 130],
            "N": [0, 30],
            "O": [0, 30],
        }
    elif neutral_mass < 2000:
        composition = {
            "C": [0, 160],
            "H": [0, 250],
            "N": [0, 40],
            "O": [0, 70],
        }
    else:
        composition = {
            "C": [0, 180],
            "H": [0, 300],
            "N": [0, 60],
            "O": [0, 90],
        }
    if isotopes is not None:
        halogens_sulfur_composition = estimate_halogens_sulfur_composition(isotopes)
        composition.update(halogens_sulfur_composition)
    composition.update(custom_composition)

    # Generate formulae
    formulae = mspy.formulator(
                mz=mz,
                charge=charge,
                tolerance=tolerance,
                units=tolerance_unit,
                composition=composition,
                agentFormula=agentFormula,
                agentCharge=agentCharge,
                limit=limit,
            )

    results = []
    
    # Get baseline
    baseline = scan.baseline(window=0.01, offset=.25)

    fwhm = 0.1
    peak_labelled = mspy.labelpeak(
        signal=scan.profile,
        mz=mz,
        pickingHeight=1.0,
        baseline=baseline,
    )
    if peak_labelled and peak_labelled.fwhm != 0:
        fwhm = peak_labelled.fwhm
    
    for formula in formulae:
        # make compound
        cmpd = mspy.compound(formula)

        # Apply 7 golden rules
        if not cmpd.frules(rules=["HC", "NOPSC", "NOPS", "RDBE", "RDBEInt"],
                           HC=(.1, 3.),
                           NOPSC=(4, 3, 2, 3),
                           RDBE=(-1, 40)):
            continue
        
        neutral_mass = cmpd.mass(0)
        th_mz = mspy.mz(neutral_mass, charge=charge, agentFormula=agentFormula, agentCharge=agentCharge)
        delta_ppm = mspy.delta(mz, th_mz, "ppm")
        delta_mDa = mspy.delta(mz, th_mz, "Da") * 1000
        
        # count ratios
        countC = float(cmpd.count("C", groupIsotopes=True))
        countH = float(cmpd.count("H", groupIsotopes=True))
        hc = None
        if countC:
            hc = countH / countC
        rdbe = cmpd.rdbe()

        pattern = cmpd.pattern(
                fwhm=fwhm,
                threshold=0.01,
                charge=charge,
                agentFormula=agentFormula,
                agentCharge=agentCharge,
                real=True,
            )
        rms = mspy.matchpattern(
                signal=scan.profile,
                pattern=pattern,
                pickingHeight=1.0,
                baseline=baseline,
            )
        if rms is not None:
            rms = (1 - rms) * 100
        results.append({"formula": cmpd.formula(),
                        "neutral_mass": neutral_mass,
                        "mz_exp": mz,
                        "mz_theo": th_mz,
                        "delta_ppm": delta_ppm,
                        "delta_mda": delta_mDa,
                        "hc": hc,
                        "rdbe": rdbe,
                        "rms": rms})
    return sorted(results, key=lambda x: abs(x['rms']), reverse=True)