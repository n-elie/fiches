from flask import current_app
from celery import shared_task

import time
import logging

from ..models import db, Analysis, Sample
from .celery_app import celery

logger = logging.getLogger(__name__)

@celery.task(bind=True)
def process_sample_analysis(self, sample_id):
    """
    Tâche Celery pour traiter un échantillon et créer une Analysis.

    Args:
        sample_id (int): ID de l'échantillon à analyser
    """
    try:
        # Récupérer l'échantillon
        sample = Sample.query.get(sample_id)
        if not sample:
            logger.error(f"Échantillon {sample_id} introuvable")
            return {'status': 'error', 'message': 'Sample not found'}

        logger.info(f"Début du traitement pour l'échantillon {sample.reference}")

        # TODO

        # Créer l'objet Analysis
        analysis = Analysis(
            sample_id=sample_id,
            results_file="foo bar", #TODO
        )

        db.session.add(analysis)
        db.session.commit()

        logger.info(f"Analysis créée pour {sample.reference}: ID={analysis.id}")
        return {
            'status': 'success',
            'analysis_id': analysis.id,
            'sample_reference': sample.reference
        }

    except Exception as e:
        logger.error(f"Erreur dans process_sample_analysis: {e}")
        db.session.rollback()
        return {'status': 'error', 'message': str(e)}