from flask import current_app
from celery import shared_task

import pyopenms as oms
import os
import redis
import logging
import requests
import urllib3
import numpy as np
import json

from ..models import db, Sample, SampleStatus, PeakAnnotation
from ..utils.data_processing import UNIFIAPI, extract_trace_name, get_data, peak_picking, lock_mass_correct, mspy_to_openms, RTRange
from ..utils.errors import sanitize_log, log_error
from ..utils.peak_annotation import annotate_peaks
from .celery_app import celery

LOCK_KEY = 'lock:download_spectra'
MAX_RAW_POINTS = 10000  # plafond de points affichés pour le spectre brut (profilé) en fond

logger = logging.getLogger(__name__)

def downsample_profile(profile, max_points=MAX_RAW_POINTS):
    """Limite le nombre de points d'un spectre profilé (intensité max par bac de m/z) pour alléger l'affichage."""
    
    if len(profile) <= max_points:
        return profile
    x, y = profile.T
    order = np.argsort(x, kind='stable')
    x, y = x[order], y[order]
    x_min, x_max = x[0], x[-1]
    if x_max <= x_min:
        return [profile[order[0]]]
    
    bins = np.minimum(((x - x_min) / (x_max - x_min) * max_points).astype(np.int64), max_points - 1)
    by_bin = np.lexsort((y, bins))                        # tri par bac, puis par intensité croissante
    sorted_bins = bins[by_bin]
    keep = np.append(sorted_bins[1:] != sorted_bins[:-1], True)  # dernier point de chaque bac = intensité max
    return np.asarray([profile[i] for i in order[by_bin[keep]]])

def round_floats(obj, precision=2):
    if isinstance(obj, float):
        return round(obj, precision)
    if isinstance(obj, dict):
        return {k: round_floats(v, precision) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [round_floats(x, precision) for x in obj]
    return obj

@celery.task(bind=True)
def download_spectra(self):
    """
    Tâche Celery pour récupérer les spectres depuis l'instrument.
    """
    
    r = celery.backend.client

    if not r.set(LOCK_KEY, '1', nx=True, ex=3600):
        logger.info("Task already running, execution of this task will be ignored.")
        return {'status': 'skipped'}
    try:
        unifi_config = current_app.config['UNIFI']
    
        stmt = db.select(Sample) \
            .where(Sample.status == SampleStatus.analysing) \
            .where(Sample.analysis_type == 'ms')
        samples = db.session.scalars(stmt)
        total = db.session.scalar(db.select(db.func.count()).select_from(stmt.subquery()))
        
        if total == 0:
            logger.warning("No MS samples in analysing status found.")
            return {'status': 'success'}
        else:
            logger.info(f"{total} MS samples in analysing status found.")
        
        api = UNIFIAPI(unifi_config['server'], certificate=unifi_config['certificate'])
        for sample in samples:
            mzml_folder = os.path.join(current_app.config['UPLOAD_FOLDER'], sample.analysis_type, 'spectra')
            os.makedirs(mzml_folder, exist_ok=True)
            mzml_file = os.path.join(mzml_folder, f'{sample.id}.mzML')
            json_file = os.path.join(mzml_folder, f'{sample.id}.json')
            if os.path.exists(mzml_file):
                logger.info(f"Skipped spectra downloading for {sanitize_log(sample.reference)} as mzML file already exists.")
                continue
            try:
                api.connect(unifi_config['username'], unifi_config['password'])
            
                data_folder = api.get_folder_by_path(unifi_config['data_folder'])
                    
                sample_items = [item for item in data_folder.items() if item.type == "SampleResult" and item.name == sample.reference]
                
                if not sample_items:
                    logger.warning(f"No sample item found for sample reference: {sanitize_log(sample.reference)}.")
                    continue
                else:
                    logger.info(f"{len(sample_items)} sample item(s) found for sample reference: {sanitize_log(sample.reference)}.")
                
                sample_items = sorted(sample_items, key=lambda item: item.createdAt, reverse=True)
                sample_results = [item.convert() for item in sample_items]
                
                # Retrieve lock mass corrected data in both polarity
                spectra, isotopes = {}, {}
                for sr in sample_results:
                    specinfos = sr.spectruminfos()
                    specinfos = {extract_trace_name(trace.name): trace for trace in specinfos}
                    ionisation_mode = specinfos['DDA TOF MS'].analyticalTechnique.ionisationMode
                    
                    if ionisation_mode in spectra.keys():
                        continue
                    
                    # Get data from server
                    ls_scan = get_data(specinfos['MS LockSpray Reference Data'])
                    data_scan = get_data(
                        specinfos['DDA TOF MS'],
                        rt_range=RTRange(0.1, 0.3)
                    )
                    
                    # Apply peak picking and lock mass correction
                    data_scan = peak_picking(data_scan) 
                    if data_scan.peaklist:
                        data_scan = lock_mass_correct(data_scan, ls_scan, ionisation_mode)
                    data_scan.profile = downsample_profile(data_scan.profile)
                    spectra[ionisation_mode] = data_scan
                    isotopes[ionisation_mode] = {round(p.mz, 5): round_floats(p.attributes.get('envelope', {}).get('isotopes', {}), precision=5) for p in data_scan.peaklist.peaks}
                            
                    if {'+', '-'} <= spectra.keys():
                        break
                
                exp = mspy_to_openms(spectra.values())
                opts = oms.PeakFileOptions()
                opts.setZstdCompression(True)
                opts.setMz32Bit(False)        # m/z en 32 bits (gain d'espace)
                opts.setIntensity32Bit(True)  # intensités en 32 bits (gain d'espace)
                mzml = oms.MzMLFile()
                mzml.setOptions(opts)
                mzml.store(mzml_file, exp)
                with open(json_file, 'w') as f:
                    json.dump(isotopes, f)
                sample.status = SampleStatus.analysed
            except (requests.exceptions.ConnectTimeout, urllib3.exceptions.MaxRetryError) as e:
                log_error(e, f"Connection to UNIFI server failed during download spectra for {sanitize_log(sample.reference)}")
                continue
            
            try:
                peaks_by_polarity = {}
                for ionisation_mode, scan in spectra.items():
                    if ionisation_mode is not None and scan.peaklist:
                        peaks_by_polarity[ionisation_mode] = [peak.mz for peak in scan.peaklist.peaks]
                annotations = annotate_peaks(peaks_by_polarity, sample.mass)
            except Exception as e:
                log_error(e, f"Automatic peak annotation failed for {sanitize_log(sample.reference)}")
                annotations = []
            for annotation in annotations:
                row = db.session.scalars(db.select(PeakAnnotation).where(
                    PeakAnnotation.sample_id == sample.id,
                    PeakAnnotation.charge == annotation['charge'],
                    PeakAnnotation.mz == annotation['mz']
                )).first()
                if row:
                    row.adduct = annotation['adduct']
                    row.neutral_mass = annotation['neutral_mass']
                else:
                    db.session.add(PeakAnnotation(
                        sample_id=sample.id,
                        charge=annotation['charge'],
                        mz=annotation['mz'],
                        adduct=annotation['adduct'],
                        neutral_mass=annotation['neutral_mass'],
                        user_id=sample.user_id,
                    ))
            if annotations:
                logger.info(f"{len(annotations)} peaks automatically annotated for {sanitize_log(sample.reference)}.")       

            try:
                db.session.commit()
                num_spectra = len(spectra)
                logger.info(f"{num_spectra} {'spectra' if num_spectra>1 else 'spectrum'} successfully saved to '{mzml_file}'.")
            except Exception as e:
                db.session.rollback()
                if os.path.exists(mzml_file):
                    os.path.remove(mzml_file)
                logger.warning(f"File was not saved because the following error occured: {e}")
        
        return {'status': 'success'}
    finally:
        r.delete(LOCK_KEY)
    