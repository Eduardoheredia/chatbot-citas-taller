from typing import Optional, Text
import os

from sanic.request import Request
from rasa.core.channels.rest import RestInput
from itsdangerous import URLSafeTimedSerializer, BadSignature


class SessionRestInput(RestInput):
    """REST channel that retrieves ``sender_id`` from a session cookie."""

    @classmethod
    def name(cls) -> Text:
        return "session_rest"

    async def _extract_sender(self, request: Request) -> Optional[Text]:
        """Read sender ID from session cookie or fall back to body field."""
        cookie_name = os.environ.get("SESSION_COOKIE_NAME", "session")
        cookie = request.cookies.get(cookie_name)
        if cookie:
            secret = os.environ.get("SECRET_KEY", "poner_un_valor_seguro")
            try:
                data = URLSafeTimedSerializer(secret, salt="cookie-session").loads(cookie)
                return data.get("telefono") or data.get("user_id")
            except BadSignature:
                pass
        return await super()._extract_sender(request)

