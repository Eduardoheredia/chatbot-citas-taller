from typing import Any, Awaitable, Callable, Dict, List, Optional, Text
import os
import uuid

from sanic import Blueprint, response
from sanic.request import Request
from rasa.core.channels.channel import InputChannel, UserMessage, CollectingOutputChannel
from rasa.core.channels.rest import RestInput
from rasa.core.constants import DEFAULT_REQUEST_TIMEOUT
from itsdangerous import URLSafeTimedSerializer, BadSignature


class SessionRestInput(RestInput):
    """REST channel que obtiene el `sender_id` de la cookie de sesi\u00f3n."""

    @classmethod
    def name(cls) -> Text:
        return "session_rest"

    def _get_user_id(self, request: Request) -> Optional[Text]:
        cookie_name = os.environ.get("SESSION_COOKIE_NAME", "session")
        cookie = request.cookies.get(cookie_name)
        if not cookie:
            return None
        secret = os.environ.get("SECRET_KEY", "poner_un_valor_seguro")
        try:
            data = URLSafeTimedSerializer(secret, salt="cookie-session").loads(cookie)
            return data.get("telefono") or data.get("user_id")
        except BadSignature:
            return None

    def blueprint(self, on_new_message: Callable[[UserMessage], Awaitable[Any]]) -> Blueprint:
        custom_webhook = Blueprint("session_rest_webhook", __name__)

        @custom_webhook.post("/webhooks/session_rest/webhook")
        async def receive(request: Request) -> response.HTTPResponse:
            sender_id = (
                self._get_user_id(request)
                or request.json.get("sender")
                or uuid.uuid4().hex
            )
            text = request.json.get("text")
            metadata = request.json.get("metadata")
            collector = CollectingOutputChannel()
            message = UserMessage(
                text,
                collector,
                sender_id,
                input_channel=self.name(),
                metadata=metadata,
            )
            await on_new_message(message)
            return response.json(collector.messages)

        return custom_webhook
