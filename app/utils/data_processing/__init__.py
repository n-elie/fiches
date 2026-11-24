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

def openms_to_mspy(exp: oms.MSExperiment) -> mspy.scan:
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
        oms.MzMLFile().store(output_filename + ".mzML", exp)
    
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
    
    # Lock Mass Correction
    for peak in scan.peaklist.peaks:
        peak.mz += ls_th_mz - ls_peak.mz
    scan.profile[:,0] += ls_th_mz - ls_peak.mz
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
        relThreshold=.001,
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
    
    return scan
            
def extract_trace_name(trace_name: str) -> str:
    '''Remove unwanted information from trace name'''
    
    match = TRACE_NAME_RE.match(trace_name)
    return match.group(1).strip()

def load_mzml_spectra(mzml_file: str) -> dict:
    '''
    Load the MS1 spectra of a mzML file, organized by polarity.

    Args:
        mzml_file: path of the mzML file to load

    Returns:
        dict {'positive': entry, 'negative': entry} where each entry has:
        - 'centroid': list of peaks {'x', 'y'} from the centroid spectra
        - 'profile': list of peaks {'x', 'y'} from the profile spectra (raw data)
        - 'tic': max "total ion current" meta value of the profile spectra (None if absent)
        - 'scan': mspy.scan of the spectrum (profile spectrum preferred over centroid)
    '''
    exp = oms.MSExperiment()
    oms.MzMLFile().load(mzml_file, exp)

    spectra = {
        key: {'centroid': [], 'profile': [], 'tic': None, 'scan': None}
        for key in ('+', '-')
    }
    for spec in exp.getSpectra():
        if spec.getMSLevel() != 1:
            continue
        polarity = spec.getInstrumentSettings().getPolarity()
        if polarity == oms.IonSource.Polarity.POSITIVE:
            key = '+'
        elif polarity == oms.IonSource.Polarity.NEGATIVE:
            key = '-'
        else:
            continue
        mz_array, intensity_array = spec.get_peaks()
        peaks = [{'x': float(mz), 'y': float(inten)} for mz, inten in zip(mz_array, intensity_array)]
        entry = spectra[key]
        spec_type = spec.getType()
        if spec_type == oms.SpectrumSettings.SpectrumType.CENTROID:
            entry['centroid'].extend(peaks)
        elif spec_type == oms.SpectrumSettings.SpectrumType.PROFILE:
            entry['profile'].extend(peaks)
            if spec.metaValueExists("total ion current"):
                value = float(spec.getMetaValue("total ion current"))
                entry['tic'] = value if entry['tic'] is None else max(entry['tic'], value)
        if entry['scan'] is None or spec_type == oms.SpectrumSettings.SpectrumType.PROFILE:
            sub = oms.MSExperiment()
            sub.addSpectrum(spec)
            entry['scan'] = openms_to_mspy(sub)
    return spectra
