import requests
import re
import itertools
from dataclasses import dataclass

import pandas as pd
import numpy as np
import pyopenms as oms

from .unifiapi import Spectrum, SpectrumInfos, UNIFIAPI
import mspy

LOCKSPRAY_FORMULA = "C28H37N5O7"
TRACE_NAME_RE = re.compile(r"[0-9:\s]*([A-Za-z\s]+)(\([\d\-]+\)[0-9A-Z\+\-])?")
OPENMS_POLARITY_TO_MSPY = {
    oms.IonSource.Polarity.NEGATIVE: -1,
    oms.IonSource.Polarity.POLNULL: 0,
    oms.IonSource.Polarity.POSITIVE: 1
}
MPSY_POLARITY_TO_OPENMS = {v: k for k, v in OPENMS_POLARITY_TO_MSPY.items()}

@dataclass
class RTRange:
    '''Retention Time Range (in minutes)'''
    
    low: float
    high: float

def unifi_to_openms(spectra: list[Spectrum], channel: SpectrumInfos) -> oms.Experiment:
    '''Converts a list of unifiapi Spectrum objects to an OpenMS experiment
    
    Args:
        spectra: list of Spectrum objects
        channel: SpectrumInfos object relative to where the spectra were extracted
        
    Returns:
        oms.Experiment containing the data extracted from the list of Spectrum
    '''
    
    exp = oms.MSExperiment()
    
    for spec in spectra:
        spectrum = oms.MSSpectrum()
        spectrum.setMSLevel(1)
        spectrum.setRT(spec.retentionTime)
        spectrum.set_peaks((spec.valuesX, spec.valuesY))
        peaks = spectrum.get_peaks()
        tic = peaks[1].sum()
        spectrum.setMetaValue("total ion current", tic.astype(float))
        bpi = peaks[1].max()
        spectrum.setMetaValue("base peak intensity", bpi.astype(float))
        bpi_mz = peaks[0][peaks[1]==bpi][0]
        spectrum.setMetaValue("base peak m/z", bpi_mz.astype(float))
        spectrum.setMetaValue("lowest observed m/z", peaks[0].min())
        spectrum.setMetaValue("highest observed m/z", peaks[0].max())
        
        settings = spectrum.getInstrumentSettings()
        match channel.analyticalTechnique.ionisationMode:
            case "+":
                settings.setPolarity(oms.IonSource.Polarity.POSITIVE)
            case "-":
                settings.setPolarity(oms.IonSource.Polarity.NEGATIVE)
        scan_window = oms.ScanWindow()
        scan_window.begin = channel.analyticalTechnique.lowMass
        scan_window.end = channel.analyticalTechnique.highMass
        settings.setScanWindows([scan_window])
        spectrum.setInstrumentSettings(settings)

        instrument = exp.getInstrument()
        instrument.setName('Waters Vion')
        instrument.setModel('Vion')
        instrument.setVendor('Waters')
        exp.setInstrument(instrument)

        # analyzer = oms.MassAnalyzer()

        # # Iterate over mass analyzers
        # for analyzer in instrument.getMassAnalyzers():
        #   print("Mass Analyzer Type:", analyzer.getType())
        
        exp.addSpectrum(spectrum)
        
    exp.updateRanges()
    return exp

def openms_to_mspy(exp: oms.Experiment) -> mspy.scan:
    '''Converts an OpenMS Experiment to a mspy scan object
    
    Args:
        exp: the OpenMS experiment to get the data from
        
    Returns:
        mspy.scan object containing the data
    '''
    
    spectrum = exp.getSpectra()[0]
    peaks = spectrum.get_peaks()
    scan = mspy.scan(profile=list(zip(*peaks)))
    scan.retentionTime = spectrum.getRT()
    scan.polarity = OPENMS_POLARITY_TO_MSPY.get(spectrum.getInstrumentSettings().getPolarity(), 0)
    return scan
    
def mspy_to_openms(scans: list[mspy.scan]):
    '''Converts a list of mspy.scan objects to an OpenMS experiment
    
    Args:
        scan: mspy.scan object containing the data
        
    Returns:
        oms.Experiment containing the data extracted from the mspy scans
    '''
    
    exp = oms.MSExperiment()

    def add_spectrum(exp, data):
        spectrum = oms.MSSpectrum()
        spectrum.setMSLevel(1)
        
        if isinstance(data, mspy.peaklist):
            spectrum.set_peaks(list(zip(*[(peak.mz, peak.intensity) for peak in scan.peaklist])))
            spectrum.setType(oms.SpectrumSettings.SpectrumType.CENTROID)
        elif isinstance(data, np.ndarray):
            spectrum.set_peaks(scan.profile.T.tolist())
            spectrum.setType(oms.SpectrumSettings.SpectrumType.PROFILE)

        if scan.retentionTime:
            spectrum.setRT(scan.retentionTime)
            
        if scan.polarity:
            insset = spectrum.getInstrumentSettings()
            insset.setPolarity(MPSY_POLARITY_TO_OPENMS.get(scan.polarity, 0))
            spectrum.setInstrumentSettings(insset)
            
        peaks = spectrum.get_peaks()
        if not peaks:
            return
        tic = peaks[1].sum()
        spectrum.setMetaValue("total ion current", tic.astype(float))
        bpi = peaks[1].max()
        spectrum.setMetaValue("base peak intensity", bpi.astype(float))
        bpi_mz = peaks[0][peaks[1]==bpi][0]
        spectrum.setMetaValue("base peak m/z", bpi_mz.astype(float))
        spectrum.setMetaValue("lowest observed m/z", peaks[0].min())
        spectrum.setMetaValue("highest observed m/z", peaks[0].max())
        exp.addSpectrum(spectrum)

    for scan in scans:
        if scan.peaklist:
            add_spectrum(exp, scan.peaklist)
        add_spectrum(exp, scan.profile)

    exp.updateRanges()
    
    return exp

def average_spectrum(exp: oms.Experiment, rt_range: RTRange = None) -> oms.Experiment:
    '''Compute the average spectrum from all the spectra inside the experiment or a subset
    if an Retention Time range is provided.
    
    Args:
        exp: Experiment from where to get spectra to average
        rt_range: Retention Time range to use to filter spectra
        
    Returns:
        oms.Experiment with only one spectrum: the computed average spectrum
    '''
    
    average_exp = oms.MSExperiment(exp)
    average_exp.clear(False)

    for spec in exp.getSpectra():
        if rt_range is None or rt_range.low < spec.getRT() < rt_range.high:
            average_exp.addSpectrum(spec)
    average_exp.updateRanges()

    merger = oms.SpectraMerger()
    param = merger.getParameters()
    param.setValue("block_method:rt_block_size", average_exp.getNrSpectra())
    merger.setParameters(param)
    merger.mergeSpectraBlockWise(average_exp)
    
    return average_exp

def get_data(channel: SpectrumInfos, rt_range: RTRange = None, output_filename: str = None) -> mspy.scan:
    '''
    Get spectra from server, save the spectra to mzML (if a filename is provided),
    average the spectra inside the Retention Time range (if provided, else in entire scan),
    and return the average spectrum in an mspy.scan object
    
    Args:
        channel: SpectrumInfos object of the channel we want to extract data
        rt_range: Retention Time range to use to filter spectra
        output_filename: filename where to save mzML data
        
    Returns:
        mspy.scan object of the average spectrum
    '''
    
    # Get data from server
    spectra = channel.data(stream=True)
    
    # Create OpenMS experiment
    exp = unifi_to_openms(spectra, channel)
    
    # Save OpenMS experiment if needed
    if output_filename is not None:
        oms.MzMLFile().store(output_filename + ".mzML.gz", exp)
    
    # Average all spectra into one spectrum (in an OpenMS experiment)
    avg_exp = average_spectrum(exp, rt_range=rt_range)
    
    # Convert to mspy scan
    scan = openms_to_mspy(avg_exp)
    
    assert(scan.hasprofile())
    
    return scan
    
def lock_mass_correct(scan: mspy.scan, ls_scan: mpy.scan, ionisation_mode: str) -> mspy.scan:
    '''Apply lock mass correction on the peaklist of an mspy scan object
    
    Args:
        scan: mspy scan to apply correction on
        ls_scan: lock spray scan to look for lock mass in
        formula: crude formula of lockmass
        ionisation_mode: polarity of the scan ('+' for positive, '-' for negative)
        
    Returns:
        scan object with peaklist lockmass corrected
    '''
    
    # Smooth Lock Spray scan
    ls_scan.smooth(method="SG", window=1., cycles=3)
        
    # Calculate theoretical m/z of lock mass
    ls_th_mz = mspy.mz(
        mspy.compound(LOCKSPRAY_FORMULA).mass(0),
        charge=-1 if ionisation_mode == '-' else 1,
        agentFormula='H',
        agentCharge=1
    )
    
    # Find lock mass peak
    ls_peak = mspy.labelpeak(
        signal=ls_scan.profile,
        mz=ls_th_mz,
        pickingHeight=1.0,
        baseline=ls_scan.baseline(window=0.01, offset=.25),
    )
    
    if ls_peak is None or ls_peak.sn <= 50:
        raise ValueError("Lock Spray mass was not found")
    
    for peak in scan.peaklist.peaks:
        # Lock Mass Correction
        peak.mz = peak.mz - ls_peak.mz + ls_th_mz
        
    return scan
    
def peak_picking(scan: mspy.scan) -> mspy.scan:
    '''Apply peak picking to scan object
    
    Args:
        scan: scan object to apply peak picking one
        
    Returns:
        Same scan object with peaklist populated
    '''
    
    # Find peaks in data and populate scan.peaklist
    scan.labelscan(
        pickingHeight=1.,
        absThreshold=1e4,
        relThreshold=.01,
        snThreshold=25.,
        baselineWindow=0.1,
        baselineOffset=.25,
        smoothMethod=None,
        smoothWindow=.15,
        smoothCycles=5,
    )
    
    # Remove isotopes in peaklist
    scan.deisotope(
        maxCharge=3,
        mzTolerance=0.005, # 0.02
        intTolerance=0.5,  # 0.85
        isotopeShift=0.,
        averagineType="lipid",
    )
    
    # Label envelopes (group isotopes)
    scan.labelenvelopes(
        label="monoisotope",
        intensity="maximum",
        mzTolerance=0.005,  # 0.02
        isotopeShift=0.,
        nonIdeality=0.4,
        averagineType="lipid",
        refinePattern=True,
        preserveSeeds=True,
        relaxed=True,
    )
    
    # Remove isotopes
    scan.remisotopes()
    
    # Remove peaks where charge can't be determined
    scan.remuncharged()
    
    # Filter out very small peaks
    # The thresholds were very low a labelscan step to include isotopes and be able to determine charge
    scan.remthreshold(absThreshold=1e5, relThreshold=0.1, snThreshold=100.)
    
    return scan
            
def extract_trace_name(trace_name: str) -> str:
    '''Remove unwanted information from trace name'''
    
    match = TRACE_NAME_RE.match(trace_name)
    return match.group(1).strip()
    
def estimate_halogens_sulfur_composition(isotopes, nC_tolerance=5):
    '''
    Estimates the number of halogen atoms from the (M+2)/M intensity ratio.
    '''
    
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
    
def generate_formulae(peak, tolerance=5, tolerance_unit="ppm",
                      agentFormula="H", agentCharge=1,
                      custom_composition={}, limit=1000):   
    mass = mspy.mz(mass=peak.mz, charge=0, currentCharge=peak.charge,
                   agentFormula=agentFormula, agentCharge=agentCharge)
    if mass < 500:
        composition = {
            "C": [0, 40],
            "H": [0, 80],
            "N": [0, 20],
            "O": [0, 20],
        }
    elif mass < 1000:
        composition = {
            "C": [0, 80],
            "H": [0, 130],
            "N": [0, 30],
            "O": [0, 30],
        }
    elif mass < 2000:
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
    halogens_sulfur_composition = estimate_halogens_sulfur_composition(peak.attributes['envelope']['isotopes'])
    composition.update(halogens_sulfur_composition)
    composition.update(custom_composition)

    # Generate formulae
    formulae = mspy.formulator(
                mz=peak.mz,
                charge=peak.charge,
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
        mz=peak.mz,
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
        th_mz = mspy.mz(neutral_mass, charge=peak.charge, agentFormula=agentFormula, agentCharge=agentCharge)
        delta_ppm = mspy.delta(peak.mz, th_mz, "ppm")
        delta_mDa = mspy.delta(peak.mz, th_mz, "Da") * 1000
        
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
                charge=peak.charge,
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
                        "mass": neutral_mass,
                        "xp_mz": peak.mz,
                        "th_mz": th_mz,
                        "delta_ppm": delta_ppm,
                        "delta_mDa": delta_mDa,
                        "hc": hc,
                        "rdbe": rdbe,
                        "rms": rms})
    return sorted(results, key=lambda x: abs(x['rms']), reverse=True)


def set_agent_formula(peak: mspy.peak, agentFormula: str) -> None:
    if peak.attributes.get("agentFormula") is None:
        peak.attributes["agentFormula"] = [agentFormula]
    else:
        peak.attributes["agentFormula"].append(agentFormula)
