from flask import current_app

import json
import logging
import os

from ..models import db, MSSample, PeakAnnotation, PeakFormula
from ..utils.adducts import find_adduct
from ..utils.data_processing import load_mzml_spectra
from ..utils.errors import log_error, sanitize_log
from ..utils.peak_composition import compute_formulas
from .celery_app import celery

logger = logging.getLogger(__name__)

def parse_float_keys(pairs):
    """Object pairs hook to read dict with float keys from json"""

    result = {}
    for k, v in pairs:
        try:
            k = float(k)
        except ValueError:
            pass
        result[k] = v
    return result

def get_closest(data, target, max_diff=1e-6):
    """Trouver la clé la plus proche dans un dict avec des clés float"""

    if not data:
        return None
    closest_key = min(data.keys(), key=lambda k: abs(k - target))
    if abs(closest_key - target) > max_diff:
        return None
    return data[closest_key]

@celery.task(bind=True)
def compute_spectrum_formulas(self, sample_id):
    """
    Tâche Celery pour calculer les formules brutes des pics annotés d'un spectre MS.

    Le traitement lourd (lecture du mzML, appel à compute_formulas pour chaque
    annotation) est réalisé ici, dans le worker, hors du processus web.

    Args:
        sample_id (int): ID de l'échantillon MS

    Returns:
        dict: {'ok': True, 'sample_id': ..., 'results': [...]} en cas de succès,
              {'ok': False, 'error': ...} sinon
    """
    try:
        sample = db.session.get(MSSample, sample_id)
        if not sample:
            logger.error(f"Échantillon {sample_id} introuvable")
            return {'ok': False, 'error': 'Sample not found'}

        annotations = db.session.scalars(
            db.select(PeakAnnotation)
            .where(PeakAnnotation.sample_id == sample_id)
            .order_by(PeakAnnotation.charge.desc(), PeakAnnotation.mz)
        ).all()

        spectra_folder = os.path.join(current_app.config['UPLOAD_FOLDER'], 'ms', 'spectra')

        # Lecture du spectre depuis le mzML
        mzml_file = os.path.join(spectra_folder, f'{sample.id}.mzML')
        if not os.path.exists(mzml_file):
            logger.error(f"MzML file {mzml_file} does not exist.")
            return {'ok': False, 'error': 'Spectrum file does not exist.'}
        try:
            spectra = load_mzml_spectra(mzml_file)
        except Exception as e:
            log_error(e, f"Reading mzML file {mzml_file}")
            return {'ok': False, 'error': 'The spectrum could not be read.'}

        # Charger les spectres données depuis le json (ratio isotopiques)
        json_file = os.path.join(spectra_folder, f'{sample.id}.json')
        if not os.path.exists(json_file):
            logger.error(f"Json file {json_file} does not exist.")
            return {'ok': False, 'error': 'Data file does not exist.'}
        try:
            with open(json_file, "r") as f:
                isotopes = json.load(f, object_pairs_hook=parse_float_keys)
        except Exception as e:
            log_error(e, f"Reading json file {json_file}")
            return {'ok': False, 'error': 'Data could not be read.'}

        num_results = 0
        for ann in annotations:
            polarity = '+' if ann.charge > 0 else '-'
            adduct = find_adduct(polarity, ann.adduct) or {}
            scan = spectra.get(polarity, {}).get('scan')
            isotopes_pol = isotopes.get(polarity, None)
            # Remplacer les formules déjà persistées pour cette annotation
            for old in db.session.scalars(
                db.select(PeakFormula).where(PeakFormula.annotation_id == ann.id)
            ).all():
                db.session.delete(old)
            for candidate in compute_formulas(scan, ann.mz, ann.neutral_mass, ann.charge, get_closest(isotopes_pol, ann.mz)):
                db.session.add(PeakFormula(
                    annotation_id=ann.id,
                    formula=candidate.get('formula'),
                    neutral_mass=candidate.get('neutral_mass'),
                    mz_exp=candidate.get('mz_exp', ann.mz),
                    mz_theo=candidate.get('mz_theo'),
                    delta_ppm=candidate.get('delta_ppm'),
                    delta_mda=candidate.get('delta_mda'),
                    hc=candidate.get('hc'),
                    rdbe=candidate.get('rdbe'),
                    rms=candidate.get('rms'),
                ))
                num_results += 1
        db.session.commit()

        logger.info(f"{num_results} formula(s) computed for sample {sanitize_log(sample.reference)} (ID={sample.id})")
        return {'ok': True, 'sample_id': sample_id}

    except Exception as e:
        db.session.rollback()
        log_error(e, f"Formula computation for sample {sample_id}")
        return {'ok': False, 'error': 'Formula computation failed.'}
