"""Envío de correos por la API de Brevo (HTTPS).

Render en su plan gratis bloquea el envío por SMTP, así que los correos se
mandan con una petición HTTPS a https://api.brevo.com/v3/smtp/email.
"""
import html
import logging

import httpx
from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend

logger = logging.getLogger("chatbot")
BREVO_URL = "https://api.brevo.com/v3/smtp/email"


class BrevoEmailBackend(BaseEmailBackend):
    def send_messages(self, email_messages):
        sent = 0
        for message in email_messages:
            payload = {
                "sender": {"email": settings.DEFAULT_FROM_EMAIL, "name": settings.EMAIL_FROM_NAME},
                "to": [{"email": address} for address in message.to],
                "subject": message.subject,
                "textContent": message.body,
            }
            for content, mimetype in getattr(message, "alternatives", []) or []:
                if mimetype == "text/html":
                    payload["htmlContent"] = content
            if "htmlContent" not in payload:  # Brevo exige htmlContent cuando no hay plantilla
                payload["htmlContent"] = "<p>" + html.escape(message.body).replace("\n", "<br>") + "</p>"
            try:
                response = httpx.post(BREVO_URL, json=payload, timeout=15,
                                      headers={"api-key": settings.BREVO_API_KEY, "accept": "application/json"})
                response.raise_for_status()
                sent += 1
            except httpx.HTTPError as exc:
                logger.error("Brevo no pudo enviar el correo: %s", exc)
                if not self.fail_silently:
                    raise
        return sent
