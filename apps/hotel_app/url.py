from django.urls import path
from . import views
from . import customer_views

urlpatterns = [
    path('', views.portal_cliente_home, name='portal_cliente_home'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('registro-cliente/', customer_views.registro_cliente_publico, name='registro_cliente_publico'),
    path('registro-cliente/verificar/<str:token>/', customer_views.verificar_registro_cliente, name='verificar_registro_cliente'),
    path('registro-cliente/reenviar-verificacion/', customer_views.reenviar_verificacion_cliente, name='reenviar_verificacion_cliente'),
    path('mi-portal/', customer_views.mis_reservas_cliente, name='mis_reservas_cliente'),
    path('portal/', customer_views.mis_reservas_cliente, name='portal_cliente'),

    # Nuevas rutas del flujo de reserva y pago en línea (Demo)
    path('reservar/habitacion/<int:habitacion_id>/', views.iniciar_reserva_web, name='iniciar_reserva_web'),
    path('reservar/datos-huesped/', views.checkout_datos_huesped, name='checkout_datos_huesped'),
    path('reservar/pagar/', views.pasarela_pago_simulada, name='pasarela_pago_simulada'),
    path('reservar/confirmacion/<int:reserva_id>/', views.confirmacion_reserva_exitoso, name='confirmacion_reserva_exitoso'),

    # Módulos Administrativos y de Recepción
    path('habitaciones/', views.lista_habitaciones, name='lista_habitaciones'),
    path('habitaciones/editar/<int:habitacion_id>/', views.editar_habitacion, name='editar_habitacion'),
    path('habitaciones/<int:habitacion_id>/accion/<str:accion>/', views.accion_habitacion, name='accion_habitacion'),
    path('huespedes/', views.lista_huespedes, name='lista_huespedes'),
    path('huespedes/nuevo/', views.crear_huesped, name='crear_huesped'),
    path('reservas/', views.lista_reservas, name='lista_reservas'),
    path('reservas/ocupantes/', views.lista_ocupantes_habitacion, name='lista_ocupantes_habitacion'),
    path('reservas/nueva/', views.crear_reserva, name='crear_reserva'),
    path('reservas/checkin/<int:reserva_id>/', views.realizar_checkin, name='realizar_checkin'),
    path('reservas/checkout/<int:reserva_id>/', views.realizar_checkout, name='realizar_checkout'),
    path('pagos/', views.lista_pagos, name='lista_pagos'),
    path('pagos/nuevo/', views.crear_pago, name='crear_pago'),
    path('servicios/', views.lista_servicios, name='lista_servicios'),
    path('servicios/nuevo/', views.crear_servicio, name='crear_servicio'),
    path('reportes/', views.vista_reportes, name='vista_reportes'),
    path('configuracion/', views.vista_configuracion, name='vista_configuracion'),
    path('habitaciones/nueva/', views.crear_habitacion, name='crear_habitacion'),
    path('reservas/cancelar/<int:reserva_id>/', views.cancelar_reserva_cliente, name='cancelar_reserva_cliente'),
    path('reservas/cancelar/personal/<int:reserva_id>/', views.cancelar_reserva_personal, name='cancelar_reserva_personal'),
    path('recepcion/hoy/', views.recepcion_hoy_view, name='recepcion_hoy'),
    path('reserva/<int:reserva_id>/solicitar-servicio/', views.solicitar_servicio_habitacion, name='solicitar_servicio_habitacion'),
    path('consumo/<int:consumo_id>/confirmar-pago/', views.confirmar_pago_consumo, name='confirmar_pago_consumo'),
    path('consumo/<int:consumo_id>/cancelar/', views.cancelar_consumo, name='cancelar_consumo'),
    path('reserva/<int:reserva_id>/factura-checkout/', views.factura_checkout, name='factura_checkout'),
    path('recuperar-password/', views.recuperar_password_solicitar, name='recuperar_password_solicitar'),
    path('recuperar-password/verificar/', views.recuperar_password_verificar, name='recuperar_password_verificar'),
    path('recuperar-password/cambiar/', views.recuperar_password_cambiar, name='recuperar_password_cambiar'),
]