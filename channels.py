from typing import Optional, Text, Dict, Any, Callable, Awaitable
import json
import logging
import os
from urllib.parse import parse_qs

from http import cookies
from urllib.parse import parse_qs

from sanic.request import Request
from sanic import response, Blueprint
from sanic.response import HTTPResponse
from rasa.core.channels.channel import UserMessage
from rasa.core.channels.socketio import (
    SocketIOInput,
    SocketIOOutput,
    SocketBlueprint,
)
from socketio import AsyncServer

logger = logging.getLogger(__name__)

class CustomSocketIOInput(SocketIOInput):
    """Canal Socket.IO personalizado que usa el ID de sesión como sender_id."""

    @classmethod
    def name(cls) -> Text:
        return "custom_socketio"  # importante para evitar conflictos

    def blueprint(
        self, on_new_message: Callable[[UserMessage], Awaitable[Any]]
    ) -> Blueprint:
        cors_raw = os.environ.get("SOCKET_CORS", "*")
        cors_items = [origin.strip() for origin in cors_raw.split(",") if origin.strip()]
        seen = set()
        cors_list = []
        for origin in cors_items:
            if origin not in seen:
                seen.add(origin)
                cors_list.append(origin)

        cors_allowed = cors_list[0] if len(cors_list) == 1 else cors_list
        sio = AsyncServer(async_mode="sanic", cors_allowed_origins=cors_allowed)

        socketio_webhook = SocketBlueprint(
            sio, self.socketio_path, "custom_socketio_webhook", __name__
        )
        self.sio = sio

        @socketio_webhook.route("/health", methods=["GET"])
        async def health(_: Request) -> HTTPResponse:
            return response.json({"status": "ok"})

        @socketio_webhook.route("/", methods=["GET", "POST"])
        async def handle_request(request: Request) -> HTTPResponse:
            result = await sio.handle_request(request)
            if isinstance(result, HTTPResponse):
                return result
            if isinstance(result, dict):
                return response.json(result)
            if result is None:
                return response.empty()
            return response.text(str(result))

        @sio.on("connect", namespace=self.namespace)
        async def connect(sid: Text, environ: Dict, auth: Optional[Dict]) -> bool:
            # 1) intentar leer de auth (solo funciona en WS handshake)
            sender = None
            if isinstance(auth, dict):
                sender = auth.get("sessionId") or auth.get("session_id") \
                        or (auth.get("customData") or {}).get("sender")
            # 2) fallback a query string (HTTP polling handshake)
            if not sender:
                qs = environ.get("QUERY_STRING", "")
                sender = parse_qs(qs).get("session_id", [None])[0]
            # 3) **cookie**: si lo anterior falla, parsear HTTP_COOKIE
            if not sender:
                cookie_header = environ.get("HTTP_COOKIE", "")
                jar = cookies.SimpleCookie()
                jar.load(cookie_header)
                morsel = jar.get("session_id")
                if morsel:
                    sender = morsel.value
            # 4) si TODO falla, usar el sid
            if not sender:
                sender = sid

            # guardar en sesión de socket.io
            await sio.save_session(sid, {"sender_id": sender})
            if self.session_persistence:
                await sio.enter_room(sid, sender)
            return True

        @sio.on("disconnect", namespace=self.namespace)
        async def disconnect(sid: Text) -> None:
            logger.debug(f"User {sid} disconnected from socketIO endpoint.")

        @sio.on("session_request", namespace=self.namespace)
        async def session_request(sid: Text, data: Dict[str, Any]) -> None:
            session = await sio.get_session(sid)
            sender = session.get("sender_id") if session else None
            if not sender:
                sender = (
                    data.get("sessionId")
                    or data.get("session_id")
                    or (data.get("customData") or {}).get("sender")
                    or sid
                )
                await sio.save_session(sid, {"sender_id": sender})
                if self.session_persistence:
                    await sio.enter_room(sid, sender)

            await sio.emit(
                "session_confirm",
                {"session_id": sender},
                room=sid,
                namespace=self.namespace,
            )

            output_channel = SocketIOOutput(sio, self.bot_message_evt)
            message = UserMessage(
                "/saludo",
                output_channel,
                sender,
                input_channel=self.name(),
            )
            await on_new_message(message)

        @sio.on(self.user_message_evt, namespace=self.namespace)
        async def handle_message(sid: Text, data: Dict) -> None:
            metadata = data.get(self.metadata_key, {})
            if isinstance(metadata, str):
                try:
                    metadata = json.loads(metadata)
                except Exception:
                    metadata = {}

            sender_id: Optional[str] = (
                metadata.get("sender") if isinstance(metadata, dict) else None
            )
            if not sender_id:
                session = await sio.get_session(sid)
                if session:
                    sender_id = session.get("sender_id")
            if not sender_id:
                sender_id = sid

            output_channel = SocketIOOutput(sio, self.bot_message_evt)
            message = UserMessage(
                data.get("message", ""),
                output_channel,
                sender_id,
                input_channel=self.name(),
                metadata=metadata,
            )
            await on_new_message(message)

        return socketio_webhook
