from django.core.management.base import BaseCommand
from apps.hotel_app.models import Habitacion

class Command(BaseCommand):
    help = 'Carga las 20 habitaciones iniciales del Hotel Brisas de La Guajira'

    def handle(self, *_args, **_kwargs):
        habitaciones_data = [
            # Sencillas (Piso 1, 6 habitaciones)
            {"numero": "101", "tipo": "Sencilla", "capacidad": 1, "precio": 90000, "piso": 1},
            {"numero": "102", "tipo": "Sencilla", "capacidad": 1, "precio": 90000, "piso": 1},
            {"numero": "103", "tipo": "Sencilla", "capacidad": 1, "precio": 90000, "piso": 1},
            {"numero": "104", "tipo": "Sencilla", "capacidad": 1, "precio": 90000, "piso": 1},
            {"numero": "105", "tipo": "Sencilla", "capacidad": 1, "precio": 90000, "piso": 1},
            {"numero": "106", "tipo": "Sencilla", "capacidad": 1, "precio": 90000, "piso": 1},

            # Dobles (Piso 2, 6 habitaciones)
            {"numero": "201", "tipo": "Doble", "capacidad": 2, "precio": 140000, "piso": 2},
            {"numero": "202", "tipo": "Doble", "capacidad": 2, "precio": 140000, "piso": 2},
            {"numero": "203", "tipo": "Doble", "capacidad": 2, "precio": 140000, "piso": 2},
            {"numero": "204", "tipo": "Doble", "capacidad": 2, "precio": 140000, "piso": 2},
            {"numero": "205", "tipo": "Doble", "capacidad": 2, "precio": 140000, "piso": 2},
            {"numero": "206", "tipo": "Doble", "capacidad": 2, "precio": 140000, "piso": 2},

            # Matrimoniales (Piso 3, 4 habitaciones)
            {"numero": "301", "tipo": "Matrimonial", "capacidad": 2, "precio": 150000, "piso": 3},
            {"numero": "302", "tipo": "Matrimonial", "capacidad": 2, "precio": 150000, "piso": 3},
            {"numero": "303", "tipo": "Matrimonial", "capacidad": 2, "precio": 150000, "piso": 3},
            {"numero": "304", "tipo": "Matrimonial", "capacidad": 2, "precio": 150000, "piso": 3},

            # Familiares (Piso 4, 4 habitaciones)
            {"numero": "401", "tipo": "Familiar", "capacidad": 4, "precio": 220000, "piso": 4},
            {"numero": "402", "tipo": "Familiar", "capacidad": 4, "precio": 220000, "piso": 4},
            {"numero": "403", "tipo": "Familiar", "capacidad": 4, "precio": 220000, "piso": 4},
            {"numero": "404", "tipo": "Familiar", "capacidad": 4, "precio": 220000, "piso": 4},
        ]

        contador = 0
        for hab in habitaciones_data:
            _, created = Habitacion.objects.get_or_create(
                numero=hab["numero"],
                defaults={
                    "tipo": hab["tipo"],
                    "capacidad": hab["capacidad"],
                    "precio": hab["precio"],
                    "piso": hab["piso"],
                    "estado": "Disponible"
                }
            )
            if created:
                contador += 1
                self.stdout.write(f"Habitación {hab['numero']} creada exitosamente.")
            else:
                self.stdout.write(f"La habitación {hab['numero']} ya existía.")

        self.stdout.write(f"\n¡Proceso finalizado! Se crearon {contador} habitaciones nuevas en MySQL.")