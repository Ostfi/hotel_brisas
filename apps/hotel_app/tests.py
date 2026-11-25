from io import BytesIO
import json
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from smtplib import SMTPException
from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib.error import HTTPError

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.mail import EmailMessage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.urls import resolve, reverse
from django.utils import timezone
from PIL import Image

from apps.hotel_app.forms import (
    CheckinAcompananteForm,
    HabitacionEdicionForm,
    HuespedForm,
)
from apps.hotel_app.email_backend import BrevoEmailBackend
from apps.hotel_app.models import (
    ConsumoHabitacion,
    Habitacion,
    Huesped,
    Pago,
    Reserva,
    ServicioAdicional,
    TransaccionPago,
)


class BrevoEmailBackendTests(SimpleTestCase):
    @override_settings(BREVO_API_KEY='test-api-key', EMAIL_TIMEOUT=8)
    @patch('apps.hotel_app.email_backend.urlopen')
    def test_sends_plain_text_email_through_brevo_api(self, urlopen_mock):
        urlopen_mock.return_value.__enter__.return_value.status = 201
        backend = BrevoEmailBackend()
        message = EmailMessage(
            'Aviso del hotel',
            'Tu reserva fue confirmada.',
            'Hotel Brisas <reservas@example.com>',
            ['Huésped <guest@example.com>'],
        )

        sent = backend.send_messages([message])

        self.assertEqual(sent, 1)
        request = urlopen_mock.call_args.args[0]
        self.assertEqual(request.full_url, backend.api_url)
        self.assertEqual(request.get_header('Api-key'), 'test-api-key')
        self.assertEqual(
            json.loads(request.data),
            {
                'sender': {
                    'email': 'reservas@example.com',
                    'name': 'Hotel Brisas',
                },
                'to': [
                    {'email': 'guest@example.com', 'name': 'Huésped'},
                ],
                'subject': 'Aviso del hotel',
                'textContent': 'Tu reserva fue confirmada.',
            },
        )
        urlopen_mock.assert_called_once_with(request, timeout=8)

    @override_settings(BREVO_API_KEY='')
    def test_reports_missing_brevo_api_key(self):
        with self.assertRaisesMessage(SMTPException, 'BREVO_API_KEY'):
            BrevoEmailBackend().send_messages([
                EmailMessage('Aviso', 'Texto', 'hotel@example.com', ['guest@example.com']),
            ])

    @override_settings(BREVO_API_KEY=' test-api-key \n', EMAIL_TIMEOUT=8)
    @patch('apps.hotel_app.email_backend.urlopen')
    def test_strips_whitespace_from_brevo_api_key(self, urlopen_mock):
        urlopen_mock.return_value.__enter__.return_value.status = 201
        message = EmailMessage(
            'Aviso',
            'Texto',
            'hotel@example.com',
            ['guest@example.com'],
        )

        sent = BrevoEmailBackend().send_messages([message])

        self.assertEqual(sent, 1)
        request = urlopen_mock.call_args.args[0]
        self.assertEqual(request.get_header('Api-key'), 'test-api-key')

    @override_settings(BREVO_API_KEY='test-api-key', EMAIL_TIMEOUT=8)
    @patch('apps.hotel_app.email_backend.urlopen')
    def test_includes_brevo_error_details_without_logging_api_key(self, urlopen_mock):
        error_body = json.dumps({
            'code': 'unauthorized',
            'message': 'Invalid API key: test-api-key',
        }).encode('utf-8')
        urlopen_mock.side_effect = HTTPError(
            'https://api.brevo.com/v3/smtp/email',
            401,
            'Unauthorized',
            {},
            BytesIO(error_body),
        )
        message = EmailMessage(
            'Aviso',
            'Texto',
            'hotel@example.com',
            ['guest@example.com'],
        )

        with self.assertRaises(SMTPException) as context:
            BrevoEmailBackend().send_messages([message])

        self.assertIn('HTTP 401', str(context.exception))
        self.assertIn('unauthorized', str(context.exception))
        self.assertIn('Invalid API key: [oculta]', str(context.exception))
        self.assertNotIn('test-api-key', str(context.exception))


class HabitacionEdicionFormTests(SimpleTestCase):
    def setUp(self):
        self.habitacion = Habitacion(
            numero='999',
            tipo='Sencilla',
            capacidad=1,
            precio='90000.00',
            piso=9,
        )

    def crear_imagen(self):
        image_data = BytesIO()
        Image.new('RGB', (1, 1), color='white').save(image_data, format='PNG')
        return SimpleUploadedFile(
            'habitacion.png',
            image_data.getvalue(),
            content_type='image/png',
        )

    def test_accepts_uploaded_image(self):
        form = HabitacionEdicionForm(
            {
                'estado': 'Disponible',
                'limpieza': 'Limpio',
                'mantenimiento': 'Ninguno',
                'imagen_url': '',
            },
            {'imagen': self.crear_imagen()},
            instance=self.habitacion,
        )

        self.assertTrue(form.is_valid(), form.errors)

    def test_accepts_valid_image_url(self):
        form = HabitacionEdicionForm(
            {
                'estado': 'Disponible',
                'limpieza': 'Limpio',
                'mantenimiento': 'Ninguno',
                'imagen_url': 'https://example.com/habitacion.jpg',
            },
            instance=self.habitacion,
        )

        self.assertTrue(form.is_valid(), form.errors)

    def test_rejects_invalid_image_url_and_two_image_sources(self):
        invalid_url_form = HabitacionEdicionForm(
            {
                'estado': 'Disponible',
                'limpieza': 'Limpio',
                'mantenimiento': 'Ninguno',
                'imagen_url': 'no-es-una-url',
            },
            instance=self.habitacion,
        )
        self.assertFalse(invalid_url_form.is_valid())

        conflicting_sources_form = HabitacionEdicionForm(
            {
                'estado': 'Disponible',
                'limpieza': 'Limpio',
                'mantenimiento': 'Ninguno',
                'imagen_url': 'https://example.com/habitacion.jpg',
            },
            {'imagen': self.crear_imagen()},
            instance=self.habitacion,
        )
        self.assertFalse(conflicting_sources_form.is_valid())

    def test_checkin_companion_phone_accepts_only_digits(self):
        form = CheckinAcompananteForm(data={
            'tipo_documento': 'CC',
            'numero_documento': '123456789',
            'nombres': 'Luis',
            'apellidos': 'Gómez',
            'telefono': '300ABC',
        })

        self.assertFalse(form.is_valid())
        self.assertIn('telefono', form.errors)
        self.assertEqual(
            form.fields['telefono'].widget.attrs['data-digits-only'],
            'true',
        )


class HabitacionImagenTests(SimpleTestCase):
    def test_production_room_images_use_collected_static_assets(self):
        habitacion = Habitacion(
            numero='101',
            tipo='Sencilla',
            capacidad=1,
            precio='90000.00',
            piso=1,
            imagen='habitaciones/subida-local.jpg',
        )

        with override_settings(DEBUG=False, STATIC_URL='/static/'):
            self.assertEqual(
                habitacion.get_imagen(),
                '/static/hotel_app/images/habitaciones/sencilla.jpg',
            )

    def test_double_rooms_share_the_configured_image(self):
        with TemporaryDirectory() as media_root:
            carpeta_habitaciones = Path(media_root) / 'habitaciones'
            carpeta_habitaciones.mkdir()
            (carpeta_habitaciones / 'doble.jpg').write_bytes(b'image')

            with override_settings(DEBUG=True, MEDIA_ROOT=media_root):
                image_urls = {
                    Habitacion(
                        numero=numero,
                        tipo='Doble',
                        capacidad=2,
                        precio='140000.00',
                        piso=2,
                        imagen='otra-foto.jpg',
                    ).get_imagen()
                    for numero in ('201', '202', '203', '204', '205', '206')
                }

        self.assertEqual(image_urls, {'/media/habitaciones/doble.jpg'})

    def test_room_number_image_is_loaded_from_media_folder(self):
        habitacion = Habitacion(
            numero='404',
            tipo='Familiar',
            capacidad=4,
            precio='220000.00',
            piso=4,
        )

        with TemporaryDirectory() as media_root:
            carpeta_habitaciones = Path(media_root) / 'habitaciones'
            carpeta_habitaciones.mkdir()
            (carpeta_habitaciones / 'habitacion-404.jpg').write_bytes(b'image')

            with override_settings(DEBUG=True, MEDIA_ROOT=media_root):
                self.assertEqual(
                    habitacion.get_imagen(),
                    '/media/habitaciones/habitacion-404.jpg',
                )

    def test_existing_media_images_are_assigned_to_rooms(self):
        image_names = [
            'habitación-doble-catalonia-620x412.jpg',
            'hotel-en-bocas-del-toro-habitaciones-familiares-6.jpg',
            'photo-1551882547-ff40c63fe5fa.avif',
            'photo-1618773928121-c32242e63f39.avif',
            'r-hotel-moniquira-palmeras-de-luz-c1.jpg',
        ]

        with TemporaryDirectory() as media_root:
            carpeta_habitaciones = Path(media_root) / 'habitaciones'
            carpeta_habitaciones.mkdir()
            for image_name in image_names:
                (carpeta_habitaciones / image_name).write_bytes(b'image')

            with override_settings(DEBUG=True, MEDIA_ROOT=media_root):
                image_urls = {
                    Habitacion(
                        numero=str(numero),
                        tipo='Sencilla',
                        capacidad=1,
                        precio='90000.00',
                        piso=1,
                    ).get_imagen()
                    for numero in range(101, 106)
                }

        self.assertEqual(
            image_urls,
            {
                f'/media/habitaciones/{image_name}'
                for image_name in image_names
            },
        )


@override_settings(ALLOWED_HOSTS=['testserver'])
class LoginFlowTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='hotel-admin',
            email='admin@example.com',
            password='SafeTestPassword123!',
        )
        admin_group, _ = Group.objects.get_or_create(name='Administradores')
        self.user.groups.add(admin_group)
        self.habitacion = Habitacion.objects.create(
            numero='101',
            tipo='Sencilla',
            capacidad=1,
            precio='90000.00',
            piso=1,
        )
        self.huesped = Huesped.objects.create(
            tipo_documento='CC',
            numero_documento='123456789',
            nombres='Ana',
            apellidos='Pérez',
            telefono='3001234567',
            correo='ana@example.com',
        )

    def request_as_user(self, url):
        request = RequestFactory().get(url)
        request.user = self.user
        request.resolver_match = resolve(url)
        return request

    def test_service_list_displays_registered_services(self):
        ServicioAdicional.objects.create(
            nombre='Desayuno',
            precio='25000.00',
            descripcion='Desayuno para una persona',
        )

        url = reverse('lista_servicios')
        response = resolve(url).func(self.request_as_user(url))

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('Desayuno', content)
        self.assertIn('$25000.00 COP', content)

    def test_reservations_page_renders_valid_table_and_working_detail_modal(self):
        reserva = Reserva.objects.create(
            huesped=self.huesped,
            habitacion=self.habitacion,
            fecha_ingreso='2026-11-10',
            fecha_salida='2026-11-12',
            estado='Confirmada',
        )
        self.client.force_login(self.user)

        response = self.client.get(reverse('lista_reservas'))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'hotel_app/reservas.html')
        content = response.content.decode()
        self.assertIn('Ana Pérez', content)
        self.assertIn('Gestión de Reservas', content)
        self.assertIn('Reportes y Estadísticas', content)
        self.assertIn(f'data-bs-target="#modalReserva{reserva.pk}"', content)
        self.assertIn(f'id="modalReserva{reserva.pk}"', content)
        self.assertIn(
            f'action="{reverse("realizar_checkin", args=[reserva.pk])}"',
            content,
        )
        self.assertLess(content.index('</table>'), content.index('id="modalReserva'))
        self.assertIn('</tbody>', content)
        self.assertIn('</html>', content)

    def test_receptionist_sees_reservation_menu_without_administrator_links(self):
        receptionist = get_user_model().objects.create_user(
            username='recepcion-reservas',
            password='SafeReceptionPassword123!',
        )
        receptionist_group, _ = Group.objects.get_or_create(
            name='Recepcionistas',
        )
        receptionist.groups.add(receptionist_group)
        self.client.force_login(receptionist)

        response = self.client.get(reverse('lista_reservas'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Gestión de Reservas')
        self.assertContains(response, 'Recepcionista')
        self.assertNotContains(response, 'Reportes y Estadísticas')
        self.assertNotContains(response, 'Configuración')

    def test_checkin_for_large_room_registers_companions_and_lists_occupants(self):
        receptionist = get_user_model().objects.create_user(
            username='recepcion-checkin',
            password='SafeReceptionPassword123!',
        )
        receptionist_group, _ = Group.objects.get_or_create(
            name='Recepcionistas',
        )
        receptionist.groups.add(receptionist_group)
        habitacion = Habitacion.objects.create(
            numero='401',
            tipo='Familiar',
            capacidad=4,
            precio='220000.00',
            piso=4,
            estado='Reservada',
        )
        reserva = Reserva.objects.create(
            huesped=self.huesped,
            habitacion=habitacion,
            fecha_ingreso='2026-11-10',
            fecha_salida='2026-11-12',
            cantidad_huespedes=3,
            estado='Confirmada',
        )
        self.client.force_login(receptionist)
        checkin_url = reverse('realizar_checkin', args=[reserva.pk])

        response = self.client.get(checkin_url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'hotel_app/checkin_ocupantes.html')
        self.assertContains(response, self.huesped.numero_documento)

        datos = {
            'cantidad_huespedes': '3',
            'acompanantes-TOTAL_FORMS': '3',
            'acompanantes-INITIAL_FORMS': '0',
            'acompanantes-MIN_NUM_FORMS': '0',
            'acompanantes-MAX_NUM_FORMS': '3',
            'acompanantes-0-tipo_documento': 'CC',
            'acompanantes-0-numero_documento': '222333444',
            'acompanantes-0-nombres': 'Luis',
            'acompanantes-0-apellidos': 'Gómez',
            'acompanantes-0-telefono': '3001112233',
            'acompanantes-1-tipo_documento': 'PAS',
            'acompanantes-1-numero_documento': '555666777',
            'acompanantes-1-nombres': 'María',
            'acompanantes-1-apellidos': 'López',
            'acompanantes-1-telefono': '',
            'acompanantes-2-tipo_documento': 'CE',
            'acompanantes-2-numero_documento': '888999000',
            'acompanantes-2-nombres': 'Carlos',
            'acompanantes-2-apellidos': 'Díaz',
            'acompanantes-2-telefono': '3002223344',
        }
        response = self.client.post(checkin_url, datos)

        self.assertRedirects(
            response,
            reverse('lista_reservas'),
            fetch_redirect_response=False,
        )
        reserva.refresh_from_db()
        habitacion.refresh_from_db()
        self.assertEqual(reserva.estado, 'En curso')
        self.assertEqual(reserva.cantidad_huespedes, 4)
        self.assertEqual(habitacion.estado, 'Ocupada')
        self.assertEqual(reserva.acompanantes.count(), 3)

        response = self.client.get(reverse('lista_ocupantes_habitacion'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(
            response,
            'hotel_app/ocupantes_habitacion.html',
        )
        self.assertContains(response, 'Habitación 401')
        self.assertContains(response, 'Ana Pérez')
        self.assertContains(response, 'Luis Gómez')
        self.assertContains(response, 'María López')
        self.assertContains(response, 'Carlos Díaz')
        self.assertContains(response, '555666777')
        self.assertContains(response, 'Huéspedes por habitación')

    def test_double_room_checkin_registers_companion_before_checkin(self):
        habitacion = Habitacion.objects.create(
            numero='202',
            tipo='Doble',
            capacidad=2,
            precio='140000.00',
            piso=2,
            estado='Reservada',
        )
        reserva = Reserva.objects.create(
            huesped=self.huesped,
            habitacion=habitacion,
            fecha_ingreso='2026-11-10',
            fecha_salida='2026-11-12',
            cantidad_huespedes=2,
            estado='Confirmada',
        )
        self.client.force_login(self.user)
        checkin_url = reverse('realizar_checkin', args=[reserva.pk])

        response = self.client.get(checkin_url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'hotel_app/checkin_ocupantes.html')
        self.assertContains(response, 'acompanantes-TOTAL_FORMS" value="1"')

        response = self.client.post(checkin_url, {
            'cantidad_huespedes': '2',
            'acompanantes-TOTAL_FORMS': '1',
            'acompanantes-INITIAL_FORMS': '0',
            'acompanantes-MIN_NUM_FORMS': '0',
            'acompanantes-MAX_NUM_FORMS': '1',
            'acompanantes-0-tipo_documento': 'CC',
            'acompanantes-0-numero_documento': '222333444',
            'acompanantes-0-nombres': 'Luis',
            'acompanantes-0-apellidos': 'Gómez',
            'acompanantes-0-telefono': '',
        })

        self.assertRedirects(
            response,
            reverse('lista_reservas'),
            fetch_redirect_response=False,
        )
        reserva.refresh_from_db()
        habitacion.refresh_from_db()
        self.assertEqual(reserva.estado, 'En curso')
        self.assertEqual(reserva.acompanantes.count(), 1)
        self.assertEqual(habitacion.estado, 'Ocupada')

    def test_matrimonial_room_checkin_registers_companion(self):
        habitacion = Habitacion.objects.create(
            numero='203',
            tipo='Matrimonial',
            capacidad=2,
            precio='150000.00',
            piso=2,
            estado='Reservada',
        )
        reserva = Reserva.objects.create(
            huesped=self.huesped,
            habitacion=habitacion,
            fecha_ingreso='2026-11-10',
            fecha_salida='2026-11-12',
            cantidad_huespedes=2,
            estado='Confirmada',
        )
        self.client.force_login(self.user)
        checkin_url = reverse('realizar_checkin', args=[reserva.pk])

        response = self.client.post(checkin_url, {
            'cantidad_huespedes': '2',
            'acompanantes-TOTAL_FORMS': '1',
            'acompanantes-INITIAL_FORMS': '0',
            'acompanantes-MIN_NUM_FORMS': '0',
            'acompanantes-MAX_NUM_FORMS': '1',
            'acompanantes-0-tipo_documento': 'CC',
            'acompanantes-0-numero_documento': '333444555',
            'acompanantes-0-nombres': 'Sofía',
            'acompanantes-0-apellidos': 'Ruiz',
            'acompanantes-0-telefono': '',
        })

        self.assertRedirects(
            response,
            reverse('lista_reservas'),
            fetch_redirect_response=False,
        )
        reserva.refresh_from_db()
        self.assertEqual(reserva.estado, 'En curso')
        self.assertEqual(reserva.acompanantes.count(), 1)

    def test_large_room_checkin_requires_exact_number_of_companions(self):
        habitacion = Habitacion.objects.create(
            numero='402',
            tipo='Familiar',
            capacidad=4,
            precio='220000.00',
            piso=4,
            estado='Reservada',
        )
        reserva = Reserva.objects.create(
            huesped=self.huesped,
            habitacion=habitacion,
            fecha_ingreso='2026-11-10',
            fecha_salida='2026-11-12',
            cantidad_huespedes=3,
            estado='Confirmada',
        )
        self.client.force_login(self.user)
        response = self.client.post(
            reverse('realizar_checkin', args=[reserva.pk]),
            {
                'cantidad_huespedes': '3',
                'acompanantes-TOTAL_FORMS': '3',
                'acompanantes-INITIAL_FORMS': '0',
                'acompanantes-MIN_NUM_FORMS': '0',
                'acompanantes-MAX_NUM_FORMS': '3',
                'acompanantes-0-tipo_documento': 'CC',
                'acompanantes-0-numero_documento': '222333444',
                'acompanantes-0-nombres': 'Luis',
                'acompanantes-0-apellidos': 'Gómez',
                'acompanantes-0-telefono': '',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'hotel_app/checkin_ocupantes.html')
        self.assertTrue(response.context['acompanantes'].non_form_errors())
        reserva.refresh_from_db()
        habitacion.refresh_from_db()
        self.assertEqual(reserva.estado, 'Confirmada')
        self.assertEqual(habitacion.estado, 'Reservada')
        self.assertFalse(reserva.acompanantes.exists())

        response = self.client.post(
            reverse('realizar_checkin', args=[reserva.pk]),
            {
                'cantidad_huespedes': '2',
                'acompanantes-TOTAL_FORMS': '3',
                'acompanantes-INITIAL_FORMS': '0',
                'acompanantes-MIN_NUM_FORMS': '0',
                'acompanantes-MAX_NUM_FORMS': '3',
                'acompanantes-0-tipo_documento': 'CC',
                'acompanantes-0-numero_documento': self.huesped.numero_documento,
                'acompanantes-0-nombres': 'Ana',
                'acompanantes-0-apellidos': 'Pérez',
                'acompanantes-0-telefono': '',
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(
            'no se debe repetir como acompañante',
            response.context['acompanantes'].non_form_errors()[0],
        )
        reserva.refresh_from_db()
        self.assertEqual(reserva.estado, 'Confirmada')
        self.assertFalse(reserva.acompanantes.exists())

    def test_checkin_and_checkout_update_reservation_and_room(self):
        self.client.force_login(self.user)
        reserva = Reserva.objects.create(
            huesped=self.huesped,
            habitacion=self.habitacion,
            fecha_ingreso='2026-11-10',
            fecha_salida='2026-11-12',
            estado='Confirmada',
        )
        self.habitacion.estado = 'Reservada'
        self.habitacion.save(update_fields=['estado'])

        checkin_url = reverse('realizar_checkin', args=[reserva.pk])
        self.assertEqual(self.client.get(checkin_url).status_code, 405)
        response = self.client.post(checkin_url)
        self.assertRedirects(
            response,
            reverse('lista_reservas'),
            fetch_redirect_response=False,
        )
        reserva.refresh_from_db()
        self.habitacion.refresh_from_db()
        self.assertEqual(reserva.estado, 'En curso')
        self.assertEqual(self.habitacion.estado, 'Ocupada')

        checkout_url = reverse('realizar_checkout', args=[reserva.pk])
        self.assertEqual(self.client.get(checkout_url).status_code, 405)
        response = self.client.post(checkout_url)
        self.assertRedirects(
            response,
            reverse('factura_checkout', args=[reserva.pk]),
            fetch_redirect_response=False,
        )
        reserva.refresh_from_db()
        self.habitacion.refresh_from_db()
        self.assertEqual(reserva.estado, 'Finalizada')
        self.assertEqual(self.habitacion.estado, 'En limpieza')
        self.assertEqual(self.habitacion.limpieza, 'Sucio')

        response = self.client.post(reverse(
            'accion_habitacion',
            args=[self.habitacion.pk, 'limpiar'],
        ))
        self.assertRedirects(
            response,
            reverse('lista_habitaciones'),
            fetch_redirect_response=False,
        )
        self.habitacion.refresh_from_db()
        self.assertEqual(self.habitacion.estado, 'Disponible')
        self.assertEqual(self.habitacion.limpieza, 'Limpio')

    def test_checkout_requires_and_records_all_pending_payments(self):
        self.client.force_login(self.user)
        reserva = Reserva.objects.create(
            huesped=self.huesped,
            habitacion=self.habitacion,
            fecha_ingreso='2026-11-10',
            fecha_salida='2026-11-12',
            estado='En curso',
            saldo_pendiente=Decimal('90000.00'),
        )
        self.habitacion.estado = 'Ocupada'
        self.habitacion.save(update_fields=['estado'])
        servicio = ServicioAdicional.objects.create(
            nombre='Lavandería',
            precio='10000.00',
        )
        consumo = ConsumoHabitacion.objects.create(
            reserva=reserva,
            servicio=servicio,
            descripcion_detalle='Lavandería',
            total=Decimal('15000.00'),
        )
        checkout_url = reverse('realizar_checkout', args=[reserva.pk])

        response = self.client.get(reverse('lista_reservas'))

        self.assertContains(response, 'Pagos pendientes antes del Check-out')
        self.assertContains(response, 'Saldo de hospedaje:')
        self.assertContains(response, 'Servicios pendientes:')
        self.assertContains(response, 'Confirmo que el huésped pagó')

        response = self.client.post(checkout_url)

        self.assertRedirects(
            response,
            reverse('lista_reservas'),
            fetch_redirect_response=False,
        )
        reserva.refresh_from_db()
        self.habitacion.refresh_from_db()
        self.assertEqual(reserva.estado, 'En curso')
        self.assertEqual(self.habitacion.estado, 'Ocupada')
        self.assertFalse(Pago.objects.filter(reserva=reserva).exists())
        self.assertEqual(consumo.estado_pago, 'Pendiente')

        response = self.client.post(checkout_url, {
            'confirmar_pagos_pendientes': 'on',
            'metodo_pago': 'Efectivo',
        })

        self.assertRedirects(
            response,
            reverse('factura_checkout', args=[reserva.pk]),
            fetch_redirect_response=False,
        )
        reserva.refresh_from_db()
        self.habitacion.refresh_from_db()
        consumo.refresh_from_db()
        pago = Pago.objects.get(reserva=reserva)
        self.assertEqual(reserva.estado, 'Finalizada')
        self.assertEqual(reserva.saldo_pendiente, Decimal('0.00'))
        self.assertEqual(self.habitacion.estado, 'En limpieza')
        self.assertEqual(consumo.estado_pago, 'Pagado')
        self.assertEqual(consumo.confirmado_por, self.user)
        self.assertEqual(pago.monto, Decimal('105000.00'))
        self.assertEqual(pago.metodo_pago, 'Efectivo')

    def test_pending_consumption_can_be_cancelled_and_is_excluded_from_invoice(self):
        self.client.force_login(self.user)
        reserva = Reserva.objects.create(
            huesped=self.huesped,
            habitacion=self.habitacion,
            fecha_ingreso='2026-11-10',
            fecha_salida='2026-11-12',
            estado='En curso',
        )
        consumo = ConsumoHabitacion.objects.create(
            reserva=reserva,
            descripcion_detalle='Servicio de prueba',
            total=Decimal('25000.00'),
        )

        response = self.client.post(
            reverse('cancelar_consumo', args=[consumo.pk]),
        )

        self.assertRedirects(
            response,
            reverse('solicitar_servicio_habitacion', args=[reserva.pk]),
            fetch_redirect_response=False,
        )
        consumo.refresh_from_db()
        self.assertEqual(consumo.estado_pago, 'Cancelado')
        response = self.client.get(
            reverse('factura_checkout', args=[reserva.pk]),
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'Servicio de prueba')
        self.assertEqual(response.context['total_servicios'], Decimal('0.00'))

    def test_create_service_page_loads(self):
        url = reverse('crear_servicio')
        response = resolve(url).func(self.request_as_user(url))

        self.assertEqual(response.status_code, 200)
        self.assertIn('Registrar Servicio Adicional', response.content.decode())

    def test_service_creation_rejects_invalid_price(self):
        self.client.force_login(self.user)

        with patch(
            'apps.hotel_app.views.render',
            return_value=HttpResponse(),
        ) as render_mock:
            response = self.client.post(reverse('crear_servicio'), {
                'nombre': 'Tour de prueba',
                'precio': '-10',
                'descripcion': 'Servicio de prueba',
            })

        self.assertEqual(response.status_code, 200)
        self.assertFalse(
            ServicioAdicional.objects.filter(nombre='Tour de prueba').exists(),
        )
        form = render_mock.call_args.args[2]['form']
        self.assertIn('precio', form.errors)

    def test_payment_creation_rejects_invalid_amount(self):
        reserva = Reserva.objects.create(
            huesped=self.huesped,
            habitacion=self.habitacion,
            fecha_ingreso='2026-10-22',
            fecha_salida='2026-10-24',
        )
        self.client.force_login(self.user)

        with patch(
            'apps.hotel_app.views.render',
            return_value=HttpResponse(),
        ) as render_mock:
            response = self.client.post(reverse('crear_pago'), {
                'reserva': reserva.pk,
                'monto': '-5',
                'metodo_pago': 'Efectivo',
                'observacion': '',
            })

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Pago.objects.exists())
        form = render_mock.call_args.args[2]['form']
        self.assertIn('monto', form.errors)

    def test_room_control_displays_existing_room(self):
        url = reverse('lista_habitaciones')
        response = resolve(url).func(self.request_as_user(url))

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('Control de Habitaciones', content)
        self.assertIn(self.habitacion.numero, content)

    def test_room_creation_saves_valid_data_and_rejects_duplicate_number(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse('crear_habitacion'), {
            'numero': '107',
            'tipo': 'Familiar',
            'capacidad': '4',
            'precio': '220000.00',
            'piso': '4',
            'descripcion': 'Habitación familiar',
        })

        self.assertRedirects(
            response,
            reverse('lista_habitaciones'),
            fetch_redirect_response=False,
        )
        habitacion = Habitacion.objects.get(numero='107')
        self.assertEqual(habitacion.capacidad, 4)
        self.assertEqual(habitacion.precio, Decimal('220000.00'))
        self.assertEqual(habitacion.estado, 'Disponible')

        response = self.client.post(reverse('crear_habitacion'), {
            'numero': '101',
            'tipo': 'Sencilla',
            'capacidad': '1',
            'precio': '90000.00',
            'piso': '1',
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn('numero', response.context['form'].errors)
        self.assertEqual(Habitacion.objects.count(), 2)

    def test_login_page_loads_and_username_login_reaches_rooms(self):
        with patch('apps.hotel_app.views.render', return_value=HttpResponse()):
            response = self.client.get(reverse('login'))
        self.assertEqual(response.status_code, 200)

        response = self.client.post(reverse('login'), {
            'username': 'hotel-admin',
            'password': 'SafeTestPassword123!',
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('lista_habitaciones'))
        self.assertEqual(int(self.client.session['_auth_user_id']), self.user.pk)

    def test_login_accepts_email_and_wrong_password_shows_error(self):
        response = self.client.post(reverse('login'), {
            'username': 'ADMIN@example.com',
            'password': 'SafeTestPassword123!',
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('lista_habitaciones'))

        self.client.post(reverse('logout'))
        with patch('apps.hotel_app.views.render', return_value=HttpResponse()) as render_mock:
            response = self.client.post(reverse('login'), {
                'username': 'hotel-admin',
                'password': 'incorrecta',
            })
        self.assertEqual(response.status_code, 200)
        self.assertTrue(render_mock.call_args.args[2]['form'].errors)

    def test_receptionist_login_reaches_reservations(self):
        receptionist = get_user_model().objects.create_user(
            username='recepcionista',
            password='SafeTestPassword123!',
        )
        receptionist_group, _ = Group.objects.get_or_create(
            name='Recepcionistas',
        )
        receptionist.groups.add(receptionist_group)

        response = self.client.post(reverse('login'), {
            'username': 'recepcionista',
            'password': 'SafeTestPassword123!',
        })

        self.assertRedirects(
            response,
            reverse('lista_reservas'),
            fetch_redirect_response=False,
        )

    def test_client_login_reaches_customer_portal(self):
        client_user = get_user_model().objects.create_user(
            username='cliente',
            password='SafeTestPassword123!',
        )
        client_group, _ = Group.objects.get_or_create(name='Clientes')
        client_user.groups.add(client_group)

        response = self.client.post(reverse('login'), {
            'username': 'cliente',
            'password': 'SafeTestPassword123!',
        })

        self.assertRedirects(
            response,
            reverse('mis_reservas_cliente'),
            fetch_redirect_response=False,
        )
        with patch(
            'apps.hotel_app.customer_views.render',
            return_value=HttpResponse(),
        ) as render_mock:
            portal_response = self.client.get(reverse('mis_reservas_cliente'))
        self.assertEqual(portal_response.status_code, 200)
        self.assertEqual(
            render_mock.call_args.args[1],
            'hotel_app/portal_cliente_dashboard.html',
        )
        form = render_mock.call_args.args[2]['form']
        habitaciones = list(form.fields['habitacion'].queryset)
        self.assertEqual(habitaciones, [
            self.habitacion,
        ])
        self.assertEqual(
            list(render_mock.call_args.args[2]['habitaciones']),
            habitaciones,
        )

    def test_customer_registration_creates_account_profile_and_role(self):
        with (
            patch(
                'apps.hotel_app.customer_views.send_mail',
                return_value=1,
            ) as send_mail_mock,
            override_settings(
                HOTEL_NOTIFICATION_EMAIL='ostwaldjoel09@gmail.com',
            ),
        ):
            response = self.client.post(reverse('registro_cliente_publico'), {
                'username': 'nuevo-cliente',
                'email': 'nuevo@example.com',
                'password': 'UniqueCustomerPassword!938',
                'confirm_password': 'UniqueCustomerPassword!938',
                'nombres': 'Laura',
                'apellidos': 'Gómez',
                'telefono': '3101234567',
                'documento': '987654321',
                'nacionalidad': 'Colombiana',
            })

        self.assertRedirects(
            response,
            reverse('login'),
            fetch_redirect_response=False,
        )
        customer = get_user_model().objects.get(username='nuevo-cliente')
        self.assertTrue(customer.check_password('UniqueCustomerPassword!938'))
        self.assertFalse(customer.is_active)
        self.assertTrue(customer.groups.filter(name='Clientes').exists())
        self.assertTrue(
            Huesped.objects.filter(
                correo='nuevo@example.com',
                numero_documento='987654321',
            ).exists(),
        )
        self.assertEqual(send_mail_mock.call_count, 2)
        verification_message = send_mail_mock.call_args_list[0].args[1]
        verification_url = verification_message.splitlines()[3]
        token = verification_url.rstrip('/').split('/')[-1]
        self.assertEqual(
            send_mail_mock.call_args_list[0].args[3],
            ['nuevo@example.com'],
        )
        self.assertEqual(
            send_mail_mock.call_args_list[1].args[3],
            ['ostwaldjoel09@gmail.com'],
        )

        response = self.client.get(
            reverse('verificar_registro_cliente', kwargs={'token': token}),
        )
        self.assertRedirects(
            response,
            reverse('login'),
            fetch_redirect_response=False,
        )
        customer.refresh_from_db()
        self.assertTrue(customer.is_active)

    def test_password_reset_email_is_sent_only_to_the_customer(self):
        with patch(
            'apps.hotel_app.views.send_mail',
            return_value=1,
        ) as send_mail_mock:
            response = self.client.post(
                reverse('recuperar_password_solicitar'),
                {'identificador': self.user.email},
            )

        self.assertRedirects(
            response,
            reverse('recuperar_password_verificar'),
            fetch_redirect_response=False,
        )
        self.assertEqual(
            send_mail_mock.call_args.args[3],
            [self.user.email],
        )
        self.assertIn(
            self.client.session['reset_codigo'],
            send_mail_mock.call_args.args[1],
        )

    def test_password_reset_code_expires(self):
        with patch(
            'apps.hotel_app.views.send_mail',
            return_value=1,
        ):
            self.client.post(
                reverse('recuperar_password_solicitar'),
                {'identificador': self.user.email},
            )

        session = self.client.session
        session['reset_expires_at'] = int(timezone.now().timestamp()) - 1
        session.save()
        response = self.client.get(reverse('recuperar_password_verificar'))

        self.assertRedirects(
            response,
            reverse('recuperar_password_solicitar'),
            fetch_redirect_response=False,
        )
        self.assertNotIn('reset_user_id', self.client.session)

    def test_customer_registration_rejects_duplicate_document(self):
        with patch(
            'apps.hotel_app.customer_views.render',
            return_value=HttpResponse(),
        ) as render_mock:
            response = self.client.post(reverse('registro_cliente_publico'), {
                'username': 'otro-cliente',
                'email': 'otro@example.com',
                'password': 'UniqueCustomerPassword!938',
                'nombres': 'Laura',
                'apellidos': 'Gómez',
                'telefono': '3101234567',
                'documento': self.huesped.numero_documento,
            })

        self.assertEqual(response.status_code, 200)
        self.assertFalse(
            get_user_model().objects.filter(username='otro-cliente').exists(),
        )
        self.assertIn(
            'documento',
            render_mock.call_args.args[2]['form'].errors,
        )

    def test_customer_can_reserve_available_room_and_cannot_use_past_dates(self):
        customer = get_user_model().objects.create_user(
            username='cliente-reserva',
            email='ana@example.com',
            password='SafeCustomerPassword123!',
        )
        client_group, _ = Group.objects.get_or_create(name='Clientes')
        customer.groups.add(client_group)
        self.client.force_login(customer)
        ingreso = timezone.localdate() + timedelta(days=1)
        salida = ingreso + timedelta(days=2)

        with patch(
            'apps.hotel_app.customer_views.render',
            return_value=HttpResponse(),
        ) as render_mock:
            self.client.get(
                reverse('mis_reservas_cliente'),
                {'habitacion': self.habitacion.pk},
            )
        self.assertEqual(
            render_mock.call_args.args[2]['form']['habitacion'].value(),
            str(self.habitacion.pk),
        )

        with patch(
            'apps.hotel_app.customer_views.send_mail',
            return_value=1,
        ) as send_mail_mock:
            response = self.client.post(
                reverse('mis_reservas_cliente'),
                {
                    'habitacion': self.habitacion.pk,
                    'fecha_ingreso': ingreso.isoformat(),
                    'fecha_salida': salida.isoformat(),
                },
            )

        self.assertRedirects(
            response,
            reverse('mis_reservas_cliente'),
            fetch_redirect_response=False,
        )
        reserva = Reserva.objects.get()
        self.assertEqual(reserva.huesped, self.huesped)
        self.assertEqual(reserva.habitacion, self.habitacion)
        self.habitacion.refresh_from_db()
        self.assertEqual(self.habitacion.estado, 'Reservada')
        send_mail_mock.assert_called_once()
        self.assertIn(
            'ostwaldjoel09@gmail.com',
            send_mail_mock.call_args.args[3],
        )

        disponible = Habitacion.objects.create(
            numero='102',
            tipo='Doble',
            capacidad=2,
            precio='120000.00',
            piso=1,
        )
        past_date = timezone.localdate() - timedelta(days=1)
        with patch(
            'apps.hotel_app.customer_views.render',
            return_value=HttpResponse(),
        ) as render_mock:
            response = self.client.post(
                reverse('mis_reservas_cliente'),
                {
                    'habitacion': disponible.pk,
                    'fecha_ingreso': past_date.isoformat(),
                    'fecha_salida': ingreso.isoformat(),
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Reserva.objects.count(), 1)
        self.assertEqual(
            render_mock.call_args.args[2]['form'].errors['fecha_ingreso'],
            ['La fecha de ingreso no puede estar en el pasado.'],
        )

    def test_administrator_can_open_configuration_and_create_receptionist(self):
        self.client.force_login(self.user)

        with patch('apps.hotel_app.views.render', return_value=HttpResponse()):
            response = self.client.get(reverse('vista_configuracion'))
        self.assertEqual(response.status_code, 200)

        response = self.client.post(reverse('vista_configuracion'), {
            'nuevo_usuario': 'recepcion-prueba',
            'password': 'SafeReceptionPassword123!',
            'rol': 'recepcion',
        })
        self.assertRedirects(
            response,
            reverse('vista_configuracion'),
            fetch_redirect_response=False,
        )

        receptionist = get_user_model().objects.get(
            username='recepcion-prueba',
        )
        self.assertTrue(receptionist.is_staff)
        self.assertTrue(
            receptionist.groups.filter(name='Recepcionistas').exists(),
        )
        self.assertTrue(
            receptionist.check_password('SafeReceptionPassword123!'),
        )

    def test_configuration_rejects_invalid_roles_and_duplicate_usernames(self):
        self.client.force_login(self.user)
        post_data = {
            'nuevo_usuario': 'usuario-prueba',
            'password': 'SafeReceptionPassword123!',
            'rol': 'rol-invalido',
        }

        with patch('apps.hotel_app.views.render', return_value=HttpResponse()):
            response = self.client.post(
                reverse('vista_configuracion'),
                post_data,
            )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(
            get_user_model().objects.filter(
                username='usuario-prueba',
            ).exists(),
        )

        post_data['rol'] = 'recepcion'
        self.client.post(reverse('vista_configuracion'), post_data)
        with patch('apps.hotel_app.views.render', return_value=HttpResponse()):
            response = self.client.post(
                reverse('vista_configuracion'),
                post_data,
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            get_user_model().objects.filter(username='usuario-prueba').count(),
            1,
        )

    def test_client_cannot_access_staff_or_administrator_pages(self):
        client_user = get_user_model().objects.create_user(
            username='cliente-sin-permisos',
            password='SafeTestPassword123!',
        )
        client_group, _ = Group.objects.get_or_create(name='Clientes')
        client_user.groups.add(client_group)
        self.client.force_login(client_user)

        for page_name in ('lista_habitaciones', 'vista_configuracion', 'lista_pagos'):
            with self.subTest(page=page_name):
                response = self.client.get(reverse(page_name))
                self.assertEqual(response.status_code, 403)

    def test_receptionist_cannot_access_administrator_pages(self):
        receptionist = get_user_model().objects.create_user(
            username='recepcion-sin-admin',
            password='SafeTestPassword123!',
            is_staff=True,
        )
        receptionist_group, _ = Group.objects.get_or_create(
            name='Recepcionistas',
        )
        receptionist.groups.add(receptionist_group)
        self.client.force_login(receptionist)

        for page_name in ('vista_configuracion', 'vista_reportes'):
            with self.subTest(page=page_name):
                response = self.client.get(reverse(page_name))
                self.assertEqual(response.status_code, 403)

    def test_room_page_requires_login_and_logout_uses_post(self):
        response = self.client.get(reverse('lista_habitaciones'))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, '/login/?next=/habitaciones/')

        self.client.force_login(self.user)
        with patch('apps.hotel_app.views.render', return_value=HttpResponse()):
            response = self.client.get(reverse('lista_habitaciones'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            reverse('accion_habitacion', args=[self.habitacion.pk, 'limpiar']),
            f'/habitaciones/{self.habitacion.pk}/accion/limpiar/',
        )

        response = self.client.post(reverse('logout'))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('login'))

    def test_crear_reserva_guarda_reserva_y_actualiza_habitacion(self):
        self.client.force_login(self.user)

        response = self.client.post(reverse('crear_reserva'), {
            'huesped': self.huesped.pk,
            'habitacion': self.habitacion.pk,
            'fecha_ingreso': '2026-10-22',
            'fecha_salida': '2026-10-24',
        })

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('lista_reservas'))
        reserva = Reserva.objects.get()
        self.assertEqual(reserva.huesped, self.huesped)
        self.assertEqual(reserva.habitacion, self.habitacion)
        self.assertEqual(reserva.estado, 'Confirmada')
        self.habitacion.refresh_from_db()
        self.assertEqual(self.habitacion.estado, 'Reservada')

    def test_crear_reserva_muestra_error_si_fechas_no_son_validas(self):
        self.client.force_login(self.user)

        with patch('apps.hotel_app.views.render', return_value=HttpResponse()) as render_mock:
            response = self.client.post(reverse('crear_reserva'), {
                'huesped': self.huesped.pk,
                'habitacion': self.habitacion.pk,
                'fecha_ingreso': '2026-10-24',
                'fecha_salida': '2026-10-22',
            })

        self.assertEqual(response.status_code, 200)
        form = render_mock.call_args.args[2]['form']
        self.assertIn(
            'La fecha de salida debe ser posterior a la fecha de ingreso.',
            form.errors['fecha_salida'],
        )
        self.assertFalse(Reserva.objects.exists())
        self.habitacion.refresh_from_db()
        self.assertEqual(self.habitacion.estado, 'Disponible')

    def test_formulario_huesped_rechaza_caracteres_no_permitidos(self):
        datos = {
            'tipo_documento': 'CC',
            'numero_documento': '987654321',
            'nombres': 'Ana María',
            'apellidos': 'Pérez Gómez',
            'telefono': '3101234567',
            'correo': 'otra@example.com',
            'nacionalidad': 'Estados Unidos',
        }
        datos.update({
            'numero_documento': '987ABC',
            'nombres': 'Ana2',
            'apellidos': 'Pérez!',
            'telefono': '310ABC',
            'nacionalidad': 'Colombia1',
        })

        form = HuespedForm(data=datos)

        self.assertFalse(form.is_valid())
        for field in (
            'numero_documento',
            'nombres',
            'apellidos',
            'telefono',
            'nacionalidad',
        ):
            self.assertIn(field, form.errors)

    def test_crear_huesped_no_guarda_datos_invalidos(self):
        self.client.force_login(self.user)

        with patch('apps.hotel_app.views.render', return_value=HttpResponse()) as render_mock:
            response = self.client.post(reverse('crear_huesped'), {
                'tipo_documento': 'CC',
                'numero_documento': '987ABC',
                'nombres': 'Ana2',
                'apellidos': 'Pérez',
                'telefono': '3101234567',
                'correo': 'otra@example.com',
                'nacionalidad': 'Colombiana',
            })

        self.assertEqual(response.status_code, 200)
        form = render_mock.call_args.args[2]['form']
        self.assertIn('numero_documento', form.errors)
        self.assertIn('nombres', form.errors)
        self.assertEqual(Huesped.objects.count(), 1)


@override_settings(ALLOWED_HOSTS=['testserver'])
class CustomerOnlineBookingTests(TestCase):
    def setUp(self):
        self.customer = get_user_model().objects.create_user(
            username='cliente-online',
            email='ana@example.com',
            password='SafeCustomerPassword123!',
        )
        client_group, _ = Group.objects.get_or_create(name='Clientes')
        self.customer.groups.add(client_group)
        self.habitacion = Habitacion.objects.create(
            numero='201',
            tipo='Doble',
            capacidad=2,
            precio='120000.00',
            piso=2,
        )
        self.huesped = Huesped.objects.create(
            tipo_documento='CC',
            numero_documento='1234567890',
            nombres='Ana',
            apellidos='Pérez',
            telefono='3001234567',
            correo=self.customer.email,
        )
        self.client.force_login(self.customer)

    def test_portal_lists_occupied_room_for_later_date_reservations(self):
        habitacion = Habitacion.objects.create(
            numero='404',
            tipo='Familiar',
            capacidad=4,
            precio='220000.00',
            piso=4,
            estado='Ocupada',
        )
        hoy = timezone.localdate()
        Reserva.objects.create(
            huesped=self.huesped,
            habitacion=habitacion,
            fecha_ingreso=hoy - timedelta(days=1),
            fecha_salida=hoy + timedelta(days=3),
            estado='En curso',
        )

        response = self.client.get(reverse('mis_reservas_cliente'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Habitación 404')
        self.assertContains(response, 'fechas elegidas')

    def test_occupied_room_rejects_overlapping_future_dates(self):
        hoy = timezone.localdate()
        inicio_reserva_actual = hoy + timedelta(days=2)
        Reserva.objects.create(
            huesped=self.huesped,
            habitacion=self.habitacion,
            fecha_ingreso=inicio_reserva_actual,
            fecha_salida=inicio_reserva_actual + timedelta(days=3),
            estado='Confirmada',
        )
        self.habitacion.estado = 'Ocupada'
        self.habitacion.save(update_fields=['estado'])

        response = self.client.post(
            reverse(
                'iniciar_reserva_web',
                kwargs={'habitacion_id': self.habitacion.pk},
            ),
            {
                'fecha_ingreso': inicio_reserva_actual.isoformat(),
                'fecha_salida': (inicio_reserva_actual + timedelta(days=1)).isoformat(),
                'cantidad_huespedes': 2,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['form'].non_field_errors())
        self.assertNotIn('reserva_temporal', self.client.session)

    def test_future_booking_for_occupied_room_can_be_checked_in_after_cleaning(self):
        hoy = timezone.localdate()
        fecha_salida_actual = hoy + timedelta(days=2)
        reserva_actual = Reserva.objects.create(
            huesped=self.huesped,
            habitacion=self.habitacion,
            fecha_ingreso=hoy - timedelta(days=1),
            fecha_salida=fecha_salida_actual,
            estado='En curso',
        )
        self.habitacion.estado = 'Ocupada'
        self.habitacion.save(update_fields=['estado'])

        response = self.client.post(
            reverse(
                'iniciar_reserva_web',
                kwargs={'habitacion_id': self.habitacion.pk},
            ),
            {
                'fecha_ingreso': fecha_salida_actual.isoformat(),
                'fecha_salida': (fecha_salida_actual + timedelta(days=2)).isoformat(),
                'cantidad_huespedes': 2,
            },
        )
        self.assertRedirects(
            response,
            reverse('checkout_datos_huesped'),
            fetch_redirect_response=False,
        )
        response = self.client.post(
            reverse('checkout_datos_huesped'),
            {
                'tipo_documento': 'CC',
                'numero_documento': self.huesped.numero_documento,
                'nombres': self.huesped.nombres,
                'apellidos': self.huesped.apellidos,
                'telefono': self.huesped.telefono,
                'correo': self.customer.email,
                'nacionalidad': 'Colombiana',
            },
        )
        self.assertRedirects(
            response,
            reverse('pasarela_pago_simulada'),
            fetch_redirect_response=False,
        )
        with patch(
            'apps.hotel_app.views.send_mail',
            return_value=1,
        ):
            response = self.client.post(
                reverse('pasarela_pago_simulada'),
                {
                    'modalidad_pago': 'Completo',
                    'metodo_pago': 'PSE',
                },
            )

        self.assertEqual(response.status_code, 302)
        reserva_futura = Reserva.objects.exclude(pk=reserva_actual.pk).get()
        self.habitacion.refresh_from_db()
        self.assertEqual(self.habitacion.estado, 'Ocupada')
        self.assertEqual(reserva_futura.fecha_ingreso, fecha_salida_actual)

        reserva_actual.estado = 'Finalizada'
        reserva_actual.save(update_fields=['estado'])
        self.habitacion.estado = 'En limpieza'
        self.habitacion.limpieza = 'Sucio'
        self.habitacion.save(update_fields=['estado', 'limpieza'])
        recepcionista = get_user_model().objects.create_user(
            username='recepcion-limpieza',
            password='SafeReceptionPassword123!',
        )
        grupo_recepcion, _ = Group.objects.get_or_create(
            name='Recepcionistas',
        )
        recepcionista.groups.add(grupo_recepcion)
        self.client.force_login(recepcionista)
        self.client.post(
            reverse(
                'accion_habitacion',
                args=[self.habitacion.pk, 'limpiar'],
            ),
        )
        self.habitacion.refresh_from_db()
        self.assertEqual(self.habitacion.estado, 'Reservada')

        self.client.post(
            reverse('realizar_checkin', args=[reserva_futura.pk]),
            {
                'cantidad_huespedes': '2',
                'acompanantes-TOTAL_FORMS': '1',
                'acompanantes-INITIAL_FORMS': '0',
                'acompanantes-MIN_NUM_FORMS': '0',
                'acompanantes-MAX_NUM_FORMS': '1',
                'acompanantes-0-tipo_documento': 'CC',
                'acompanantes-0-numero_documento': '222333444',
                'acompanantes-0-nombres': 'Luis',
                'acompanantes-0-apellidos': 'Gómez',
                'acompanantes-0-telefono': '',
            },
        )
        reserva_futura.refresh_from_db()
        self.habitacion.refresh_from_db()
        self.assertEqual(reserva_futura.estado, 'En curso')
        self.assertEqual(self.habitacion.estado, 'Ocupada')

    def test_customer_cancellation_requires_post_and_releases_room(self):
        fecha_ingreso = timezone.localdate() + timedelta(days=2)
        reserva = Reserva.objects.create(
            huesped=self.huesped,
            habitacion=self.habitacion,
            fecha_ingreso=fecha_ingreso,
            fecha_salida=fecha_ingreso + timedelta(days=1),
            estado='Confirmada',
        )
        self.habitacion.estado = 'Reservada'
        self.habitacion.save(update_fields=['estado'])
        url = reverse('cancelar_reserva_cliente', args=[reserva.pk])

        self.assertEqual(self.client.get(url).status_code, 405)
        response = self.client.post(url)

        self.assertRedirects(
            response,
            reverse('mis_reservas_cliente'),
            fetch_redirect_response=False,
        )
        reserva.refresh_from_db()
        self.habitacion.refresh_from_db()
        self.assertEqual(reserva.estado, 'Cancelada')
        self.assertEqual(self.habitacion.estado, 'Disponible')

    def test_booking_dates_are_strictly_validated(self):
        url = reverse(
            'iniciar_reserva_web',
            kwargs={'habitacion_id': self.habitacion.pk},
        )
        ayer = timezone.localdate() - timedelta(days=1)
        response = self.client.post(url, {
            'fecha_ingreso': ayer.isoformat(),
            'fecha_salida': timezone.localdate().isoformat(),
            'cantidad_huespedes': 3,
        })

        self.assertEqual(response.status_code, 200)
        self.assertIn('fecha_ingreso', response.context['form'].errors)
        self.assertIn('cantidad_huespedes', response.context['form'].errors)
        self.assertNotIn('reserva_temporal', self.client.session)

    def test_customer_completes_payment_and_receives_receipt_email(self):
        inicio_url = reverse(
            'iniciar_reserva_web',
            kwargs={'habitacion_id': self.habitacion.pk},
        )
        fecha_ingreso = timezone.localdate() + timedelta(days=1)
        fecha_salida = fecha_ingreso + timedelta(days=2)

        response = self.client.get(inicio_url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'hotel_app/iniciar_reserva.html')

        response = self.client.post(inicio_url, {
            'fecha_ingreso': fecha_ingreso.isoformat(),
            'fecha_salida': fecha_salida.isoformat(),
            'cantidad_huespedes': 2,
        })
        self.assertRedirects(
            response,
            reverse('checkout_datos_huesped'),
            fetch_redirect_response=False,
        )
        response = self.client.get(reverse('checkout_datos_huesped'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'hotel_app/checkout_huesped.html')

        response = self.client.post(
            reverse('checkout_datos_huesped'),
            {
                'tipo_documento': 'CC',
                'numero_documento': self.huesped.numero_documento,
                'nombres': self.huesped.nombres,
                'apellidos': self.huesped.apellidos,
                'telefono': self.huesped.telefono,
                'correo': self.customer.email,
                'nacionalidad': 'Colombiana',
                'solicitudes_especiales': 'Llegada en la tarde',
            },
        )
        self.assertRedirects(
            response,
            reverse('pasarela_pago_simulada'),
            fetch_redirect_response=False,
        )
        response = self.client.get(reverse('pasarela_pago_simulada'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'hotel_app/pasarela_pago.html')
        self.assertContains(response, 'type="radio"')
        for metodo in ('PSE', 'Nequi', 'Daviplata', 'Tarjeta débito', 'Tarjeta crédito'):
            self.assertContains(response, metodo)

        with patch(
            'apps.hotel_app.views.send_mail',
            return_value=1,
        ) as send_mail_mock:
            response = self.client.post(
                reverse('pasarela_pago_simulada'),
                {
                    'modalidad_pago': 'Anticipo',
                    'metodo_pago': 'Nequi',
                },
            )

        reserva = Reserva.objects.get()
        pago = Pago.objects.get(reserva=reserva)
        transaccion = TransaccionPago.objects.get(reserva=reserva)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse(
            'confirmacion_reserva_exitoso',
            kwargs={'reserva_id': reserva.pk},
        ))
        self.assertEqual(reserva.estado, 'Confirmada')
        self.assertEqual(reserva.valor_total, Decimal('240000.00'))
        self.assertEqual(reserva.saldo_pendiente, Decimal('120000.00'))
        self.assertEqual(pago.monto, Decimal('120000.00'))
        self.assertEqual(pago.metodo_pago, 'Nequi')
        self.assertEqual(transaccion.metodo_pago, 'Nequi')
        self.habitacion.refresh_from_db()
        self.assertEqual(self.habitacion.estado, 'Reservada')
        self.assertEqual(send_mail_mock.call_count, 2)
        self.assertEqual(
            send_mail_mock.call_args_list[0].args[3],
            [self.customer.email],
        )
        self.assertIn(
            'ostwaldjoel09@gmail.com',
            send_mail_mock.call_args_list[1].args[3],
        )

        confirmacion_url = response.url
        response = self.client.get(confirmacion_url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'hotel_app/confirmacion_reserva.html')
        self.assertContains(response, transaccion.referencia_pasarela)
