from typing import Optional, Text, Dict, Any, Callable, Awaitable
import os
import json
import uuid
import logging

logger = logging.getLogger(__name__)
from http.cookies import SimpleCookie

from sanic.request import Request
from sanic import response, Blueprint
from sanic.response import HTTPResponse
from rasa.core.channels.channel import UserMessage
from rasa.core.channels.rest import RestInput
from rasa.core.channels.socketio import (
    SocketIOInput,
    SocketIOOutput,
    SocketBlueprint,
)
import rasa.shared.utils.io
from socketio import AsyncServer
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


class SessionSocketIOInput(SocketIOInput):
    """Socket.IO channel that sets ``sender_id`` using session cookies."""

    @classmethod
    def name(cls) -> Text:
        return "session_socketio"

    def _sender_from_cookie(self, environ: Dict[str, Any]) -> Optional[Text]:
        """Extract the phone or user ID from Flask's session cookie."""
        cookie_header = environ.get("HTTP_COOKIE") or ""
        cookie = SimpleCookie()
        cookie.load(cookie_header)
        cookie_name = os.environ.get("SESSION_COOKIE_NAME", "session")
        morsel = cookie.get(cookie_name)
        if not morsel:
            return None
        secret = os.environ.get("SECRET_KEY", "poner_un_valor_seguro")
        try:
            data = URLSafeTimedSerializer(secret, salt="cookie-session").loads(
                morsel.value
            )
            return data.get("telefono") or data.get("user_id")
        except BadSignature:
            return None

    def blueprint(
        self, on_new_message: Callable[[UserMessage], Awaitable[Any]]
    ) -> Blueprint:
        """Return a custom blueprint that overrides the session ID."""
        sio = AsyncServer(async_mode="sanic", cors_allowed_origins=[])
        socketio_webhook = SocketBlueprint(
            sio, self.socketio_path, "socketio_webhook", __name__
        )
        self.sio = sio

        @socketio_webhook.route("/health", methods=["GET"])
        async def health(_: Request) -> HTTPResponse:
            return response.json({"status": "ok"})

        @socketio_webhook.route("/", methods=["GET", "POST"])
        async def handle_request(request: Request) -> HTTPResponse:
            """Forward the request to ``python-socketio`` and return its response."""
            result = await sio.handle_request(request)
            if isinstance(result, HTTPResponse):
                return result
            if isinstance(result, dict):
                return response.json(result)
            return response.text(result if result is not None else "")

        @sio.on("connect", namespace=self.namespace)
        async def connect(sid: Text, environ: Dict, auth: Optional[Dict]) -> bool:
            logger.debug(f"User {sid} connected to socketIO endpoint.")
            sender = self._sender_from_cookie(environ)
            if sender and self.session_persistence:
                sio.enter_room(sid, sender)
                await sio.emit("session_confirm", sender, room=sid)
            return True

        @sio.on("disconnect", namespace=self.namespace)
        async def disconnect(sid: Text) -> None:
            logger.debug(f"User {sid} disconnected from socketIO endpoint.")

        @sio.on("session_request", namespace=self.namespace)
        async def session_request(sid: Text, data: Optional[Dict]) -> None:
            sender = None
            if data:
                sender = data.get("session_id")
            if not sender:
                sender = self._sender_from_cookie({})
            if not sender:
                sender = uuid.uuid4().hex
            if self.session_persistence:
                sio.enter_room(sid, sender)
            await sio.emit("session_confirm", sender, room=sid)

        @sio.on(self.user_message_evt, namespace=self.namespace)
        async def handle_message(sid: Text, data: Dict) -> None:
            output_channel = SocketIOOutput(sio, self.bot_message_evt)

            sender_id = data.get("session_id") or self._sender_from_cookie({})
            if self.session_persistence and not sender_id:
                rasa.shared.utils.io.raise_warning(
                    "A message without a valid session_id was received."
                )
                return
            if not sender_id:
                sender_id = sid

            metadata = data.get(self.metadata_key, {})
            if isinstance(metadata, Text):
                metadata = json.loads(metadata)
            message = UserMessage(
                data.get("message", ""),
                output_channel,
                sender_id,
                input_channel=self.name(),
                metadata=metadata,
            )
            await on_new_message(message)

        return socketio_webhook