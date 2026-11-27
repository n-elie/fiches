import requests
import re
import itertools
from dataclasses import dataclass

import pandas as pd
import numpy as np
import pyopenms as oms
from pyopenms.Constants import PROTON_MASS_U

from .unifiapi import Spectrum, SpectrumInfos, UNIFIAPI

LOCKSPRAY_FORMULA = "C28H37N5O7"
MAX_RAW_POINTS = 10000  # plafond de points affichés pour le spectre brut (profilé) en fond
TRACE_NAME_RE = re.compile(r"[0-9:\s]*([A-Za-z\s]+)(\([\d\-]+\)[0-9A-Z\+\-])?")

@dataclass
class RTRange:
    '''Retention Time Range (in minutes)'''
    
    low: float
    high: float

def download_spectra_to_openms(channel: SpectrumInfos) -> oms.Experiment:
    '''Download spectra from UNIFI channel and store them in an OpenMS experiment
    
    Args:
        channel: SpectrumInfos object relative to where the spectra were extracted
        
    Returns:
        oms.Experiment containing the downloaded spectra
    '''
    
    spectra = channel.data(stream=True)
    
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
        spectrum.setType(oms.SpectrumSettings.SpectrumType.PROFILE)
        
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
        
        exp.addSpectrum(spectrum)
        
    exp.updateRanges()
    return exp

def average_spectrum(exp: oms.Experiment, rt_range: RTRange = None) -> oms.MSSpectrum:
    '''Compute the average spectrum from all the spectra inside the experiment or a subset
    if an Retention Time range is provided.
    
    Args:
        exp: Experiment from where to get spectra to average
        rt_range: Retention Time range to use to filter spectra
        
    Returns:
        oms.MSSpectrum: the computed average spectrum
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
    
    return average_exp.getSpectra()[0]
    
def centroid_experiment(exp: oms.MSExperiment, signal_to_noise: float = 1.0) -> oms.MSExperiment:
    '''Centroid all MS1 profile spectra of an experiment with PeakPickerHiRes

    Args:
        exp: MSExperiment containing profile spectra
        signal_to_noise: signal-to-noise threshold used by the peak picker

    Returns:
        New MSExperiment with centroided spectra
    '''
    picker = oms.PeakPickerHiRes()
    params = picker.getParameters()
    params.setValue("signal_to_noise", signal_to_noise)
    params.setValue("ms_levels", [1])
    picker.setParameters(params)
    return picker.pickExperiment(exp, True)

def centroid_and_lock_mass_correct(analyte_exp: oms.MSExperiment, lockmass_exp: oms.MSExperiment,
                                   ionisation_mode: str = None, tol_ppm: float = 20.0,
                                   signal_to_noise: float = 1.0) -> tuple[oms.MSExperiment, oms.MSExperiment]:
    '''Centroid both experiments, then recalibrate the analyte spectra using the lock spray
    reference channel (Waters) with pyopenms InternalCalibration.

    Args:
        analyte_exp: MSExperiment with profile spectra of the analyte data
        lockmass_exp: MSExperiment with profile spectra of the lock spray channel
        ionisation_mode: '+' or '-' (read from the spectra polarity if None)
        tol_ppm: tolerance (ppm) used to find the lock mass in the lock spray spectra
        signal_to_noise: signal-to-noise threshold for peak picking

    Returns:
        (analyte_centroided, analyte_profile): two MSExperiments with the analyte data,
        the first centroided and calibrated, the second calibrated but kept in profile mode

    Raises:
        ValueError: if the lock mass is not found in the lock spray experiment
    '''
    if ionisation_mode is None:
        polarity = analyte_exp.getSpectra()[0].getInstrumentSettings().getPolarity()
        ionisation_mode = '+' if polarity == oms.IonSource.Polarity.POSITIVE else '-'
    z = 1 if ionisation_mode == '+' else -1
    th_mz = oms.EmpiricalFormula(LOCKSPRAY_FORMULA).getMonoWeight() + z * PROTON_MASS_U

    lockmass_cent = centroid_experiment(lockmass_exp, signal_to_noise)
    analyte_cent = centroid_experiment(analyte_exp, signal_to_noise)

    ic = oms.InternalCalibration()
    n_found, _ = ic.fillCalibrants(
        lockmass_cent,
        [oms.InternalCalibration_LockMass(th_mz, 1, 1)],
        tol_ppm, True, False, False
    )
    if not n_found:
        raise ValueError("Lock mass was not found in the lock spray experiment")

    calibrants = ic.getCalibrationPoints()
    ppm_err = float(np.mean([
        (calibrants.getMZ(i) - calibrants.getRefMZ(i)) / calibrants.getRefMZ(i) * 1e6
        for i in range(calibrants.size())
    ]))

    trafo = oms.MZTrafoModel()
    trafo.setCoefficients(ppm_err, 0.0, 0.0)

    analyte_profile = oms.MSExperiment(analyte_exp)
    ic.applyTransformation(analyte_cent, [1], trafo)
    ic.applyTransformation(analyte_profile, [1], trafo)
    return analyte_cent, analyte_profile    

def filter_centroid_peaks(spectrum: oms.MSSpecctrum, abs_threshold: int=1e4, rel_threshold:float=.01):
    """
    Remove peaks below theshold, deisotope and remove uncharged ions
    """
    
    # Threshold filtering
    peaks = list(spectrum.get_peaks())
    threshold_filter = peaks[1] > max(spectrum.get_base_peak()[1]*rel_threshold, abs_threshold)
    peaks[0] = peaks[0][threshold_filter]
    peaks[1] = peaks[1][threshold_filter]
    spectrum.set_peaks(peaks, metadata='clear')
    
    # Deisotope
    spectrum.sortByPosition()
    oms.Deisotoper.deisotopeWithAveragineModel(
        spectrum,
        fragment_tolerance=20.0,   # tolerance value
        fragment_unit_ppm=True,    # True for ppm, False for m/z (Da)
        number_of_final_peaks=5000,
        min_charge=1,
        max_charge=3,
        keep_only_deisotoped=False,
        min_isopeaks=2,
        max_isopeaks=10,
        make_single_charged=True,
        annotate_charge=True,
        annotate_iso_peak_count=False,
        add_up_intensity=False,
    )
    
    # Remove uncharged peaks
    peaks = list(spectrum.get_peaks())
    for data_array in spectrum.getIntegerDataArrays():
        if data_array.getName() == 'charge':
            charges = data_array.get_data()
            peaks[0] = peaks[0][charges.astype(bool)]
            peaks[1] = peaks[1][charges.astype(bool)]
            spectrum.set_peaks(peaks, metadata='clear')
    
    return spectrum

def downsample_profile(spectrum: oms.MSSpectrum, max_points=MAX_RAW_POINTS):
    """Limite le nombre de points d'un spectre profilé (intensité max par bac de m/z) pour alléger l'affichage."""

    x, y = spectrum.get_peaks()
    
    if x.size <= max_points:
        return spectrum
    order = np.argsort(x, kind='stable')
    x, y = x[order], y[order]
    x_min, x_max = x[0], x[-1]
    if x_max <= x_min:
        return [profile[order[0]]]
    
    bins = np.minimum(((x - x_min) / (x_max - x_min) * max_points).astype(np.int64), max_points - 1)
    by_bin = np.lexsort((y, bins))                        # tri par bac, puis par intensité croissante
    sorted_bins = bins[by_bin]
    keep = np.append(sorted_bins[1:] != sorted_bins[:-1], True)  # dernier point de chaque bac = intensité max
    spectrum.set_peaks([x[i] for i in order[by_bin[keep]]], [y[i] for i in order[by_bin[keep]]])
    return spectrum
            
def extract_trace_name(trace_name: str) -> str:
    '''Remove unwanted information from trace name'''
    
    match = TRACE_NAME_RE.match(trace_name)
    return match.group(1).strip()

def load_mzml_spectra(mzml_file: str, return_scan:bool=True, return_data:bool=True) -> dict:
    '''
    Load the MS1 spectra of a mzML file, organized by polarity.

    Args:
        mzml_file: path of the mzML file to load
        return_scan: whether to return the oms.MSSpectrum object
        return_data: whether to return centroid, profile and tic data

    Returns:
        dict {'positive': entry, 'negative': entry} where each entry has:
        - 'centroid': list of peaks {'x', 'y'} from the centroid spectra
        - 'profile': list of peaks {'x', 'y'} from the profile spectra (raw data)
        - 'tic': max "total ion current" meta value of the profile spectra (None if absent)
        - 'scan': oms.MSSpectrum containing the spectrum (profile spectrum preferred over centroid)
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
            
        entry = spectra[key]
        spec_type = spec.getType()
        
        if return_data:
            mz_array, intensity_array = spec.get_peaks()
            peaks = [{'x': float(mz), 'y': float(inten)} for mz, inten in zip(mz_array, intensity_array)]
            if spec_type == oms.SpectrumSettings.SpectrumType.CENTROID:
                entry['centroid'].extend(peaks)
            elif spec_type == oms.SpectrumSettings.SpectrumType.PROFILE:
                entry['profile'].extend(peaks)
                if spec.metaValueExists("total ion current"):
                    value = float(spec.getMetaValue("total ion current"))
                    entry['tic'] = value if entry['tic'] is None else max(entry['tic'], value)
        if return_scan and (entry['scan'] is None or spec_type == oms.SpectrumSettings.SpectrumType.PROFILE):
            entry['scan'] = spec
    return spectra
