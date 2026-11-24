from django.contrib import admin
from .models import (
    AcompañanteReserva,
    Habitacion,
    Huesped,
    ServicioAdicional,
    Reserva,
    Pago,
)

@admin.register(Habitacion)
class HabitacionAdmin(admin.ModelAdmin):
    list_display = ('numero', 'tipo', 'capacidad', 'precio', 'piso', 'estado')
    list_filter = ('tipo', 'estado', 'piso')
    search_fields = ('numero', 'tipo')

@admin.register(Huesped)
class HuespedAdmin(admin.ModelAdmin):
    list_display = ('numero_documento', 'nombres', 'apellidos', 'telefono', 'correo', 'nacionalidad')
    search_fields = ('numero_documento', 'nombres', 'apellidos')

@admin.register(ServicioAdicional)
class ServicioAdicionalAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'precio')
    search_fields = ('nombre',)

@admin.register(Reserva)
class ReservaAdmin(admin.ModelAdmin):
    list_display = ('id', 'huesped', 'habitacion', 'fecha_ingreso', 'fecha_salida', 'estado')
    list_filter = ('estado', 'fecha_ingreso')
    search_fields = ('huesped__nombres', 'huesped__apellidos', 'habitacion__numero')

@admin.register(Pago)
class PagoAdmin(admin.ModelAdmin):
    list_display = ('id', 'reserva', 'monto', 'metodo_pago', 'fecha_pago')
    list_filter = ('metodo_pago', 'fecha_pago')
    search_fields = ('reserva__id', 'metodo_pago')

@admin.register(AcompañanteReserva)
class AcompananteReservaAdmin(admin.ModelAdmin):
    list_display = (
        'nombres',
        'apellidos',
        'tipo_documento',
        'numero_documento',
        'reserva',
    )
    search_fields = (
        'nombres',
        'apellidos',
        'numero_documento',
        'reserva__habitacion__numero',
    )