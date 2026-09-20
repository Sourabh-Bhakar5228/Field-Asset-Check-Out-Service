import os
from celery import Celery
from celery.schedules import crontab

# Set default Django settings module
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

app = Celery('artikate')

# Load configuration from Django settings with CELERY_ prefix
app.config_from_object('django.conf:settings', namespace='CELERY')

# Auto-discover tasks from installed apps
app.autodiscover_tasks()

# Celery Beat schedule: runs flag_overdue_checkouts hourly
app.conf.beat_schedule = {
    'flag-overdue-checkouts-hourly': {
        'task': 'field_assets.tasks.flag_overdue_checkouts',
        'schedule': crontab(minute=0),
    },
}
