from flask import current_app
from celery import shared_task

import pyopenms as oms
import os
import redis
import logging

from ..models import db, Analysis, Sample, SampleStatus
from ..utils.data_processing import UNIFIAPI, extract_trace_name, get_data, peak_picking, lock_mass_correct, mspy_to_openms, RTRange
from .celery_app import celery

LOCK_KEY = 'lock:download_spectra'

logger = logging.getLogger(__name__)

@celery.task(bind=True)
def download_spectra(self):
    """
    Tâche Celery pour récupérer les spectres depuis l'instrument.
    """
    
    r = celery.backend.client

    if not r.set(LOCK_KEY, '1', nx=True, ex=3600):
        logger.info("Tâche déjà en cours, l'éxécution de cette tâche va être ignorée.")
        return {'status': 'skipped'}
    try:
        unifi_config = current_app.config['UNIFI']
    
        samples = Sample.query.filter_by(status=SampleStatus.analysing, analysis_type='ms')
        
        if not samples:
            logger.warning("No samples in analysing status found.")
            r.delete(LOCK_KEY)
            return {'status': 'success'}
        else:
            logger.info(f"{samples.count()} MS samples in analysing status found.")
        
        api = UNIFIAPI(unifi_config['server'], certificate=unifi_config['certificate'])
        for sample in samples:
            mzml_folder = os.path.join(current_app.config['UPLOAD_FOLDER'], sample.analysis_type, 'spectra')
            os.makedirs(mzml_folder, exist_ok=True)
            mzml_file = os.path.join(mzml_folder, f'{sample.id}.mzML')
            if os.path.exists(mzml_file):
                logger.info(f"Skipped spectra downloading for {sample.reference} as mzML file already exists.")
                continue
            
            api.connect(unifi_config['username'], unifi_config['password'])
        
            data_folder = api.get_folder_by_path(unifi_config['data_folder'])
                
            sample_items = [item for item in data_folder.items() if item.type == "SampleResult" and item.name == sample.reference]
            
            if not sample_items:
                logger.warning(f"No samples items found for sample reference: {sample.reference}.")
                continue
            else:
                logger.info(f"{len(sample_items)} samples items found for sample reference: {sample.reference}.")
            
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
                ls_scan = get_data(specinfos['MS LockSpray Reference Data'])
                data_scan = get_data(
                    specinfos['DDA TOF MS'],
                    rt_range=RTRange(0.1, 0.3)
                )
                
                # Apply peak picking and lock mass correction
                data_scan = peak_picking(data_scan) 
                if data_scan.peaklist:
                    try:
                        data_scan = lock_mass_correct(data_scan, ls_scan, ionisation_mode)
                    except ValueError as e:
                        print(str(e))
                        print(sr)
                        print(specinfos['MS LockSpray Reference Data'])
                        raise e
                spectra[ionisation_mode] = data_scan
                        
                if {'+', '-'} <= spectra.keys():
                    break
            
            exp = mspy_to_openms(spectra.values())
            oms.MzMLFile().store(mzml_file, exp)
            num_spectra = len(spectra)
            logger.info(f"{num_spectra} {'spectra' if num_spectra>1 else 'spectrum'} successfully saved to '{mzml_file}'.")
        
        return {'status': 'success'}
    finally:
        r.delete(LOCK_KEY)
    