import logging
from smtplib import SMTPException

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponseForbidden
from django.shortcuts import redirect, render
from django.urls import reverse

from .forms import RegistroClienteForm, ReservaClienteForm
from .models import Habitacion, Huesped, Reserva

logger = logging.getLogger(__name__)
REGISTRATION_TOKEN_SALT = 'hotel_app.customer_registration'
REGISTRATION_TOKEN_MAX_AGE = 3 * 24 * 60 * 60


def _send_registration_verification(user, request):
    token = signing.dumps(user.pk, salt=REGISTRATION_TOKEN_SALT)
    verification_url = request.build_absolute_uri(
        reverse('verificar_registro_cliente', kwargs={'token': token}),
    )
    message = (
        f'Hola {user.username},\n\n'
        'Confirma tu correo para activar tu cuenta en Hotel Brisas de La Guajira:\n'
        f'{verification_url}\n\n'
        'El enlace vence en 3 días. Si no creaste esta cuenta, ignora este mensaje.'
    )
    sent = send_mail(
        'Confirma tu correo - Hotel Brisas de La Guajira',
        message,
        settings.DEFAULT_FROM_EMAIL,
        [user.email],
        fail_silently=False,
    )
    if sent != 1:
        raise SMTPException('No se pudo entregar el correo de verificación.')


def registro_cliente_publico(request):
    form = RegistroClienteForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user_model = get_user_model()
        try:
            with transaction.atomic():
                user = user_model.objects.create_user(
                    username=form.cleaned_data['username'],
                    email=form.cleaned_data['email'],
                    password=form.cleaned_data['password'],
                    is_active=False,
                )
                client_group, _ = Group.objects.get_or_create(name='Clientes')
                user.groups.add(client_group)
                Huesped.objects.create(
                    nombres=form.cleaned_data['nombres'],
                    apellidos=form.cleaned_data['apellidos'],
                    tipo_documento='CC',
                    numero_documento=form.cleaned_data['documento'],
                    telefono=form.cleaned_data['telefono'],
                    correo=form.cleaned_data['email'],
                    nacionalidad=form.cleaned_data['nacionalidad'],
                )
                _send_registration_verification(user, request)
        except (OSError, SMTPException):
            logger.exception(
                'No se pudo enviar la verificación para el registro de %s.',
                form.cleaned_data['email'],
            )
            messages.error(
                request,
                'No se pudo enviar el correo de verificación. Intenta registrarte nuevamente más tarde.',
            )
            return render(
                request,
                'hotel_app/registro_cliente.html',
                {'form': form},
            )

        try:
            sent = send_mail(
                'Nuevo registro de cliente - Hotel Brisas de La Guajira',
                (
                    f'Se registró {user.get_full_name() or user.username} '
                    f'({user.email}). La cuenta está pendiente de verificación.'
                ),
                settings.DEFAULT_FROM_EMAIL,
                [settings.HOTEL_NOTIFICATION_EMAIL],
                fail_silently=False,
            )
            if sent != 1:
                raise SMTPException('No se pudo entregar el aviso de registro.')
        except (OSError, SMTPException):
            logger.exception(
                'No se pudo enviar el aviso de registro para el usuario %s.',
                user.pk,
            )

        messages.success(
            request,
            'Te enviamos un enlace de verificación. Confirma tu correo antes de iniciar sesión.',
        )
        return redirect('login')

    return render(request, 'hotel_app/registro_cliente.html', {'form': form})


def verificar_registro_cliente(request, token):
    user_model = get_user_model()
    try:
        user_id = signing.loads(
            token,
            salt=REGISTRATION_TOKEN_SALT,
            max_age=REGISTRATION_TOKEN_MAX_AGE,
        )
    except signing.BadSignature:
        messages.error(
            request,
            'El enlace de verificación no es válido o venció. Solicita uno nuevo.',
        )
        return redirect('reenviar_verificacion_cliente')

    user = user_model.objects.filter(pk=user_id).first()
    if not user:
        messages.error(request, 'No se encontró la cuenta asociada al enlace.')
        return redirect('registro_cliente_publico')

    if user.is_active:
        messages.info(request, 'Tu correo ya estaba verificado. Puedes iniciar sesión.')
    else:
        user.is_active = True
        user.save(update_fields=['is_active'])
        messages.success(
            request,
            'Correo verificado. Ya puedes iniciar sesión.',
        )
    return redirect('login')


def reenviar_verificacion_cliente(request):
    if request.method == 'POST':
        email = request.POST.get('email', '').strip()
        user = get_user_model().objects.filter(
            email__iexact=email,
            is_active=False,
        ).first()
        if user:
            try:
                _send_registration_verification(user, request)
            except (OSError, SMTPException):
                logger.exception(
                    'No se pudo reenviar la verificación para el usuario %s.',
                    user.pk,
                )
                messages.error(
                    request,
                    'No se pudo enviar el correo ahora. Inténtalo más tarde.',
                )
                return redirect('reenviar_verificacion_cliente')

        messages.success(
            request,
            'Si existe una cuenta pendiente con ese correo, recibirás un enlace de verificación.',
        )
        return redirect('login')

    return render(request, 'hotel_app/reenviar_verificacion.html')


@login_required(login_url='login')
def mis_reservas_cliente(request):
    if (
        request.user.is_staff
        or not request.user.groups.filter(name='Clientes').exists()
    ):
        return HttpResponseForbidden(
            'Este portal está disponible únicamente para clientes.',
        )

    huesped = Huesped.objects.filter(
        correo__iexact=request.user.email,
    ).first()
    reservas = (
        Reserva.objects.filter(huesped=huesped)
        .select_related('habitacion')
        .order_by('-fecha_creacion')
        if huesped
        else Reserva.objects.none()
    )
    form = ReservaClienteForm(
        request.POST or None,
        initial={'habitacion': request.GET.get('habitacion')},
    )
    habitaciones = form.fields['habitacion'].queryset

    if request.method == 'POST':
        if not huesped:
            messages.error(
                request,
                'No encontramos tus datos de huésped. Contacta a recepción para completar tu perfil.',
            )
            return redirect('mis_reservas_cliente')

        if form.is_valid():
            with transaction.atomic():
                habitacion = (
                    Habitacion.objects.select_for_update()
                    .filter(pk=form.cleaned_data['habitacion'].pk)
                    .first()
                )
                if not habitacion or not habitacion.esta_disponible_para(
                    form.cleaned_data['fecha_ingreso'],
                    form.cleaned_data['fecha_salida'],
                ):
                    form.add_error(
                        'habitacion',
                        'La habitación seleccionada no está disponible para esas fechas.',
                    )
                else:
                    reserva = Reserva.objects.create(
                        huesped=huesped,
                        habitacion=habitacion,
                        fecha_ingreso=form.cleaned_data['fecha_ingreso'],
                        fecha_salida=form.cleaned_data['fecha_salida'],
                        estado='Confirmada',
                    )
                    habitacion.actualizar_estado_segun_reservas()

            if not form.errors:
                personal = get_user_model().objects.filter(
                    Q(is_superuser=True)
                    | Q(groups__name__in=['Administradores', 'Recepcionistas'])
                ).exclude(email='').values_list('email', flat=True).distinct()
                destinatarios = set(personal)
                destinatarios.add(settings.HOTEL_NOTIFICATION_EMAIL)
                if destinatarios:
                    asunto = f'Nueva reserva confirmada - #{reserva.pk}'
                    mensaje = (
                        'Se ha registrado una nueva reserva en el Hotel '
                        'Brisas de La Guajira.\n\n'
                        f'Reserva: #{reserva.pk}\n'
                        f'Huésped: {huesped.nombres} {huesped.apellidos}\n'
                        f'Habitación: {habitacion.numero} ({habitacion.tipo})\n'
                        f'Ingreso: {reserva.fecha_ingreso}\n'
                        f'Salida: {reserva.fecha_salida}\n'
                    )
                    try:
                        sent = send_mail(
                            asunto,
                            mensaje,
                            settings.DEFAULT_FROM_EMAIL,
                            sorted(destinatarios),
                            fail_silently=False,
                        )
                        if sent != 1:
                            raise SMTPException(
                                'No se pudo entregar el aviso de reserva.',
                            )
                    except (OSError, SMTPException):
                        logger.exception(
                            'No se pudo enviar la notificación de reserva %s.',
                            reserva.pk,
                        )
                        messages.warning(
                            request,
                            'La reserva quedó registrada, pero no se pudo enviar la notificación al personal.',
                        )
                    else:
                        messages.success(
                            request,
                            '¡Reserva realizada con éxito! Se notificó al personal.',
                        )
                else:
                    messages.success(
                        request,
                        '¡Reserva realizada con éxito! No hay correos de personal configurados para notificaciones.',
                    )
                return redirect('mis_reservas_cliente')
        else:
            messages.error(request, 'Revisa los datos de la reserva.')

    return render(request, 'hotel_app/portal_cliente_dashboard.html', {
        'reservas': reservas,
        'form': form,
        'huesped': huesped,
        'habitaciones': habitaciones,
    })
