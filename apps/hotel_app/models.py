from pathlib import Path

from django.conf import settings
from django.db import models
from django.templatetags.static import static
from django.utils import timezone
from django.utils.text import slugify
from .validators import validate_digits, validate_letters_and_spaces

# Cambia aquí el archivo para elegir qué foto mostrar en cada habitación.
# Las rutas parten de la carpeta media/, por ejemplo: habitaciones/foto.jpg.
IMAGENES_POR_TIPO = {
    'Sencilla': 'habitaciones/sencilla.jpg',
    'Doble': 'habitaciones/doble.jpg',
    'Matrimonial': 'habitaciones/photo-1618773928121-c32242e63f39.avif',
    'Familiar': 'habitaciones/hotel-en-bocas-del-toro-habitaciones-familiares-6.jpg',
}
IMAGENES_ESTATICAS_POR_TIPO = {
    'Sencilla': 'hotel_app/images/habitaciones/sencilla.jpg',
    'Doble': 'hotel_app/images/habitaciones/doble.jpg',
    'Matrimonial': 'hotel_app/images/habitaciones/matrimonial.avif',
    'Familiar': 'hotel_app/images/habitaciones/familiar.jpg',
}

IMAGEN_BANNER = 'hotel_app/images/habitaciones/portada.jpg'



class Habitacion(models.Model):
    ESTADOS_HABITACION = [
        ('Disponible', 'Disponible'),
        ('Reservada', 'Reservada'),
        ('Ocupada', 'Ocupada'),
        ('En limpieza', 'En limpieza'),
        ('En mantenimiento', 'En mantenimiento'),
    ]

    TIPOS_HABITACION = [
        ('Sencilla', 'Sencilla'),
        ('Doble', 'Doble'),
        ('Matrimonial', 'Matrimonial'),
        ('Familiar', 'Familiar'),
    ]

    ESTADOS_LIMPIEZA = [
        ('Limpio', 'Limpio'),
        ('Sucio', 'Sucio'),
        ('En proceso', 'En proceso'),
    ]
    ESTADOS_NO_RESERVABLES = ('En mantenimiento',)

    numero = models.CharField(max_length=10, unique=True, verbose_name="Número de Habitación")
    tipo = models.CharField(max_length=50, choices=TIPOS_HABITACION, verbose_name="Tipo de Habitación")
    capacidad = models.IntegerField(verbose_name="Capacidad máxima (Personas)")
    precio = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Precio por Noche (COP)")
    piso = models.IntegerField(verbose_name="Piso")
    estado = models.CharField(max_length=30, choices=ESTADOS_HABITACION, default='Disponible', verbose_name="Estado")
    limpieza = models.CharField(max_length=20, choices=ESTADOS_LIMPIEZA, default='Limpio', verbose_name="Estado de Limpieza")
    mantenimiento = models.CharField(max_length=100, default='Ninguno', verbose_name="Mantenimiento")
    
    imagen = models.ImageField(upload_to='habitaciones/', blank=True, null=True, verbose_name="Foto de la Habitación")
    imagen_url = models.CharField(max_length=255, blank=True, null=True, verbose_name="URL de Imagen")

    descripcion = models.TextField(blank=True, null=True, verbose_name="Descripción")

    def __str__(self):
        return f"Habitación {self.numero} - {self.tipo} ({self.estado})"

    def esta_disponible_para(self, fecha_ingreso, fecha_salida):
        if self.estado in self.ESTADOS_NO_RESERVABLES:
            return False
        if (
            self.estado == 'En limpieza'
            and fecha_ingreso <= timezone.localdate()
        ):
            return False

        reservas_que_se_cruzan = Reserva.objects.filter(
            habitacion=self,
            estado__in=['Confirmada', 'En curso'],
            fecha_ingreso__lt=fecha_salida,
            fecha_salida__gt=fecha_ingreso,
        )
        return not reservas_que_se_cruzan.exists()

    def actualizar_estado_segun_reservas(self):
        if self.estado in {'En mantenimiento', 'En limpieza'}:
            return

        if self.reserva_set.filter(estado='En curso').exists():
            nuevo_estado = 'Ocupada'
        elif self.reserva_set.filter(estado='Confirmada').exists():
            nuevo_estado = 'Reservada'
        else:
            nuevo_estado = 'Disponible'

        if self.estado != nuevo_estado:
            self.estado = nuevo_estado
            self.save(update_fields=['estado'])

    def get_imagen(self):
        if self.imagen_url:
            return self.imagen_url

        ruta_tipo = IMAGENES_POR_TIPO.get(self.tipo)
        if settings.DEBUG and ruta_tipo:
            archivo_tipo = Path(settings.MEDIA_ROOT) / ruta_tipo
            if archivo_tipo.is_file():
                return f'{settings.MEDIA_URL.rstrip("/")}/{ruta_tipo}'

        if settings.DEBUG and self.imagen:
            return self.imagen.url

        nombre_habitacion = slugify(self.numero)
        extensiones_imagen = {'.jpg', '.jpeg', '.png', '.webp', '.avif'}
        carpeta_imagenes = Path(settings.MEDIA_ROOT) / 'habitaciones'
        if settings.DEBUG and carpeta_imagenes.is_dir():
            for extension in ('jpg', 'jpeg', 'png', 'webp', 'avif'):
                nombre_archivo = f'habitacion-{nombre_habitacion}.{extension}'
                ruta_imagen = carpeta_imagenes / nombre_archivo
                if ruta_imagen.is_file():
                    return (
                        f'{settings.MEDIA_URL.rstrip("/")}/habitaciones/'
                        f'{nombre_archivo}'
                    )

            imagenes_disponibles = sorted(
                archivo.name
                for archivo in carpeta_imagenes.iterdir()
                if archivo.is_file()
                and archivo.suffix.lower() in extensiones_imagen
            )
            if imagenes_disponibles:
                try:
                    indice = int(self.numero) % len(imagenes_disponibles)
                except ValueError:
                    indice = sum(map(ord, self.numero)) % len(
                        imagenes_disponibles
                    )

                nombre_archivo = imagenes_disponibles[indice]
                return (
                    f'{settings.MEDIA_URL.rstrip("/")}/habitaciones/'
                    f'{nombre_archivo}'
                )

        return static(
            IMAGENES_ESTATICAS_POR_TIPO.get(
                self.tipo,
                IMAGENES_ESTATICAS_POR_TIPO['Sencilla'],
            ),
        )

class Huesped(models.Model):
    TIPOS_DOCUMENTO = [
        ('CC', 'Cédula de Ciudadanía'),
        ('CE', 'Cédula de Extranjería'),
        ('PAS', 'Pasaporte'),
        ('TI', 'Tarjeta de Identidad'),
    ]

    tipo_documento = models.CharField(max_length=10, choices=TIPOS_DOCUMENTO, default='CC', verbose_name="Tipo de Documento")
    numero_documento = models.CharField(
        max_length=20,
        unique=True,
        validators=[validate_digits],
        verbose_name="Número de Documento",
    )
    nombres = models.CharField(
        max_length=100,
        validators=[validate_letters_and_spaces],
        verbose_name="Nombres",
    )
    apellidos = models.CharField(
        max_length=100,
        validators=[validate_letters_and_spaces],
        verbose_name="Apellidos",
    )
    telefono = models.CharField(
        max_length=20,
        validators=[validate_digits],
        verbose_name="Teléfono",
    )
    correo = models.EmailField(verbose_name="Correo Electrónico")
    nacionalidad = models.CharField(
        max_length=50,
        default="Colombiana",
        validators=[validate_letters_and_spaces],
        verbose_name="Nacionalidad",
    )

    def __str__(self):
        return f"{self.nombres} {self.apellidos} ({self.numero_documento})"

class ServicioAdicional(models.Model):
    nombre = models.CharField(max_length=100, unique=True, verbose_name="Nombre del Servicio")
    precio = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Precio (COP)")
    descripcion = models.TextField(blank=True, null=True, verbose_name="Descripción")

    def __str__(self):
        return f"{self.nombre} - ${self.precio}"

class Reserva(models.Model):
    ESTADOS_RESERVA = [
        ('Pendiente', 'Pendiente de pago'),
        ('Confirmada', 'Confirmada'),
        ('En curso', 'En curso'),
        ('Finalizada', 'Finalizada'),
        ('Cancelada', 'Cancelada'),
    ]

    MODALIDADES_PAGO = [
        ('Completo', 'Pago Completo (100%)'),
        ('Anticipo', 'Pago Anticipado (50%)'),
    ]

    huesped = models.ForeignKey(Huesped, on_delete=models.CASCADE, verbose_name="Huésped")
    habitacion = models.ForeignKey(Habitacion, on_delete=models.CASCADE, verbose_name="Habitación")
    fecha_ingreso = models.DateField(verbose_name="Fecha de Ingreso (Check-in)")
    fecha_salida = models.DateField(verbose_name="Fecha de Salida (Check-out)")
    
    # Nuevos campos para la demo de pagos y reserva online
    cantidad_huespedes = models.IntegerField(default=1, verbose_name="Cantidad de Huéspedes")
    solicitudes_especiales = models.TextField(blank=True, null=True, verbose_name="Solicitudes Especiales")
    modalidad_pago = models.CharField(max_length=20, choices=MODALIDADES_PAGO, default='Completo', verbose_name="Modalidad de Pago")
    valor_total = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, verbose_name="Valor Total (COP)")
    saldo_pendiente = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, verbose_name="Saldo Pendiente (COP)")
    
    estado = models.CharField(max_length=30, choices=ESTADOS_RESERVA, default='Pendiente', verbose_name="Estado de la Reserva")
    fecha_creacion = models.DateTimeField(auto_now_add=True, verbose_name="Fecha de Creación")

    def __str__(self):
        return f"Reserva #{self.id} - {self.huesped} (Hab. {self.habitacion.numero})"

class Pago(models.Model):
    METODOS_PAGO = [
        ('Efectivo', 'Efectivo'),
        ('Transferencia', 'Transferencia bancaria'),
        ('Tarjeta débito', 'Tarjeta débito'),
        ('Tarjeta crédito', 'Tarjeta crédito'),
        ('PSE', 'PSE'),
        ('Nequi', 'Nequi'),
        ('Daviplata', 'Daviplata'),
    ]

    reserva = models.ForeignKey(Reserva, on_delete=models.CASCADE, verbose_name="Reserva asociada")
    monto = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Monto pagado (COP)")
    metodo_pago = models.CharField(max_length=30, choices=METODOS_PAGO, verbose_name="Método de Pago")
    fecha_pago = models.DateTimeField(auto_now_add=True, verbose_name="Fecha y Hora del Pago")
    observacion = models.TextField(blank=True, null=True, verbose_name="Observaciones / Comprobante")

    def __str__(self):
        return f"Pago de ${self.monto} ({self.metodo_pago}) - Reserva #{self.reserva.id}"

class TransaccionPago(models.Model):
    reserva = models.ForeignKey(Reserva, on_delete=models.CASCADE, verbose_name="Reserva asociada")
    referencia_pasarela = models.CharField(max_length=100, unique=True, verbose_name="Referencia de Transacción")
    metodo_pago = models.CharField(max_length=50, verbose_name="Método de Pago")
    monto_pagado = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Monto Pagado")
    estado_transaccion = models.CharField(max_length=30, default='Aprobada', verbose_name="Estado de Transacción")
    fecha_transaccion = models.DateTimeField(auto_now_add=True, verbose_name="Fecha de Transacción")

    def __str__(self):
        return f"Transacción #{self.id} - Ref: {self.referencia_pasarela} ({self.estado_transaccion})"
class AcompañanteReserva(models.Model):
    reserva = models.ForeignKey(Reserva, on_delete=models.CASCADE, related_name='acompanantes')
    nombres = models.CharField(max_length=100, verbose_name="Nombres")
    apellidos = models.CharField(max_length=100, verbose_name="Apellidos")
    tipo_documento = models.CharField(
        max_length=20,
        choices=Huesped.TIPOS_DOCUMENTO,
        default='CC',
        verbose_name="Tipo de Documento",
    )
    numero_documento = models.CharField(max_length=50, verbose_name="Número de Documento")
    telefono = models.CharField(max_length=20, blank=True, null=True, verbose_name="Teléfono")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=('reserva', 'numero_documento'),
                name='unique_acompanante_documento_por_reserva',
            ),
        ]

    def __str__(self):
        return f"{self.nombres} {self.apellidos} (Acompañante de Reserva #{self.reserva.id})"

class ConsumoHabitacion(models.Model):
    ESTADO_PAGO_CHOICES = [
        ('Pendiente', 'Pendiente de pago'),
        ('Pagado', 'Pagado'),
        ('Cancelado', 'Cancelado'),
    ]

    reserva = models.ForeignKey(Reserva, on_delete=models.CASCADE, related_name='consumos')
    servicio = models.ForeignKey(ServicioAdicional, on_delete=models.SET_NULL, null=True, blank=True)
    descripcion_detalle = models.TextField(help_text="Detalle de prendas o descripción del consumo")
    total = models.DecimalField(max_digits=10, decimal_places=2)
    estado_pago = models.CharField(max_length=20, choices=ESTADO_PAGO_CHOICES, default='Pendiente')
    fecha_solicitud = models.DateTimeField(auto_now_add=True)
    confirmado_por = models.ForeignKey(
        'auth.User', on_delete=models.SET_NULL, null=True, blank=True
    )

    def __str__(self):
        return f"Hab. {self.reserva.habitacion.numero} - ${self.total} ({self.estado_pago})"