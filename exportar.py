import os
import django
from django.core.management import call_command

# Configurar entorno de Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'hotel_brisas.settings')
django.setup()

# Ejecutar el comando dumpdata directamente desde Python
with open('data.json', 'w', encoding='utf-8') as f:
    call_command(
        'dumpdata',
        indent=2,
        exclude=['auth.permission', 'contenttypes', 'admin.logentry', 'sessions.session'],
        stdout=f
    )
print("¡Base de datos exportada con éxito a data.json!")