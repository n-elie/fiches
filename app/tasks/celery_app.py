from celery import Celery
from ..config import config

celery = Celery(
    __name__,
    broker_url=config.CELERY_BROKER_URL,
    result_backend=config.CELERY_RESULT_BACKEND)

def init_celery(app):
    class ContextTask(celery.Task):
        def __call__(self, *args, **kwargs):
            with app.app_context():
                return self.run(*args, **kwargs)

    celery.Task = ContextTask
    celery.autodiscover_tasks(['app.tasks'])
    celery.set_default()
    return celery