from celery import Celery
from ..config import config

celery = Celery(
    __name__,
    broker_url=config.CELERY_BROKER_URL,
    result_backend=config.CELERY_RESULT_BACKEND,
)
celery.conf.update(
    task_serializer='json',
    result_serializer='json',
    accept_content=['json'],   # jamais de pickle : un message forgé = RCE
)

def init_celery(app):
    class ContextTask(celery.Task):
        def __call__(self, *args, **kwargs):
            with app.app_context():
                return self.run(*args, **kwargs)

    celery.Task = ContextTask
    celery.autodiscover_tasks(['app.tasks'])
    celery.set_default()
    
    celery.conf.beat_schedule = {
        # Check if there is spectra to download every hour
        'downlad_spectra': {
            'task': 'app.tasks.download_spectra.download_spectra',
            'schedule': 3600,
        },
        # Remove orphan structure file once per week
        'cleanup_orphan_files': {
            'task': 'app.tasks.cleanup.cleanup_orphan_files_task',
            'schedule': 604800,  # 7 days
        },
    }
    
    return celery