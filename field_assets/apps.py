from django.apps import AppConfig
from django.db.backends.signals import connection_created


def configure_sqlite(sender, connection, **kwargs):
    if connection.vendor == 'sqlite':
        with connection.cursor() as cursor:
            cursor.execute('PRAGMA journal_mode=WAL;')
            cursor.execute('PRAGMA busy_timeout=10000;')


class FieldAssetsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'field_assets'
    verbose_name = 'Field Asset Management'

    def ready(self):
        connection_created.connect(configure_sqlite)
