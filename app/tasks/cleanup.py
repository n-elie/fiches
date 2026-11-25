from celery import shared_task
from flask import current_app
import os

from ..routes.admin_routes import delete_orphan_files

@shared_task
def cleanup_orphan_files_task():
    """Supprime tous les fichiers orphelins (structures, spectres mzML/json)."""
    return {'deleted': delete_orphan_files(dry_run=False)}