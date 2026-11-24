from django import forms
from django.forms import BaseFormSet
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.utils import timezone

from .models import (
    AcompañanteReserva,
    Habitacion,
    Huesped,
    Pago,
    Reserva,
    ServicioAdicional,
)
from .validators import validate_digits, validate_letters_and_spaces


class InicioSesionForm(AuthenticationForm):
    def clean(self):
        username = self.cleaned_data.get('username')
        if username and '@' in username:
            matches = list(
                get_user_model()._default_manager.filter(
                    email__iexact=username,
                ).values_list('username', flat=True)[:2]
            )
            if len(matches) == 1:
                self.cleaned_data['username'] = matches[0]

        return super().clean()


class ServicioAdicionalForm(forms.ModelForm):
    precio = forms.DecimalField(
        min_value=0.01,
        max_digits=10,
        decimal_places=2,
        widget=forms.NumberInput(attrs={
            'class': 'form-control rounded-3 py-2',
            'step': '0.01',
            'placeholder': 'Ej. 80000',
        }),
    )

    class Meta:
        model = ServicioAdicional
        fields = ('nombre', 'precio', 'descripcion')
        widgets = {
            'nombre': forms.TextInput(attrs={
                'class': 'form-control rounded-3 py-2',
                'placeholder': 'Ej. Tour turístico a Cabo de la Vela',
            }),
            'descripcion': forms.Textarea(attrs={
                'class': 'form-control rounded-3 py-2',
                'rows': 3,
                'placeholder': 'Detalles del servicio...',
            }),
        }


class PagoForm(forms.ModelForm):
    monto = forms.DecimalField(
        min_value=0.01,
        max_digits=10,
        decimal_places=2,
        widget=forms.NumberInput(attrs={
            'class': 'form-control rounded-3 py-2',
            'step': '0.01',
            'placeholder': 'Ej. 150000',
        }),
    )

    class Meta:
        model = Pago
        fields = ('reserva', 'monto', 'metodo_pago', 'observacion')
        widgets = {
            'reserva': forms.Select(attrs={
                'class': 'form-select rounded-3 py-2',
            }),
            'metodo_pago': forms.Select(attrs={
                'class': 'form-select rounded-3 py-2',
            }),
            'observacion': forms.Textarea(attrs={
                'class': 'form-control rounded-3 py-2',
                'rows': 2,
                'placeholder': 'Detalles adicionales del pago...',
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['reserva'].queryset = Reserva.objects.select_related(
            'huesped',
            'habitacion',
        ).order_by('-fecha_creacion')


class RegistroClienteForm(forms.Form):
    username = forms.CharField(max_length=150, label='Nombre de usuario')
    email = forms.EmailField(label='Correo electrónico')
    password = forms.CharField(
        label='Contraseña',
        strip=False,
        widget=forms.PasswordInput,
    )
    confirm_password = forms.CharField(
        label='Confirmar contraseña',
        strip=False,
        widget=forms.PasswordInput,
    )
    nombres = forms.CharField(
        max_length=100,
        validators=[validate_letters_and_spaces],
    )
    apellidos = forms.CharField(
        max_length=100,
        validators=[validate_letters_and_spaces],
    )
    telefono = forms.CharField(max_length=20, validators=[validate_digits])
    documento = forms.CharField(max_length=20, validators=[validate_digits])
    nacionalidad = forms.CharField(
        max_length=50,
        validators=[validate_letters_and_spaces],
        initial='Colombiana',
    )

    def clean_username(self):
        username = self.cleaned_data['username'].strip()
        if get_user_model()._default_manager.filter(
            username__iexact=username,
        ).exists():
            raise ValidationError('Este nombre de usuario ya está en uso.')
        return username

    def clean_email(self):
        email = self.cleaned_data['email'].strip()
        if get_user_model()._default_manager.filter(
            email__iexact=email,
        ).exists():
            raise ValidationError('Ya existe una cuenta con este correo.')
        if Huesped.objects.filter(correo__iexact=email).exists():
            raise ValidationError('Este correo ya está asociado a un huésped.')
        return email

    def clean_documento(self):
        documento = self.cleaned_data['documento']
        if Huesped.objects.filter(numero_documento=documento).exists():
            raise ValidationError('Este documento ya está registrado.')
        return documento

    def clean_password(self):
        password = self.cleaned_data['password']
        user_model = get_user_model()
        user = user_model(
            username=self.data.get('username', '').strip(),
            email=self.data.get('email', '').strip(),
        )
        validate_password(password, user=user)
        return password

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get('password')
        confirm_password = cleaned_data.get('confirm_password')
        if password and confirm_password and password != confirm_password:
            self.add_error(
                'confirm_password',
                'Las contraseñas no coinciden.',
            )
        return cleaned_data


class ReservaClienteForm(forms.Form):
    habitacion = forms.ModelChoiceField(
        queryset=Habitacion.objects.none(),
        label='Habitación disponible',
    )
    fecha_ingreso = forms.DateField(
        widget=forms.DateInput(attrs={'type': 'date'}),
        label='Fecha de ingreso',
    )
    fecha_salida = forms.DateField(
        widget=forms.DateInput(attrs={'type': 'date'}),
        label='Fecha de salida',
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['habitacion'].queryset = Habitacion.objects.exclude(
            estado__in=Habitacion.ESTADOS_NO_RESERVABLES,
        ).order_by('precio', 'numero')

    def clean(self):
        cleaned_data = super().clean()
        fecha_ingreso = cleaned_data.get('fecha_ingreso')
        fecha_salida = cleaned_data.get('fecha_salida')

        if fecha_ingreso and fecha_salida:
            if fecha_ingreso < timezone.localdate():
                self.add_error(
                    'fecha_ingreso',
                    'La fecha de ingreso no puede estar en el pasado.',
                )
            if fecha_salida <= fecha_ingreso:
                self.add_error(
                    'fecha_salida',
                    'La fecha de salida debe ser posterior a la fecha de ingreso.',
                )

        return cleaned_data


class FechasReservaWebForm(forms.Form):
    fecha_ingreso = forms.DateField(
        label='Fecha de ingreso',
        widget=forms.DateInput(attrs={
            'class': 'form-control rounded-3 py-2',
            'type': 'date',
        }),
    )
    fecha_salida = forms.DateField(
        label='Fecha de salida',
        widget=forms.DateInput(attrs={
            'class': 'form-control rounded-3 py-2',
            'type': 'date',
        }),
    )
    cantidad_huespedes = forms.IntegerField(
        label='Cantidad de huéspedes',
        min_value=1,
        widget=forms.NumberInput(attrs={
            'class': 'form-control rounded-3 py-2',
            'min': 1,
        }),
    )

    def __init__(self, *args, habitacion, **kwargs):
        self.habitacion = habitacion
        super().__init__(*args, **kwargs)
        self.fields['cantidad_huespedes'].widget.attrs['max'] = habitacion.capacidad

    def clean(self):
        cleaned_data = super().clean()
        fecha_ingreso = cleaned_data.get('fecha_ingreso')
        fecha_salida = cleaned_data.get('fecha_salida')
        cantidad_huespedes = cleaned_data.get('cantidad_huespedes')

        if fecha_ingreso and fecha_ingreso < timezone.localdate():
            self.add_error(
                'fecha_ingreso',
                'La fecha de ingreso no puede estar en el pasado.',
            )
        if fecha_ingreso and fecha_salida and fecha_salida <= fecha_ingreso:
            self.add_error(
                'fecha_salida',
                'La fecha de salida debe ser posterior a la fecha de ingreso.',
            )
        if cantidad_huespedes and cantidad_huespedes > self.habitacion.capacidad:
            self.add_error(
                'cantidad_huespedes',
                f'Esta habitación tiene capacidad máxima para {self.habitacion.capacidad} huéspedes.',
            )

        return cleaned_data


class PagoCheckoutForm(forms.Form):
    modalidad_pago = forms.ChoiceField(
        label='Modalidad de pago',
        choices=Reserva.MODALIDADES_PAGO,
        initial='Completo',
        widget=forms.RadioSelect,
    )
    metodo_pago = forms.ChoiceField(
        label='Método de pago',
        choices=(
            ('PSE', 'PSE'),
            ('Nequi', 'Nequi'),
            ('Daviplata', 'Daviplata'),
            ('Tarjeta débito', 'Tarjeta débito'),
            ('Tarjeta crédito', 'Tarjeta crédito'),
        ),
        initial='PSE',
        widget=forms.RadioSelect,
    )


class HuespedForm(forms.ModelForm):
    class Meta:
        model = Huesped
        fields = (
            'tipo_documento',
            'numero_documento',
            'nombres',
            'apellidos',
            'telefono',
            'correo',
            'nacionalidad',
        )
        widgets = {
            'tipo_documento': forms.Select(attrs={'class': 'form-select rounded-3 py-2'}),
            'numero_documento': forms.TextInput(attrs={
                'class': 'form-control rounded-3 py-2',
                'inputmode': 'numeric',
                'pattern': '[0-9]+',
                'data-digits-only': 'true',
            }),
            'nombres': forms.TextInput(attrs={
                'class': 'form-control rounded-3 py-2',
                'data-letters-only': 'true',
            }),
            'apellidos': forms.TextInput(attrs={
                'class': 'form-control rounded-3 py-2',
                'data-letters-only': 'true',
            }),
            'telefono': forms.TextInput(attrs={
                'class': 'form-control rounded-3 py-2',
                'inputmode': 'numeric',
                'pattern': '[0-9]+',
                'data-digits-only': 'true',
            }),
            'correo': forms.EmailInput(attrs={
                'class': 'form-control rounded-3 py-2',
            }),
            'nacionalidad': forms.TextInput(attrs={
                'class': 'form-control rounded-3 py-2',
                'data-letters-only': 'true',
            }),
        }


class ReservaForm(forms.ModelForm):
    class Meta:
        model = Reserva
        fields = ('huesped', 'habitacion', 'fecha_ingreso', 'fecha_salida')
        widgets = {
            'huesped': forms.Select(attrs={'class': 'form-select rounded-3 py-2'}),
            'habitacion': forms.Select(attrs={'class': 'form-select rounded-3 py-2'}),
            'fecha_ingreso': forms.DateInput(
                attrs={'class': 'form-control rounded-3 py-2', 'type': 'date'},
            ),
            'fecha_salida': forms.DateInput(
                attrs={'class': 'form-control rounded-3 py-2', 'type': 'date'},
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['huesped'].queryset = Huesped.objects.order_by(
            'nombres',
            'apellidos',
        )
        self.fields['habitacion'].queryset = Habitacion.objects.exclude(
            estado__in=Habitacion.ESTADOS_NO_RESERVABLES,
        ).order_by('numero')

    def clean(self):
        cleaned_data = super().clean()
        fecha_ingreso = cleaned_data.get('fecha_ingreso')
        fecha_salida = cleaned_data.get('fecha_salida')

        if fecha_ingreso and fecha_salida and fecha_salida <= fecha_ingreso:
            self.add_error(
                'fecha_salida',
                'La fecha de salida debe ser posterior a la fecha de ingreso.',
            )

        return cleaned_data


class CheckinOcupacionForm(forms.Form):
    cantidad_huespedes = forms.IntegerField(
        min_value=1,
        label='Personas que se alojarán en la habitación',
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'min': 1,
        }),
    )

    def __init__(self, *args, capacidad, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['cantidad_huespedes'].max_value = capacidad
        self.fields['cantidad_huespedes'].widget.attrs['max'] = capacidad


class CheckinAcompananteForm(forms.Form):
    tipo_documento = forms.ChoiceField(
        choices=Huesped.TIPOS_DOCUMENTO,
        label='Tipo de documento',
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    numero_documento = forms.CharField(
        max_length=50,
        label='Número de documento',
        required=False,
        validators=[validate_digits],
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'autocomplete': 'off',
            'inputmode': 'numeric',
            'pattern': '[0-9]+',
            'data-digits-only': 'true',
        }),
    )
    nombres = forms.CharField(
        max_length=100,
        label='Nombres',
        required=False,
        validators=[validate_letters_and_spaces],
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'autocomplete': 'given-name',
            'data-letters-only': 'true',
        }),
    )
    apellidos = forms.CharField(
        max_length=100,
        label='Apellidos',
        required=False,
        validators=[validate_letters_and_spaces],
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'autocomplete': 'family-name',
            'data-letters-only': 'true',
        }),
    )
    telefono = forms.CharField(
        max_length=20,
        label='Teléfono (opcional)',
        required=False,
        validators=[validate_digits],
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'inputmode': 'numeric',
            'pattern': '[0-9]*',
            'autocomplete': 'tel',
            'data-digits-only': 'true',
        }),
    )

    def clean_numero_documento(self):
        numero = self.cleaned_data['numero_documento'].strip()
        if numero:
            validate_digits(numero)
        return numero

    def clean(self):
        cleaned_data = super().clean()
        campos_requeridos = (
            'tipo_documento',
            'numero_documento',
            'nombres',
            'apellidos',
        )
        if self.has_changed() and any(
            not cleaned_data.get(campo) for campo in campos_requeridos
        ):
            raise ValidationError(
                'Completa el tipo y número de documento, los nombres y los apellidos del acompañante.',
            )
        return cleaned_data


class CheckinAcompananteFormSet(BaseFormSet):
    def add_non_form_error(self, message):
        self._non_form_errors.append(message)

    def clean(self):
        super().clean()
        if any(self.errors):
            return

        documentos = set()
        for form in self.forms:
            if not form.has_changed():
                continue
            documento = form.cleaned_data.get('numero_documento', '').casefold()
            if documento in documentos:
                raise ValidationError(
                    'No repitas el número de documento de un acompañante.',
                )
            documentos.add(documento)


class HabitacionCreacionForm(forms.ModelForm):
    capacidad = forms.IntegerField(
        min_value=1,
        label='Capacidad máxima (personas)',
        widget=forms.NumberInput(attrs={
            'class': 'form-control rounded-3 py-2',
            'min': 1,
        }),
    )
    precio = forms.DecimalField(
        min_value=0.01,
        max_digits=10,
        decimal_places=2,
        widget=forms.NumberInput(attrs={
            'class': 'form-control rounded-3 py-2',
            'step': '0.01',
            'min': '0.01',
        }),
    )
    piso = forms.IntegerField(
        min_value=0,
        widget=forms.NumberInput(attrs={
            'class': 'form-control rounded-3 py-2',
            'min': 0,
        }),
    )

    class Meta:
        model = Habitacion
        fields = (
            'numero',
            'tipo',
            'capacidad',
            'precio',
            'piso',
            'descripcion',
            'imagen',
        )
        widgets = {
            'numero': forms.TextInput(attrs={
                'class': 'form-control rounded-3 py-2',
            }),
            'tipo': forms.Select(attrs={
                'class': 'form-select rounded-3 py-2',
            }),
            'descripcion': forms.Textarea(attrs={
                'class': 'form-control rounded-3 py-2',
                'rows': 3,
            }),
            'imagen': forms.ClearableFileInput(attrs={
                'class': 'form-control rounded-3 py-2',
                'accept': 'image/*',
            }),
        }


class HabitacionEdicionForm(forms.ModelForm):
    imagen_url = forms.CharField(
        required=False,
        label='URL de Imagen (opcional)',
        validators=[URLValidator()],
        widget=forms.URLInput(attrs={
            'class': 'form-control',
            'placeholder': 'https://ejemplo.com/habitacion.jpg',
        }),
    )

    class Meta:
        model = Habitacion
        fields = ('estado', 'limpieza', 'mantenimiento', 'imagen', 'imagen_url')
        widgets = {
            'estado': forms.Select(attrs={'class': 'form-select'}),
            'limpieza': forms.Select(attrs={'class': 'form-select'}),
            'mantenimiento': forms.TextInput(attrs={'class': 'form-control'}),
            'imagen': forms.ClearableFileInput(attrs={
                'class': 'form-control',
                'accept': 'image/*',
            }),
        }

    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data.get('imagen') and cleaned_data.get('imagen_url'):
            raise ValidationError('Usa una imagen subida o una URL, no ambas al mismo tiempo.')
        return cleaned_data
