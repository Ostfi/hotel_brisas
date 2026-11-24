from decimal import Decimal
import logging
import uuid
from datetime import datetime
from pathlib import Path
from smtplib import SMTPException
from django.contrib import messages
from django.contrib.auth import get_user_model, login, logout
from functools import wraps
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import Group, User
from django.db import transaction
from django.db.models import Q, Sum
from django.forms import formset_factory
from django.http import Http404, HttpResponseForbidden, HttpResponseNotAllowed
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST
from .forms import (
    CheckinAcompananteForm,
    CheckinAcompananteFormSet,
    CheckinOcupacionForm,
    FechasReservaWebForm,
    HabitacionCreacionForm,
    HabitacionEdicionForm,
    HuespedForm,
    InicioSesionForm,
    PagoForm,
    PagoCheckoutForm,
    ReservaForm,
    ServicioAdicionalForm,
)
from .models import (
    AcompañanteReserva,
    ConsumoHabitacion,
    Habitacion,
    Huesped,
    IMAGEN_BANNER,
    Reserva,
    ServicioAdicional,
    Pago,
    TransaccionPago,
)
from django.core.mail import send_mail
from django.conf import settings
import csv
from django.db.models import Q
from django.http import HttpResponse
logger = logging.getLogger(__name__)
from datetime import date
from decimal import Decimal
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.contrib.auth.decorators import login_required
from .models import Reserva, ServicioAdicional, ConsumoHabitacion
from django.core.mail import send_mail
import secrets

def es_administrador(user):
    return user.is_superuser or user.groups.filter(
        name='Administradores',
    ).exists()


def es_personal(user):
    return (
        es_administrador(user)
        or user.is_staff
        or user.groups.filter(name='Recepcionistas').exists()
    )


def requiere_rol(verificar_rol):
    def decorador(view_func):
        @wraps(view_func)
        @login_required(login_url='login')
        def vista_protegida(request, *args, **kwargs):
            if not verificar_rol(request.user):
                return HttpResponseForbidden(
                    'No tienes permiso para acceder a esta página.',
                )
            return view_func(request, *args, **kwargs)
        return vista_protegida
    return decorador


@login_required
@require_POST
def cancelar_reserva_cliente(request, reserva_id):
    huesped = Huesped.objects.filter(correo=request.user.email).first()
    reserva = get_object_or_404(Reserva, id=reserva_id, huesped=huesped)
    
    # Validar que la cancelación sea estrictamente antes del día de ingreso (check-in)
    hoy = date.today()
    if hoy >= reserva.fecha_ingreso:
        messages.error(request, "No es posible cancelar la reserva el mismo día del ingreso o después de la fecha de check-in.")
        return redirect('mis_reservas_cliente')
    
    if reserva.estado == 'Cancelada':
        messages.warning(request, "Esta reserva ya se encuentra cancelada.")
        return redirect('mis_reservas_cliente')

    # Aplicar lógica de cancelación
    reserva.estado = 'Cancelada'
    reserva.save()

    habitacion = reserva.habitacion
    habitacion.actualizar_estado_segun_reservas()

    messages.success(
        request,
        f'Reserva #{reserva.id} cancelada. El estado de la habitación se '
        'actualizó según las demás reservas.',
    )
    return redirect('mis_reservas_cliente')


@requiere_rol(es_personal)
@require_POST
def cancelar_reserva_personal(request, reserva_id):
    with transaction.atomic():
        reserva = get_object_or_404(
            Reserva.objects.select_for_update().select_related('habitacion'),
            id=reserva_id,
        )
        if reserva.estado != 'Confirmada':
            messages.error(
                request,
                'Solo se pueden cancelar reservas confirmadas.',
            )
            return redirect('lista_reservas')

        habitacion = reserva.habitacion
        reserva.estado = 'Cancelada'
        reserva.save(update_fields=['estado'])
        habitacion.actualizar_estado_segun_reservas()

    messages.success(
        request,
        f'Reserva #{reserva.id} cancelada. El estado de la habitación se '
        'actualizó según las demás reservas.',
    )
    return redirect('lista_reservas')

def portal_cliente_home(request):
    habitaciones = (
        Habitacion._base_manager.exclude(
            estado__in=Habitacion.ESTADOS_NO_RESERVABLES,
        )
        .order_by('numero')
    )
    servicios = ServicioAdicional.objects.all()
    imagen_banner_path = (
        Path(settings.MEDIA_ROOT) / 'habitaciones' / IMAGEN_BANNER
    )
    imagen_banner_version = imagen_banner_path.stat().st_mtime_ns
    return render(request, 'hotel_app/portal_cliente_home.html', {
        'habitaciones': habitaciones,
        'servicios': servicios,
        'imagen_banner': IMAGEN_BANNER,
        'imagen_banner_version': imagen_banner_version,
        'es_cliente': (
            request.user.is_authenticated
            and not request.user.is_staff
            and request.user.groups.filter(name='Clientes').exists()
        ),
        'es_personal': (
            request.user.is_authenticated
            and es_personal(request.user)
        ),
    })

def registro_cliente_publico(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        email = request.POST.get('email')
        password = request.POST.get('password')
        confirm_password = request.POST.get('confirm_password')
        nombres = request.POST.get('nombres')
        apellidos = request.POST.get('apellidos')
        telefono = request.POST.get('telefono')
        tipo_documento = request.POST.get('tipo_documento')
        documento = request.POST.get('documento')
        nacionalidad = request.POST.get('nacionalidad')

        if password != confirm_password:
            messages.error(request, "Las contraseñas no coinciden. Por favor, verifícalas.")
            return redirect('registro_cliente_publico')

        if User.objects.filter(username=username).exists():
            messages.error(request, "El nombre de usuario ya está en uso.")
            return redirect('registro_cliente_publico')

        if User.objects.filter(email=email).exists():
            messages.error(request, "El correo electrónico ya está registrado.")
            return redirect('registro_cliente_publico')

        user = User.objects.create_user(username=username, email=email, password=password)
        client_group, _ = Group.objects.get_or_create(name='Clientes')
        user.groups.add(client_group)

        Huesped.objects.create(
            nombres=nombres,
            apellidos=apellidos,
            tipo_documento=tipo_documento,
            numero_documento=documento,
            telefono=telefono,
            correo=email,
            nacionalidad=nacionalidad
        )

        messages.success(request, "¡Cuenta creada con éxito! Ahora puedes iniciar sesión.")
        return redirect('login')

    return render(request, 'hotel_app/registro_cliente.html')

@login_required
def mis_reservas_cliente(request):
    huesped = Huesped.objects.filter(correo=request.user.email).first()
    reservas = Reserva.objects.filter(huesped=huesped) if huesped else []
    
    # Asegúrate de usar .all() sin ningún .filter(estado=...)
    habitaciones = Habitacion.objects.all().order_by('numero')

    return render(request, 'hotel_app/portal_cliente_dashboard.html', {
        'reservas': reservas,
        'habitaciones': habitaciones,
        'huesped': huesped
    })

# --- NUEVAS VISTAS PARA EL FLUJO DE RESERVA Y PAGO EN LÍNEA (DEMO) ---

def _es_cliente(request):
    return (
        not request.user.is_staff
        and not request.user.is_superuser
        and request.user.groups.filter(name='Clientes').exists()
    )


def _denegar_si_no_es_cliente(request):
    if not _es_cliente(request):
        return HttpResponseForbidden(
            'Este proceso de reserva está disponible únicamente para clientes.',
        )
    return None


@login_required
def iniciar_reserva_web(request, habitacion_id):
    habitacion = get_object_or_404(Habitacion, id=habitacion_id)
    form = FechasReservaWebForm(
        request.POST or None,
        habitacion=habitacion,
    )

    if request.method == 'POST':
        if form.is_valid():
            fecha_ingreso = form.cleaned_data['fecha_ingreso']
            fecha_salida = form.cleaned_data['fecha_salida']
            if not habitacion.esta_disponible_para(
                fecha_ingreso,
                fecha_salida,
            ):
                form.add_error(
                    None,
                    'La habitación no está disponible para las fechas seleccionadas. Elige otras fechas.',
                )
            else:
                noches = (fecha_salida - fecha_ingreso).days
                valor_total = habitacion.precio * noches

                request.session['reserva_temporal'] = {
                    'habitacion_id': habitacion.id,
                    'fecha_ingreso': fecha_ingreso.isoformat(),
                    'fecha_salida': fecha_salida.isoformat(),
                    'cantidad_huespedes': form.cleaned_data[
                        'cantidad_huespedes'
                    ],
                    'noches': noches,
                    'valor_total': str(valor_total),
                }
                return redirect('checkout_datos_huesped')

    return render(request, 'hotel_app/iniciar_reserva.html', {
        'habitacion': habitacion,
        'form': form,
        'fecha_minima': timezone.localdate().isoformat(),
    })

@login_required
def checkout_datos_huesped(request):
    denegacion = _denegar_si_no_es_cliente(request)
    if denegacion:
        return denegacion
    datos_reserva = request.session.get('reserva_temporal')
    if not datos_reserva:
        messages.error(request, 'No hay ninguna reserva en proceso. Selecciona una habitación.')
        return redirect('mis_reservas_cliente')

    habitacion = get_object_or_404(Habitacion, id=datos_reserva['habitacion_id'])
    huesped = Huesped.objects.filter(
        correo__iexact=request.user.email,
    ).first()
    form = HuespedForm(
        request.POST or None,
        instance=huesped,
        initial={'correo': request.user.email},
    )
    form.fields['correo'].disabled = True
    if request.method == 'POST' and form.is_valid():
        huesped = form.save(commit=False)
        huesped.correo = request.user.email
        huesped.save()
        datos_reserva['huesped_id'] = huesped.pk
        datos_reserva['solicitudes'] = request.POST.get(
            'solicitudes_especiales',
            '',
        ).strip()
        request.session['reserva_temporal'] = datos_reserva
        return redirect('pasarela_pago_simulada')

    return render(request, 'hotel_app/checkout_huesped.html', {
        'habitacion': habitacion,
        'datos': datos_reserva,
        'form': form,
    })

@login_required
def pasarela_pago_simulada(request):
    denegacion = _denegar_si_no_es_cliente(request)
    if denegacion:
        return denegacion
    datos_reserva = request.session.get('reserva_temporal')
    if not datos_reserva:
        messages.error(request, 'No hay ninguna reserva en proceso. Selecciona una habitación.')
        return redirect('mis_reservas_cliente')
    if not datos_reserva.get('huesped_id'):
        messages.error(request, 'Completa tus datos personales antes de continuar al pago.')
        return redirect('checkout_datos_huesped')

    habitacion = get_object_or_404(Habitacion, id=datos_reserva['habitacion_id'])
    try:
        fecha_ingreso = datetime.strptime(
            datos_reserva['fecha_ingreso'],
            '%Y-%m-%d',
        ).date()
        fecha_salida = datetime.strptime(
            datos_reserva['fecha_salida'],
            '%Y-%m-%d',
        ).date()
        cantidad_huespedes = int(datos_reserva['cantidad_huespedes'])
    except (KeyError, TypeError, ValueError):
        request.session.pop('reserva_temporal', None)
        messages.error(request, 'Los datos de la reserva no son válidos. Inicia de nuevo.')
        return redirect('mis_reservas_cliente')

    if (
        fecha_ingreso < timezone.localdate()
        or fecha_salida <= fecha_ingreso
        or cantidad_huespedes < 1
        or cantidad_huespedes > habitacion.capacidad
    ):
        request.session.pop('reserva_temporal', None)
        messages.error(
            request,
            'Las fechas o la cantidad de huéspedes ya no son válidas. Inicia de nuevo.',
        )
        return redirect('mis_reservas_cliente')

    noches = (fecha_salida - fecha_ingreso).days
    valor_total = habitacion.precio * noches
    datos_reserva.update({
        'noches': noches,
        'valor_total': str(valor_total),
    })
    request.session['reserva_temporal'] = datos_reserva
    form = PagoCheckoutForm(request.POST or None)

    if request.method == 'POST':
        if form.is_valid():
            modalidad_pago = form.cleaned_data['modalidad_pago']
            metodo_pago = form.cleaned_data['metodo_pago']

            with transaction.atomic():
                habitacion = (
                    Habitacion.objects.select_for_update()
                    .filter(pk=datos_reserva['habitacion_id'])
                    .first()
                )
                if not habitacion or not habitacion.esta_disponible_para(
                    fecha_ingreso,
                    fecha_salida,
                ):
                    messages.error(
                        request,
                        'La habitación no está disponible para esas fechas. El pago no fue procesado.',
                    )
                    request.session.pop('reserva_temporal', None)
                    return redirect('mis_reservas_cliente')
                if cantidad_huespedes > habitacion.capacidad:
                    messages.error(
                        request,
                        'La capacidad de la habitación cambió. El pago no fue procesado.',
                    )
                    request.session.pop('reserva_temporal', None)
                    return redirect('mis_reservas_cliente')

                huesped = get_object_or_404(
                    Huesped,
                    pk=datos_reserva['huesped_id'],
                    correo__iexact=request.user.email,
                )
                valor_total = habitacion.precio * noches
                monto_a_pagar = valor_total
                if modalidad_pago == 'Anticipo':
                    monto_a_pagar = (
                        valor_total / Decimal('2')
                    ).quantize(Decimal('0.01'))
                saldo_pendiente = valor_total - monto_a_pagar
                reserva = Reserva.objects.create(
                    huesped=huesped,
                    habitacion=habitacion,
                    fecha_ingreso=fecha_ingreso,
                    fecha_salida=fecha_salida,
                    cantidad_huespedes=cantidad_huespedes,
                    solicitudes_especiales=datos_reserva.get('solicitudes', ''),
                    modalidad_pago=modalidad_pago,
                    valor_total=valor_total,
                    saldo_pendiente=saldo_pendiente,
                    estado='Confirmada',
                )
                habitacion.actualizar_estado_segun_reservas()

                referencia = f'REF-BRISAS-{uuid.uuid4().hex[:12].upper()}'
                TransaccionPago.objects.create(
                    reserva=reserva,
                    referencia_pasarela=referencia,
                    metodo_pago=metodo_pago,
                    monto_pagado=monto_a_pagar,
                    estado_transaccion='Aprobada',
                )
                Pago.objects.create(
                    reserva=reserva,
                    monto=monto_a_pagar,
                    metodo_pago=metodo_pago,
                    observacion=f'Pago online vía {metodo_pago} - Ref: {referencia}',
                )

            asunto = (
                f'Confirmación de Reserva #{reserva.pk} - Hotel Brisas de La Guajira'
            )
            mensaje = (
                f'¡Hola {huesped.nombres}!\n\n'
                'Tu reserva en el Hotel Brisas de La Guajira se ha realizado con éxito.\n\n'
                'Detalles de tu estancia:\n'
                f'- Código de Reserva: #{reserva.pk}\n'
                f'- Habitación: {habitacion.numero} ({habitacion.tipo})\n'
                f'- Fecha de Entrada: {reserva.fecha_ingreso}\n'
                f'- Fecha de Salida: {reserva.fecha_salida}\n'
                f'- Total de la reserva: ${valor_total} COP\n'
                f'- Total pagado: ${monto_a_pagar} COP\n'
                f'- Saldo pendiente: ${saldo_pendiente} COP\n'
                f'- Referencia de pago: {referencia}\n\n'
                '¡Te esperamos!'
            )
            destinatarios_hotel = {
                settings.HOTEL_NOTIFICATION_EMAIL,
                *get_user_model().objects.filter(
                    Q(is_superuser=True)
                    | Q(groups__name__in=['Administradores', 'Recepcionistas']),
                ).exclude(email='').values_list('email', flat=True),
            }
            try:
                correo_cliente_enviado = send_mail(
                    asunto,
                    mensaje,
                    settings.DEFAULT_FROM_EMAIL,
                    [huesped.correo],
                    fail_silently=False,
                )
                if correo_cliente_enviado != 1:
                    raise SMTPException('No se pudo entregar la confirmación al huésped.')
            except (OSError, SMTPException):
                logger.exception(
                    'No se pudo enviar la confirmación de reserva %s al huésped.',
                    reserva.pk,
                )
                messages.warning(
                    request,
                    'La reserva fue confirmada, pero no se pudo enviar el correo al huésped.',
                )
                request.session['reserva_correo_enviado'] = False
            else:
                request.session['reserva_correo_enviado'] = True

            try:
                sent = send_mail(
                    asunto,
                    mensaje,
                    settings.DEFAULT_FROM_EMAIL,
                    sorted(destinatarios_hotel),
                    fail_silently=False,
                )
                if sent != 1:
                    raise SMTPException('No se pudo entregar el aviso de reserva al hotel.')
            except (OSError, SMTPException):
                logger.exception(
                    'No se pudo enviar el aviso de reserva %s al hotel.',
                    reserva.pk,
                )

            request.session.pop('reserva_temporal', None)
            return redirect(
                'confirmacion_reserva_exitoso',
                reserva_id=reserva.pk,
            )

    return render(request, 'hotel_app/pasarela_pago.html', {
        'habitacion': habitacion,
        'datos': datos_reserva,
        'valor_total': valor_total,
        'anticipo': valor_total / Decimal('2'),
        'form': form,
    })

@login_required
def confirmacion_reserva_exitoso(request, reserva_id):
    denegacion = _denegar_si_no_es_cliente(request)
    if denegacion:
        return denegacion
    reserva = get_object_or_404(
        Reserva.objects.select_related('habitacion', 'huesped'),
        id=reserva_id,
        huesped__correo__iexact=request.user.email,
    )
    return render(request, 'hotel_app/confirmacion_reserva.html', {
        'reserva': reserva,
        'correo_enviado': request.session.pop(
            'reserva_correo_enviado',
            None,
        ),
    })

# --- FIN DE VISTAS NUEVAS ---

@requiere_rol(es_administrador)
def vista_configuracion(request):
    user_model = get_user_model()
    usuarios = user_model.objects.filter(
        Q(is_superuser=True)
        | Q(groups__name='Administradores')
        | Q(groups__name='Recepcionistas')
    ).distinct().order_by('-date_joined')

    if request.method == 'POST':
        if 'eliminar_usuario_id' in request.POST:
            user_id = request.POST.get('eliminar_usuario_id')
            usuario_a_eliminar = get_object_or_404(user_model, id=user_id)
            
            if usuario_a_eliminar == request.user:
                messages.error(request, "No puedes eliminar tu propia cuenta de administrador.")
            else:
                usuario_a_eliminar.delete()
                messages.success(request, "Usuario eliminado correctamente del sistema.")
            return redirect('vista_configuracion')

        nuevo_usuario = request.POST.get('nuevo_usuario', '').strip()
        password = request.POST.get('password')
        rol = request.POST.get('rol')

        if (
            nuevo_usuario
            and password
            and rol in {'admin', 'recepcion', 'cliente'}
            and not User.objects.filter(username__iexact=nuevo_usuario).exists()
        ):
            if rol == 'admin':
                user = User.objects.create_superuser(username=nuevo_usuario, password=password)
                admin_group, _ = Group.objects.get_or_create(name='Administradores')
                user.groups.add(admin_group)
            elif rol == 'recepcion':
                user = User.objects.create_user(username=nuevo_usuario, password=password)
                user.is_staff = True
                user.save()
                recep_group, _ = Group.objects.get_or_create(name='Recepcionistas')
                user.groups.add(recep_group)
            else:
                user = User.objects.create_user(username=nuevo_usuario, password=password)
                client_group, _ = Group.objects.get_or_create(name='Clientes')
                user.groups.add(client_group)

            messages.success(request, "Usuario creado exitosamente.")
            return redirect('vista_configuracion')
        messages.error(
            request,
            'Verifica el nombre, la contraseña y el rol. El usuario podría existir ya.',
        )

    return render(request, 'hotel_app/configuracion.html', {'usuarios': usuarios})

@requiere_rol(es_administrador)
def vista_reportes(request):
    total_habitaciones = Habitacion.objects.count()
    habitaciones_ocupadas = Habitacion.objects.filter(estado__in=['Ocupada', 'Reservada']).count()
    
    porcentaje_ocupacion = 0
    if total_habitaciones > 0:
        porcentaje_ocupacion = round((habitaciones_ocupadas / total_habitaciones) * 100, 1)

    total_huespedes = Huesped.objects.count()
    total_reservas = Reserva.objects.count()
    ingresos_totales = Pago.objects.aggregate(Sum('monto'))['monto__sum'] or 0

    context = {
        'total_habitaciones': total_habitaciones,
        'habitaciones_ocupadas': habitaciones_ocupadas,
        'porcentaje_ocupacion': porcentaje_ocupacion,
        'total_huespedes': total_huespedes,
        'total_reservas': total_reservas,
        'ingresos_totales': ingresos_totales,
    }

    return render(request, 'hotel_app/reportes.html', context)

@requiere_rol(es_personal)
def lista_servicios(request):
    servicios = ServicioAdicional.objects.all().order_by('nombre')
    return render(request, 'hotel_app/servicios.html', {'servicios': servicios})

@requiere_rol(es_personal)
def crear_servicio(request):
    form = ServicioAdicionalForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'El servicio se guardó correctamente.')
        return redirect('lista_servicios')

    if request.method == 'POST':
        messages.error(request, 'Revisa los datos del servicio.')
    return render(request, 'hotel_app/crear_servicios.html', {'form': form})

@requiere_rol(es_personal)
def lista_pagos(request):
    pagos = Pago.objects.all().order_by('-fecha_pago')
    return render(request, 'hotel_app/pagos.html', {'pagos': pagos})

@requiere_rol(es_personal)
def crear_pago(request):
    form = PagoForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'El pago se guardó correctamente.')
        return redirect('lista_pagos')

    if request.method == 'POST':
        messages.error(request, 'Revisa los datos del pago.')
    return render(request, 'hotel_app/crear_pago.html', {'form': form})

@requiere_rol(es_personal)
def lista_reservas(request):
    reservas = list(
        Reserva.objects.select_related('huesped', 'habitacion')
        .prefetch_related('consumos')
        .order_by('-fecha_creacion')
    )
    for reserva in reservas:
        reserva.total_servicios_pendientes = sum(
            (
                consumo.total
                for consumo in reserva.consumos.all()
                if consumo.estado_pago == 'Pendiente'
            ),
            Decimal('0.00'),
        )
        reserva.total_pendiente_checkout = (
            reserva.saldo_pendiente + reserva.total_servicios_pendientes
        )
    return render(request, 'hotel_app/reservas.html', {
        'reservas': reservas,
        'metodos_pago': Pago.METODOS_PAGO,
    })


@requiere_rol(es_personal)
def lista_ocupantes_habitacion(request):
    reservas = (
        Reserva.objects.filter(estado='En curso')
        .select_related('huesped', 'habitacion')
        .prefetch_related('acompanantes')
        .order_by('habitacion__numero')
    )
    return render(
        request,
        'hotel_app/ocupantes_habitacion.html',
        {'reservas': reservas},
    )


@requiere_rol(es_personal)
def crear_reserva(request):
    form = ReservaForm(request.POST or None)

    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            try:
                habitacion = Habitacion.objects.select_for_update().get(
                    pk=form.cleaned_data['habitacion'].pk,
                )
            except Habitacion.DoesNotExist:
                form.add_error(
                    'habitacion',
                    'La habitación seleccionada ya no está disponible.',
                )
            else:
                if not habitacion.esta_disponible_para(
                    form.cleaned_data['fecha_ingreso'],
                    form.cleaned_data['fecha_salida'],
                ):
                    form.add_error(
                        'habitacion',
                        'La habitación no está disponible para esas fechas.',
                    )
                else:
                    reserva = form.save(commit=False)
                    reserva.habitacion = habitacion
                    reserva.estado = 'Confirmada'
                    reserva.save()
                    habitacion.actualizar_estado_segun_reservas()

        if not form.errors:
            messages.success(request, 'La reserva se guardó correctamente.')
            return redirect('lista_reservas')

    return render(request, 'hotel_app/crear_reserva.html', {
        'form': form,
        'huespedes': form.fields['huesped'].queryset,
        'habitaciones': form.fields['habitacion'].queryset,
    })

def login_view(request):
    if request.method == 'POST':
        form = InicioSesionForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            
            if user.is_superuser or user.groups.filter(name='Administradores').exists():
                return redirect('lista_habitaciones')
            elif user.groups.filter(name='Recepcionistas').exists() or user.is_staff:
                return redirect('lista_reservas')
            elif user.groups.filter(name='Clientes').exists():
                return redirect('mis_reservas_cliente')
            logout(request)
            messages.error(
                request,
                'Tu cuenta todavía no tiene un rol asignado. Contacta al administrador.',
            )
            return redirect('login')
        else:
            messages.error(request, "Usuario o contraseña incorrectos.")
    else:
        form = InicioSesionForm()
    
    return render(request, 'hotel_app/login.html', {'form': form})

@require_POST
def logout_view(request):
    logout(request)
    return redirect('login')

@login_required(login_url='login')
def portal_cliente(request):
    if (
        request.user.is_staff
        or not request.user.groups.filter(name='Clientes').exists()
    ):
        return redirect('portal_cliente_home')
    return redirect('mis_reservas_cliente')

@requiere_rol(es_personal)
def lista_habitaciones(request):
    habitaciones = Habitacion.objects.all().order_by('numero')
    tipo = request.GET.get('tipo', '')
    reporte_limpieza = request.GET.get('reporte') == 'limpieza'

    if tipo in dict(Habitacion.TIPOS_HABITACION):
        habitaciones = habitaciones.filter(tipo=tipo)
    if reporte_limpieza:
        habitaciones = habitaciones.exclude(limpieza='Limpio')

    return render(request, 'hotel_app/habitaciones.html', {
        'habitaciones': habitaciones,
        'tipo_actual': tipo,
        'reporte_limpieza': reporte_limpieza,
    })

@requiere_rol(es_personal)
def editar_habitacion(request, habitacion_id):
    habitacion = get_object_or_404(Habitacion, pk=habitacion_id)
    form = HabitacionEdicionForm(
        request.POST or None,
        request.FILES or None,
        instance=habitacion,
    )
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Los cambios de la habitación se guardaron correctamente.')
        return redirect('lista_habitaciones')

    return render(request, 'hotel_app/editar_habitacion.html', {
        'habitacion': habitacion,
        'form': form,
    })

@require_POST
@requiere_rol(es_personal)
def accion_habitacion(request, habitacion_id, accion):
    habitacion = get_object_or_404(Habitacion, pk=habitacion_id)

    if accion == 'limpiar':
        if habitacion.estado == 'Ocupada':
            messages.error(
                request,
                'No se puede marcar como limpia una habitación ocupada.',
            )
            return redirect('lista_habitaciones')

        habitacion.limpieza = 'Limpio'
        update_fields = ['limpieza']
        if habitacion.estado == 'En limpieza':
            habitacion.estado = 'Disponible'
            update_fields.append('estado')
        habitacion.save(update_fields=update_fields)
        habitacion.actualizar_estado_segun_reservas()
        messages.success(request, f'La habitación {habitacion.numero} quedó marcada como limpia.')
    elif accion == 'bloquear':
        if habitacion.estado != 'Disponible':
            messages.error(request, 'Solo se pueden bloquear habitaciones disponibles.')
        else:
            habitacion.estado = 'En mantenimiento'
            habitacion.mantenimiento = 'Bloqueada temporalmente'
            habitacion.save(update_fields=['estado', 'mantenimiento'])
            messages.success(request, f'La habitación {habitacion.numero} quedó bloqueada.')
    elif accion == 'desbloquear':
        if habitacion.mantenimiento != 'Bloqueada temporalmente':
            messages.error(request, 'Esta habitación no tiene un bloqueo temporal para retirar.')
        else:
            habitacion.estado = 'Disponible'
            habitacion.mantenimiento = 'Ninguno'
            habitacion.save(update_fields=['estado', 'mantenimiento'])
            messages.success(request, f'La habitación {habitacion.numero} quedó disponible.')
    else:
        raise Http404('Acción de habitación no válida.')

    return redirect('lista_habitaciones')

@requiere_rol(es_personal)
def lista_huespedes(request):
    huespedes = Huesped.objects.all().order_by('-id')
    
    # 1. Búsqueda por nombre o documento
    busqueda = request.GET.get('q', '').strip()
    if busqueda:
        huespedes = huespedes.filter(
            Q(nombres__icontains=busqueda) |
            Q(apellidos__icontains=busqueda) |
            Q(numero_documento__icontains=busqueda) |
            Q(correo__icontains=busqueda)
        )

    # 2. Filtro por estado (si se desea implementar estado en Huésped o asociarlo a reservas)
    estado = request.GET.get('estado', '').strip()
    # Nota: Si manejas estado en reservas o en otra lógica, puedes aplicarlo aquí. 
    # Por ahora dejamos preparado el filtro por si usas un campo de estado o similar.

    # 3. Exportar a CSV
    if request.GET.get('exportar') == 'csv':
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="huespedes_brisas.csv"'
        writer = csv.writer(response)
        writer.writerow(['ID', 'Nombres', 'Apellidos', 'Tipo Documento', 'Documento', 'Teléfono', 'Correo', 'Nacionalidad'])
        
        for h in huespedes:
            writer.writerow([h.id, h.nombres, h.apellidos, h.tipo_documento, h.numero_documento, h.telefono, h.correo, h.nacionalidad])
        
        return response

    return render(request, 'hotel_app/huespedes.html', {
        'huespedes': huespedes,
        'busqueda_actual': busqueda
    })

@requiere_rol(es_personal)
def crear_huesped(request):
    form = HuespedForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'El huésped se guardó correctamente.')
        return redirect('lista_huespedes')

    return render(request, 'hotel_app/crear_huesped.html', {'form': form})

@requiere_rol(es_administrador)
def crear_habitacion(request):
    form = HabitacionCreacionForm(
        request.POST or None,
        request.FILES or None,
    )
    if request.method == 'POST' and form.is_valid():
        habitacion = form.save()
        messages.success(
            request,
            f'¡Habitación {habitacion.numero} registrada con éxito!',
        )
        return redirect('lista_habitaciones')

    if request.method == 'POST':
        messages.error(request, 'Revisa los datos de la habitación.')
    return render(request, 'hotel_app/crear_habitacion.html', {'form': form})

@requiere_rol(es_personal)
def realizar_checkin(request, reserva_id):
    reserva = get_object_or_404(
        Reserva.objects.select_related('habitacion', 'huesped'),
        id=reserva_id,
    )
    if reserva.estado != 'Confirmada':
        messages.error(
            request,
            'Solo se puede hacer check-in a reservas confirmadas.',
        )
        return redirect('lista_reservas')

    habitacion = reserva.habitacion
    if habitacion.estado != 'Reservada':
        messages.error(
            request,
            'La habitación no está reservada y no se puede hacer check-in.',
        )
        return redirect('lista_reservas')

    if habitacion.capacidad > 1:
        if request.method not in {'GET', 'POST'}:
            return HttpResponseNotAllowed(['GET', 'POST'])

        cantidad_inicial = min(
            max(reserva.cantidad_huespedes, 1),
            habitacion.capacidad,
        )
        form = CheckinOcupacionForm(
            request.POST or None,
            capacidad=habitacion.capacidad,
            initial={'cantidad_huespedes': cantidad_inicial},
        )
        acompanante_formset_class = formset_factory(
            CheckinAcompananteForm,
            formset=CheckinAcompananteFormSet,
            extra=habitacion.capacidad - 1,
            max_num=habitacion.capacidad - 1,
            validate_max=True,
        )
        acompanantes = acompanante_formset_class(
            request.POST or None,
            prefix='acompanantes',
        )

        if request.method == 'POST':
            ocupacion_valida = form.is_valid()
            acompanantes_validos = acompanantes.is_valid()
            formularios_validos = ocupacion_valida and acompanantes_validos
            formularios_llenados = [
                form_acompanante
                for form_acompanante in acompanantes.forms
                if form_acompanante.has_changed()
            ]
            cantidad_huespedes = None
            if formularios_validos:
                cantidad_declarada = form.cleaned_data['cantidad_huespedes']
                cantidad_registrada = len(formularios_llenados) + 1
                if cantidad_registrada < cantidad_declarada:
                    cantidad_esperada = cantidad_declarada - 1
                    acompanantes.add_non_form_error(
                        f'Para {cantidad_declarada} huéspedes en total, registra {cantidad_esperada} acompañantes además del huésped principal.',
                    )
                    formularios_validos = False
                else:
                    cantidad_huespedes = cantidad_registrada

            documento_principal = (
                reserva.huesped.numero_documento.strip().casefold()
            )
            if formularios_validos and any(
                form_acompanante.cleaned_data['numero_documento'].casefold()
                == documento_principal
                for form_acompanante in formularios_llenados
            ):
                acompanantes.add_non_form_error(
                    'El documento del huésped principal no se debe repetir como acompañante.',
                )
                formularios_validos = False

            if formularios_validos:
                with transaction.atomic():
                    reserva_bloqueada = get_object_or_404(
                        Reserva.objects.select_for_update(),
                        id=reserva_id,
                    )
                    habitacion_bloqueada = get_object_or_404(
                        Habitacion.objects.select_for_update(),
                        pk=reserva_bloqueada.habitacion_id,
                    )
                    if (
                        reserva_bloqueada.estado != 'Confirmada'
                        or habitacion_bloqueada.estado != 'Reservada'
                    ):
                        messages.error(
                            request,
                            'La reserva o habitación cambió de estado. Actualiza la página e inténtalo de nuevo.',
                        )
                        return redirect('lista_reservas')
                    if (
                        cantidad_huespedes
                        > habitacion_bloqueada.capacidad
                    ):
                        messages.error(
                            request,
                            'La capacidad de la habitación cambió. No se pudo completar el check-in.',
                        )
                        return redirect('lista_reservas')

                    for form_acompanante in formularios_llenados:
                        AcompañanteReserva.objects.create(
                            reserva=reserva_bloqueada,
                            **form_acompanante.cleaned_data,
                        )
                    reserva_bloqueada.cantidad_huespedes = (
                        cantidad_huespedes
                    )
                    reserva_bloqueada.estado = 'En curso'
                    reserva_bloqueada.save(
                        update_fields=['cantidad_huespedes', 'estado'],
                    )
                    habitacion_bloqueada.estado = 'Ocupada'
                    habitacion_bloqueada.save(update_fields=['estado'])

                messages.success(
                    request,
                    f'Check-in realizado para {cantidad_huespedes} huéspedes en la habitación {habitacion.numero}.',
                )
                return redirect('lista_reservas')

        return render(
            request,
            'hotel_app/checkin_ocupantes.html',
            {
                'reserva': reserva,
                'habitacion': habitacion,
                'form': form,
                'acompanantes': acompanantes,
            },
        )

    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])

    with transaction.atomic():
        reserva_bloqueada = get_object_or_404(
            Reserva.objects.select_for_update(),
            id=reserva_id,
        )
        habitacion_bloqueada = get_object_or_404(
            Habitacion.objects.select_for_update(),
            pk=reserva_bloqueada.habitacion_id,
        )
        if (
            reserva_bloqueada.estado != 'Confirmada'
            or habitacion_bloqueada.estado != 'Reservada'
        ):
            messages.error(
                request,
                'La reserva o habitación cambió de estado. Actualiza la página e inténtalo de nuevo.',
            )
            return redirect('lista_reservas')

        reserva_bloqueada.estado = 'En curso'
        reserva_bloqueada.save(update_fields=['estado'])
        habitacion_bloqueada.estado = 'Ocupada'
        habitacion_bloqueada.save(update_fields=['estado'])

    messages.success(
        request,
        f'Check-in realizado. La habitación {habitacion_bloqueada.numero} está ocupada.',
    )
    return redirect('lista_reservas')


@requiere_rol(es_personal)
@require_POST
def realizar_checkout(request, reserva_id):
    with transaction.atomic():
        reserva = get_object_or_404(
            Reserva.objects.select_for_update().select_related('habitacion'),
            id=reserva_id,
        )
        if reserva.estado != 'En curso':
            messages.error(
                request,
                'Esta reserva no está en curso actualmente.',
            )
            return redirect('lista_reservas')

        habitacion = reserva.habitacion
        consumos_pendientes = list(
            ConsumoHabitacion.objects.select_for_update().filter(
                reserva=reserva,
                estado_pago='Pendiente',
            )
        )
        total_servicios_pendientes = sum(
            (consumo.total for consumo in consumos_pendientes),
            Decimal('0.00'),
        )
        total_pendiente = (
            reserva.saldo_pendiente + total_servicios_pendientes
        )
        if total_pendiente > 0:
            metodo_pago = request.POST.get('metodo_pago')
            metodos_validos = dict(Pago.METODOS_PAGO)
            if (
                request.POST.get('confirmar_pagos_pendientes') != 'on'
                or metodo_pago not in metodos_validos
            ):
                messages.error(
                    request,
                    'Antes del Check-out debes confirmar el pago de todos los saldos pendientes.',
                )
                return redirect('lista_reservas')

            Pago.objects.create(
                reserva=reserva,
                monto=total_pendiente,
                metodo_pago=metodo_pago,
                observacion='Pago de saldo de hospedaje y servicios al Check-out.',
            )
            reserva.saldo_pendiente = Decimal('0.00')
            reserva.save(update_fields=['saldo_pendiente'])
            for consumo in consumos_pendientes:
                consumo.estado_pago = 'Pagado'
                consumo.confirmado_por = request.user
                consumo.save(update_fields=['estado_pago', 'confirmado_por'])

        reserva.estado = 'Finalizada'
        reserva.save(update_fields=['estado'])
        habitacion.estado = 'En limpieza'
        habitacion.limpieza = 'Sucio'
        habitacion.save(update_fields=['estado', 'limpieza'])

    messages.success(
        request,
        f'Check-out realizado. La habitación {habitacion.numero} pasó a limpieza.',
    )
    
    # <--- AQUÍ ES DONDE DEBES PONER EL REDIRECT A LA FACTURA --->
    return redirect('factura_checkout', reserva_id=reserva.id)

@requiere_rol(es_personal)
def recepcion_hoy_view(request):
    hoy = date.today()
    
    # Huéspedes que llegan hoy (Check-in)
    llegadas_hoy = Reserva.objects.filter(
        fecha_ingreso=hoy,
        estado='Confirmada'
    ).order_by('fecha_ingreso')
    
    # Huéspedes que salen hoy (Check-out) - Deben entregar a las 11:00 AM
    salidas_hoy = Reserva.objects.filter(
        fecha_salida=hoy,
        estado='En curso'
    ).order_by('fecha_salida')
    
    return render(request, 'hotel_app/recepcion_hoy.html', {
        'llegadas_hoy': llegadas_hoy,
        'salidas_hoy': salidas_hoy,
        'hoy': hoy
    })

@login_required
def mis_reservas_cliente(request):
    huesped = Huesped.objects.filter(correo=request.user.email).first()
    reservas = Reserva.objects.filter(huesped=huesped) if huesped else []
    
    # Aquí también usamos _base_manager para forzar que aparezcan todas en el dashboard
    habitaciones = (
        Habitacion._base_manager.exclude(
            estado__in=Habitacion.ESTADOS_NO_RESERVABLES,
        )
        .order_by('numero')
    )

    return render(request, 'hotel_app/portal_cliente_dashboard.html', {
        'reservas': reservas,
        'habitaciones': habitaciones,
        'huesped': huesped
    })

# Tarifario fijo de prendas para Lavandería
TARIFAS_LAVANDERIA = [
    {'id': 'sueter', 'nombre': 'Suéter / Camiseta', 'precio': 2000},
    {'id': 'camisa_larga', 'nombre': 'Camisa manga larga', 'precio': 4000},
    {'id': 'jeans', 'nombre': 'Jeans / Pantalón', 'precio': 5000},
    {'id': 'vestido', 'nombre': 'Vestido / Falda', 'precio': 6000},
    {'id': 'chaqueta', 'nombre': 'Chaqueta / Saco', 'precio': 8000},
    {'id': 'ropa_interior', 'nombre': 'Ropa interior / Medias (par)', 'precio': 1500},
]

@requiere_rol(es_personal)
def solicitar_servicio_habitacion(request, reserva_id):
    reserva = get_object_or_404(
        Reserva.objects.select_related('habitacion', 'huesped'),
        id=reserva_id,
    )
    if not es_personal(request.user):
        return HttpResponseForbidden(
            'Solo el personal puede solicitar servicios para una habitación.',
        )
    servicios = ServicioAdicional.objects.all()
    consumos_existentes = reserva.consumos.all().order_by('-fecha_solicitud')

    if request.method == 'POST':
        tipo_solicitud = request.POST.get('tipo_solicitud')  # 'lavanderia' o 'otro'
        detalle_items = []
        total_calculado = Decimal('0.00')

        if tipo_solicitud == 'lavanderia':
            for prenda in TARIFAS_LAVANDERIA:
                try:
                    cantidad = int(request.POST.get(f"cant_{prenda['id']}", 0) or 0)
                except (TypeError, ValueError):
                    messages.error(request, 'Las cantidades de lavandería deben ser números enteros.')
                    return redirect('solicitar_servicio_habitacion', reserva_id=reserva.id)
                if cantidad < 0:
                    messages.error(request, 'Las cantidades de lavandería no pueden ser negativas.')
                    return redirect('solicitar_servicio_habitacion', reserva_id=reserva.id)
                if cantidad > 0:
                    subtotal = Decimal(cantidad * prenda['precio'])
                    total_calculado += subtotal
                    detalle_items.append(f"{cantidad}x {prenda['nombre']} (${subtotal:,.0f})")

            if total_calculado <= 0:
                messages.error(request, "Debes seleccionar al menos una prenda para el servicio de lavandería.")
                return redirect('solicitar_servicio_habitacion', reserva_id=reserva.id)

            servicio_lav = (
                ServicioAdicional.objects.filter(
                    nombre__iexact='Lavandería',
                ).first()
                or ServicioAdicional.objects.filter(
                    nombre__iexact='Lavanderia',
                ).first()
            )
            if servicio_lav is None:
                servicio_lav = ServicioAdicional.objects.create(
                    nombre='Lavandería',
                    precio=0,
                    descripcion='Servicio de lavandería por prenda',
                )
            descripcion_final = "Lavandería: " + ", ".join(detalle_items)
            ConsumoHabitacion.objects.create(
                reserva=reserva,
                servicio=servicio_lav,
                descripcion_detalle=descripcion_final,
                total=total_calculado,
                estado_pago='Pendiente'
            )
            messages.success(request, f"Servicio de lavandería registrado por ${total_calculado:,.0f}. Pendiente de confirmación de pago.")
            return redirect('solicitar_servicio_habitacion', reserva_id=reserva.id)

        elif tipo_solicitud == 'otro':
            servicio_id = request.POST.get('servicio_id')
            try:
                cantidad = int(request.POST.get('cantidad_otro', 1) or 1)
            except (TypeError, ValueError):
                messages.error(request, 'La cantidad del servicio debe ser un número entero.')
                return redirect('solicitar_servicio_habitacion', reserva_id=reserva.id)
            if cantidad < 1:
                messages.error(request, 'La cantidad del servicio debe ser mayor que cero.')
                return redirect('solicitar_servicio_habitacion', reserva_id=reserva.id)
            try:
                servicio_obj = ServicioAdicional.objects.get(id=int(servicio_id))
            except (ServicioAdicional.DoesNotExist, TypeError, ValueError):
                messages.error(request, 'Selecciona un servicio adicional válido.')
                return redirect('solicitar_servicio_habitacion', reserva_id=reserva.id)
            total_calculado = servicio_obj.precio * cantidad
            ConsumoHabitacion.objects.create(
                reserva=reserva,
                servicio=servicio_obj,
                descripcion_detalle=f"{cantidad}x {servicio_obj.nombre}",
                total=total_calculado,
                estado_pago='Pendiente'
            )
            messages.success(request, f"Servicio '{servicio_obj.nombre}' agregado por ${total_calculado:,.0f}.")
            return redirect('solicitar_servicio_habitacion', reserva_id=reserva.id)

    return render(request, 'hotel_app/solicitar_servicio_habitacion.html', {
        'reserva': reserva,
        'prendas': TARIFAS_LAVANDERIA,
        'servicios': servicios,
        'consumos': consumos_existentes,
    })


@require_POST
@login_required(login_url='login')
def confirmar_pago_consumo(request, consumo_id):
    consumo = get_object_or_404(ConsumoHabitacion, id=consumo_id)
    if not es_personal(request.user):
        return HttpResponseForbidden(
            'Solo el personal puede confirmar pagos de servicios.',
        )
    if consumo.estado_pago == 'Pagado':
        messages.info(request, 'Este consumo ya fue confirmado como pagado.')
        return redirect('solicitar_servicio_habitacion', reserva_id=consumo.reserva.id)
    consumo.estado_pago = 'Pagado'
    consumo.confirmado_por = request.user
    consumo.save(update_fields=['estado_pago', 'confirmado_por'])
    messages.success(request, f"Pago confirmado por ${consumo.total:,.0f} para la Habitación {consumo.reserva.habitacion.numero}.")
    return redirect('solicitar_servicio_habitacion', reserva_id=consumo.reserva.id)

@require_POST
@login_required(login_url='login')
def cancelar_consumo(request, consumo_id):
    consumo = get_object_or_404(ConsumoHabitacion, id=consumo_id)
    if not es_personal(request.user):
        return HttpResponseForbidden(
            'Solo el personal puede cancelar servicios de una habitación.',
        )
    if consumo.estado_pago != 'Pendiente':
        messages.error(
            request,
            'Solo se pueden cancelar servicios que aún estén pendientes de pago.',
        )
        return redirect(
            'solicitar_servicio_habitacion',
            reserva_id=consumo.reserva.id,
        )

    consumo.estado_pago = 'Cancelado'
    consumo.save(update_fields=['estado_pago'])
    messages.success(request, 'El servicio fue cancelado y no se incluirá en el cobro.')
    return redirect(
        'solicitar_servicio_habitacion',
        reserva_id=consumo.reserva.id,
    )


@login_required
def factura_checkout(request, reserva_id):
    reserva = get_object_or_404(Reserva, id=reserva_id)
    consumos = reserva.consumos.exclude(estado_pago='Cancelado')
    
    # Calcular días de hospedaje (mínimo 1 noche)
    dias = (reserva.fecha_salida - reserva.fecha_ingreso).days
    if dias < 1:
        dias = 1
    total_hospedaje = reserva.habitacion.precio * dias
    total_servicios = sum(c.total for c in consumos)
    total_pagado_servicios = sum(c.total for c in consumos if c.estado_pago == 'Pagado')
    total_pendiente_servicios = sum(c.total for c in consumos if c.estado_pago == 'Pendiente')
    gran_total = total_hospedaje + total_servicios

    return render(request, 'hotel_app/factura_checkout.html', {
        'reserva': reserva,
        'dias': dias,
        'total_hospedaje': total_hospedaje,
        'consumos': consumos,
        'total_servicios': total_servicios,
        'total_pagado_servicios': total_pagado_servicios,
        'total_pendiente_servicios': total_pendiente_servicios,
        'gran_total': gran_total,
    })
def recuperar_password_solicitar(request):
    if request.method == 'POST':
        identificador = request.POST.get('identificador', '').strip()
        user = User.objects.filter(
            Q(username__iexact=identificador) | Q(email__iexact=identificador),
            is_active=True,
        ).first()
        
        if user and user.email:
            codigo = f'{secrets.randbelow(1_000_000):06}'
            request.session.pop('reset_user_id', None)
            request.session.pop('reset_codigo', None)
            request.session.pop('reset_attempts', None)
            request.session.pop('reset_expires_at', None)
            request.session.pop('codigo_verificado', None)
            
            asunto = "Código de recuperación de contraseña - Hotel Brisas de La Guajira"
            mensaje = (
                f"Hola {user.username},\n\n"
                f"Has solicitado recuperar tu contraseña en el Hotel Brisas de La Guajira.\n"
                f"Tu código de verificación es: {codigo}\n\n"
                f"Si no solicitaste este cambio, puedes ignorar este mensaje."
            )
            try:
                sent = send_mail(
                    asunto,
                    mensaje,
                    settings.DEFAULT_FROM_EMAIL,
                    [user.email],
                    fail_silently=False,
                )
                if sent != 1:
                    raise SMTPException('No se pudo entregar el código de recuperación.')
                request.session['reset_user_id'] = user.id
                request.session['reset_codigo'] = codigo
                request.session['reset_attempts'] = 0
                request.session['reset_expires_at'] = int(
                    timezone.now().timestamp(),
                ) + 600
                return redirect('recuperar_password_verificar')
            except (OSError, SMTPException):
                logger.exception(
                    'No se pudo enviar el código de recuperación al usuario %s.',
                    user.pk,
                )
                messages.error(
                    request,
                    'No se pudo enviar el correo de recuperación. Inténtalo más tarde.',
                )
        else:
            messages.error(request, f"No se encontró ningún usuario registrado con: '{identificador}'.")
            
    return render(request, 'hotel_app/recuperar_password_solicitar.html')


def recuperar_password_verificar(request):
    if 'reset_user_id' not in request.session:
        return redirect('recuperar_password_solicitar')

    if int(timezone.now().timestamp()) >= request.session.get(
        'reset_expires_at',
        0,
    ):
        request.session.pop('reset_user_id', None)
        request.session.pop('reset_codigo', None)
        request.session.pop('reset_attempts', None)
        request.session.pop('reset_expires_at', None)
        request.session.pop('codigo_verificado', None)
        messages.error(
            request,
            'El código venció. Solicita uno nuevo para continuar.',
        )
        return redirect('recuperar_password_solicitar')
        
    if request.method == 'POST':
        codigo_ingresado = request.POST.get('codigo', '').strip()
        codigo_guardado = request.session.get('reset_codigo')
        
        if codigo_ingresado == codigo_guardado:
            request.session['codigo_verificado'] = True
            messages.success(request, "Código verificado correctamente. Ingresa tu nueva contraseña.")
            return redirect('recuperar_password_cambiar')
        else:
            intentos = request.session.get('reset_attempts', 0) + 1
            request.session['reset_attempts'] = intentos
            if intentos >= 5:
                request.session.pop('reset_user_id', None)
                request.session.pop('reset_codigo', None)
                request.session.pop('reset_attempts', None)
                request.session.pop('reset_expires_at', None)
                request.session.pop('codigo_verificado', None)
                messages.error(
                    request,
                    'Se superó el número de intentos. Solicita un nuevo código.',
                )
                return redirect('recuperar_password_solicitar')
            messages.error(
                request,
                f"El código es incorrecto. Te quedan {5 - intentos} intentos.",
            )
            
    return render(request, 'hotel_app/recuperar_password_verificar.html')


def recuperar_password_cambiar(request):
    if not request.session.get('codigo_verificado') or 'reset_user_id' not in request.session:
        return redirect('recuperar_password_solicitar')

    if int(timezone.now().timestamp()) >= request.session.get(
        'reset_expires_at',
        0,
    ):
        request.session.pop('reset_user_id', None)
        request.session.pop('reset_codigo', None)
        request.session.pop('reset_attempts', None)
        request.session.pop('reset_expires_at', None)
        request.session.pop('codigo_verificado', None)
        messages.error(
            request,
            'El código venció. Solicita uno nuevo para continuar.',
        )
        return redirect('recuperar_password_solicitar')
        
    if request.method == 'POST':
        nueva_password = request.POST.get('nueva_password')
        confirmar_password = request.POST.get('confirmar_password')
        
        if nueva_password != confirmar_password:
            messages.error(request, "Las contraseñas no coinciden.")
            return redirect('recuperar_password_cambiar')
            
        user_id = request.session.get('reset_user_id')
        user = get_object_or_404(User, id=user_id)
        user.set_password(nueva_password)
        user.save()
        
        # Limpiar datos de sesión temporales
        request.session.pop('reset_user_id', None)
        request.session.pop('reset_codigo', None)
        request.session.pop('reset_attempts', None)
        request.session.pop('reset_expires_at', None)
        request.session.pop('codigo_verificado', None)
        
        messages.success(request, "¡Contraseña actualizada con éxito! Ya puedes iniciar sesión.")
        return redirect('login')
        
    return render(request, 'hotel_app/recuperar_password_cambiar.html')