import base64
import json
from smtplib import SMTPException
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend


class GmailAPIEmailBackend(BaseEmailBackend):
    token_url = 'https://oauth2.googleapis.com/token'
    send_url = 'https://gmail.googleapis.com/gmail/v1/users/me/messages/send'
    credential_settings = (
        'GMAIL_CLIENT_ID',
        'GMAIL_CLIENT_SECRET',
        'GMAIL_REFRESH_TOKEN',
    )

    def send_messages(self, email_messages):
        if not email_messages:
            return 0

        try:
            credentials = self._credentials()
            access_token = self._get_access_token(credentials)
        except (OSError, SMTPException):
            if self.fail_silently:
                return 0
            raise

        sent = 0
        for message in email_messages:
            try:
                self._send(message, access_token, credentials)
            except (OSError, SMTPException):
                if not self.fail_silently:
                    raise
            else:
                sent += 1
        return sent

    @classmethod
    def _credentials(cls):
        credentials = {
            name: getattr(settings, name).strip()
            for name in cls.credential_settings
        }
        missing = [name for name, value in credentials.items() if not value]
        if missing:
            raise SMTPException(
                'Faltan credenciales de Gmail API: ' + ', '.join(missing),
            )
        return credentials

    def _get_access_token(self, credentials):
        data = urlencode({
            'client_id': credentials['GMAIL_CLIENT_ID'],
            'client_secret': credentials['GMAIL_CLIENT_SECRET'],
            'refresh_token': credentials['GMAIL_REFRESH_TOKEN'],
            'grant_type': 'refresh_token',
        }).encode('utf-8')
        request = Request(
            self.token_url,
            data=data,
            headers={'Content-Type': 'application/x-www-form-urlencoded'},
            method='POST',
        )
        try:
            with urlopen(request, timeout=settings.EMAIL_TIMEOUT) as response:
                token_data = json.loads(response.read().decode('utf-8'))
        except HTTPError as error:
            raise SMTPException(
                self._http_error_message('Google OAuth', error, credentials),
            ) from error
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise SMTPException(
                'Google OAuth devolvió una respuesta inválida.',
            ) from error

        if not isinstance(token_data, dict):
            raise SMTPException(
                'Google OAuth devolvió una respuesta inválida.',
            )
        access_token = token_data.get('access_token')
        if not isinstance(access_token, str) or not access_token:
            raise SMTPException(
                'Google OAuth no devolvió un token de acceso válido.',
            )
        return access_token

    def _send(self, message, access_token, credentials):
        raw_message = base64.urlsafe_b64encode(
            message.message().as_bytes(),
        ).decode('ascii').rstrip('=')
        request = Request(
            self.send_url,
            data=json.dumps({'raw': raw_message}).encode('utf-8'),
            headers={
                'Authorization': f'Bearer {access_token}',
                'Content-Type': 'application/json',
                'Accept': 'application/json',
            },
            method='POST',
        )
        try:
            with urlopen(request, timeout=settings.EMAIL_TIMEOUT) as response:
                if response.status != 200:
                    raise SMTPException(
                        f'Gmail API rechazó el correo con HTTP {response.status}.',
                    )
        except HTTPError as error:
            secrets = dict(credentials, access_token=access_token)
            raise SMTPException(
                self._http_error_message('Gmail API', error, secrets),
            ) from error

    @staticmethod
    def _http_error_message(service, error, secrets):
        try:
            error_data = json.loads(error.read().decode('utf-8'))
        except (UnicodeDecodeError, json.JSONDecodeError):
            error_data = None

        details = []
        if isinstance(error_data, dict):
            error_info = error_data.get('error')
            if isinstance(error_info, dict):
                for field in ('status', 'message'):
                    value = error_info.get(field)
                    if isinstance(value, str) and value.strip():
                        details.append(value.strip())
            elif isinstance(error_info, str) and error_info.strip():
                details.append(error_info.strip())
                description = error_data.get('error_description')
                if isinstance(description, str) and description.strip():
                    details.append(description.strip())

        detail = ': '.join(details)
        for secret in secrets.values():
            if secret:
                detail = detail.replace(secret, '[oculta]')
        suffix = f' ({detail[:300]})' if detail else ''
        return f'{service} rechazó la solicitud con HTTP {error.code}{suffix}.'
