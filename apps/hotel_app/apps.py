from django.apps import AppConfig

class HotelAppConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.hotel_app'  # <-- Es muy importante que lleve 'apps.' al principio