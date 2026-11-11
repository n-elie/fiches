from celery import shared_task
from flask import current_app
import os

from ..routes.admin_routes import delete_orphan_structure_files

@shared_task
def cleanup_orphan_files_task():
    return {'deleted': delete_orphan_structure_files(dry_run=False)}