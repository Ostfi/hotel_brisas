import json
from email.utils import parseaddr
from smtplib import SMTPException
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend


class BrevoEmailBackend(BaseEmailBackend):
    api_url = 'https://api.brevo.com/v3/smtp/email'

    def send_messages(self, email_messages):
        if not email_messages:
            return 0

        api_key = settings.BREVO_API_KEY
        if not api_key:
            if self.fail_silently:
                return 0
            raise SMTPException('La variable BREVO_API_KEY no está configurada.')

        sent = 0
        for message in email_messages:
            try:
                self._send(message, api_key)
            except (OSError, SMTPException):
                if not self.fail_silently:
                    raise
            else:
                sent += 1
        return sent

    def _send(self, message, api_key):
        sender = self._contact(message.from_email)
        if not sender:
            raise SMTPException('El correo remitente no está configurado correctamente.')

        payload = {
            'sender': sender,
            'to': self._contacts(message.to),
            'subject': message.subject,
        }
        if message.content_subtype == 'html':
            payload['htmlContent'] = message.body
        else:
            payload['textContent'] = message.body

        if message.cc:
            payload['cc'] = self._contacts(message.cc)
        if message.bcc:
            payload['bcc'] = self._contacts(message.bcc)
        for content, mimetype in getattr(message, 'alternatives', ()):
            if mimetype == 'text/html':
                payload['htmlContent'] = content
                break

        request = Request(
            self.api_url,
            data=json.dumps(payload).encode('utf-8'),
            headers={
                'api-key': api_key,
                'Content-Type': 'application/json',
                'Accept': 'application/json',
            },
            method='POST',
        )
        try:
            with urlopen(request, timeout=settings.EMAIL_TIMEOUT) as response:
                if response.status not in (201, 202):
                    raise SMTPException(
                        f'Brevo rechazó el correo con HTTP {response.status}.',
                    )
        except HTTPError as error:
            try:
                error_data = json.loads(error.read().decode('utf-8'))
            except (UnicodeDecodeError, json.JSONDecodeError):
                error_data = None

            details = []
            if isinstance(error_data, dict):
                for field in ('code', 'message'):
                    value = error_data.get(field)
                    if isinstance(value, str) and value.strip():
                        details.append(value.strip().replace(api_key, '[oculta]'))
            detail = f" ({': '.join(details)[:300]})" if details else ''
            raise SMTPException(
                f'Brevo rechazó el correo con HTTP {error.code}{detail}.',
            ) from error

    @classmethod
    def _contacts(cls, addresses):
        contacts = [cls._contact(address) for address in addresses]
        if not contacts or any(contact is None for contact in contacts):
            raise SMTPException('El correo no tiene destinatarios válidos.')
        return contacts

    @staticmethod
    def _contact(address):
        name, email = parseaddr(address)
        if not email:
            return None
        contact = {'email': email}
        if name:
            contact['name'] = name
        return contact
