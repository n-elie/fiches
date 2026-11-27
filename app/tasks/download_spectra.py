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
from ..utils.data_processing import (UNIFIAPI, extract_trace_name, download_spectra_to_openms,
                                     centroid_and_lock_mass_correct, average_spectrum, RTRange,
                                     downsample_profile, filter_centroid_peaks)
from ..utils.errors import sanitize_log, log_error
from ..utils.peak_annotation import annotate_peaks
from .celery_app import celery

LOCK_KEY = 'lock:download_spectra'

logger = logging.getLogger(__name__)

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
                spectra = {}
                for sr in sample_results:
                    specinfos = sr.spectruminfos()
                    specinfos = {extract_trace_name(trace.name): trace for trace in specinfos}
                    ionisation_mode = specinfos['DDA TOF MS'].analyticalTechnique.ionisationMode
                    
                    if ionisation_mode in spectra.keys():
                        continue
                    
                    # Get data from server
                    lock_exp = download_spectra_to_openms(specinfos['MS LockSpray Reference Data'])
                    data_exp = download_spectra_to_openms(specinfos['DDA TOF MS'])
                    
                    # Centroid and Lock mass correct spectra
                    data_corrected_centroid_exp, data_corrected_profile_exp = centroid_and_lock_mass_correct(data_exp, lock_exp)
                    
                    # Average spectra
                    average_centroid_spec = average_spectrum(data_corrected_centroid_exp, rt_range=RTRange(0.1, 0.3))
                    average_profile_spec = average_spectrum(data_corrected_profile_exp, rt_range=RTRange(0.1, 0.3))
                    
                    # Filter peaks below threshold, deisotope and remove uncharge peaks
                    average_centroid_spec = filter_centroid_peaks(average_centroid_spec)

                    spectra[ionisation_mode] = {'centroid': average_centroid_spec, 'profile': downsample_profile(average_profile_spec)}

                    if {'+', '-'} <= spectra.keys():
                        break
                
                exp = oms.MSExperiment()
                for data in spectra.values():
                    exp.addSpectrum(data['centroid'])
                    exp.addSpectrum(data['profile'])
                opts = oms.PeakFileOptions()
                opts.setZstdCompression(True)
                opts.setMz32Bit(False)        # m/z en 32 bits (gain d'espace)
                opts.setIntensity32Bit(True)  # intensités en 32 bits (gain d'espace)
                mzml = oms.MzMLFile()
                mzml.setOptions(opts)
                mzml.store(mzml_file, exp)
                
                sample.status = SampleStatus.analysed
            except (requests.exceptions.ConnectTimeout, urllib3.exceptions.MaxRetryError) as e:
                log_error(e, f"Connection to UNIFI server failed during download spectra for {sanitize_log(sample.reference)}")
                continue
            
            try:
                peaks_by_polarity = {}
                for ionisation_mode, data in spectra.items():
                    if ionisation_mode is not None:
                        peaks_by_polarity[ionisation_mode] = [mz for mz in data['centroid'].get_peaks()[0]]
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
    