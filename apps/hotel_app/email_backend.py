import json
from email.utils import getaddresses
from smtplib import SMTPException
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend


class GmailAppsScriptEmailBackend(BaseEmailBackend):
    def send_messages(self, email_messages):
        if not email_messages:
            return 0

        try:
            relay_url, relay_token = self._configuration()
        except SMTPException:
            if self.fail_silently:
                return 0
            raise

        sent = 0
        for message in email_messages:
            try:
                self._send(message, relay_url, relay_token)
            except (OSError, SMTPException):
                if not self.fail_silently:
                    raise
            else:
                sent += 1
        return sent

    @staticmethod
    def _configuration():
        relay_url = settings.GMAIL_RELAY_URL.strip()
        relay_token = settings.GMAIL_RELAY_TOKEN.strip()
        if not relay_url or not relay_token:
            raise SMTPException(
                'Faltan GMAIL_RELAY_URL o GMAIL_RELAY_TOKEN en Render.',
            )

        parsed_url = urlparse(relay_url)
        if (
            parsed_url.scheme != 'https'
            or parsed_url.hostname != 'script.google.com'
            or not parsed_url.path.startswith('/macros/s/')
            or not parsed_url.path.endswith('/exec')
        ):
            raise SMTPException(
                'GMAIL_RELAY_URL debe ser la URL HTTPS /exec de Apps Script.',
            )
        return relay_url, relay_token

    def _send(self, message, relay_url, relay_token):
        if getattr(message, 'attachments', None):
            raise SMTPException(
                'El relevo de Gmail no admite archivos adjuntos.',
            )

        recipients = self._addresses(message.to)
        if not recipients:
            raise SMTPException('El correo no tiene destinatarios válidos.')

        payload = {
            'token': relay_token,
            'to': recipients,
            'subject': message.subject,
            'body': message.body,
        }

        cc = self._addresses(message.cc)
        bcc = self._addresses(message.bcc)
        reply_to = self._addresses(message.reply_to)
        if cc:
            payload['cc'] = cc
        if bcc:
            payload['bcc'] = bcc
        if reply_to:
            payload['replyTo'] = reply_to[0]

        html_body = (
            message.body if message.content_subtype == 'html' else None
        )
        for content, mimetype in getattr(message, 'alternatives', ()):
            if mimetype == 'text/html':
                html_body = content
                break
        if html_body:
            payload['htmlBody'] = html_body

        request = Request(
            relay_url,
            data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
            headers={
                'Content-Type': 'application/json',
                'Accept': 'application/json',
            },
            method='POST',
        )
        try:
            with urlopen(request, timeout=settings.EMAIL_TIMEOUT) as response:
                result = json.loads(response.read().decode('utf-8'))
        except HTTPError as error:
            raise SMTPException(
                self._http_error_message(error, relay_token),
            ) from error
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise SMTPException(
                'El relevo de Gmail devolvió una respuesta inválida.',
            ) from error

        if not isinstance(result, dict):
            raise SMTPException(
                'El relevo de Gmail devolvió una respuesta inválida.',
            )
        if result.get('ok') is not True:
            error = result.get('error')
            if not isinstance(error, str) or not error.strip():
                error = 'Gmail no confirmó el envío.'
            raise SMTPException(
                error.strip().replace(relay_token, '[oculta]')[:300],
            )

    @staticmethod
    def _addresses(addresses):
        return [
            email
            for _, email in getaddresses(addresses)
            if email
        ]

    @staticmethod
    def _http_error_message(error, relay_token):
        try:
            error_data = json.loads(error.read().decode('utf-8'))
        except (UnicodeDecodeError, json.JSONDecodeError):
            error_data = None

        detail = ''
        if isinstance(error_data, dict):
            message = error_data.get('error')
            if isinstance(message, str):
                detail = message.strip()
        detail = detail.replace(relay_token, '[oculta]')[:300]
        suffix = f' ({detail})' if detail else ''
        return f'El relevo de Gmail rechazó la solicitud con HTTP {error.code}{suffix}.'
