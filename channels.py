from typing import Optional, Text, Dict, Any, Callable, Awaitable
import os
import json
import logging

from sanic.request import Request
from sanic import response, Blueprint
from sanic.response import HTTPResponse
from rasa.core.channels.channel import UserMessage
from rasa.core.channels.socketio import (
    SocketIOInput,
    SocketIOOutput,
    SocketBlueprint,
)
import rasa.shared.utils.io
from socketio import AsyncServer

logger = logging.getLogger(__name__)

class SessionSocketIOInput(SocketIOInput):
    """Socket.IO channel that uses session_request to set sender_id."""

    @classmethod
    def name(cls) -> Text:
        return "session_socketio"

    def blueprint(
        self, on_new_message: Callable[[UserMessage], Awaitable[Any]]
    ) -> Blueprint:
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
            logger.debug(f"User {sid} connected to socketIO endpoint.")
            return True

        @sio.on("disconnect", namespace=self.namespace)
        async def disconnect(sid: Text) -> None:
            logger.debug(f"User {sid} disconnected from socketIO endpoint.")

        @sio.on("session_request", namespace=self.namespace)
        async def session_request(sid: Text, data: Dict[str, Any]) -> None:
            """Handle a new session request from the client."""

            sender = data.get("sessionId") or data.get("session_id")
            if not isinstance(sender, str) or not sender:
                logger.warning(f"Invalid sender_id received: {sender}")
                return

            await sio.save_session(sid, {"sender_id": sender})

            if self.session_persistence:
                await sio.enter_room(sid, sender)

            await sio.emit(
                "session_confirm", {"sessionId": sender}, room=sid
            )

        @sio.on(self.user_message_evt, namespace=self.namespace)
        async def handle_message(sid: Text, data: Dict) -> None:
            # Extraemos metadata si existe
            metadata = data.get(self.metadata_key, {})
            if isinstance(metadata, Text):
                metadata = json.loads(metadata)

            # Priorizamos el sender de customData
            sender_id: Optional[str] = None
            if isinstance(metadata, dict):
                sender_id = metadata.get("sender")
            # Si no vino en customData, probamos session_id
            if not sender_id:
                sender_id = data.get("session_id")
            # Si aún no lo tenemos, buscamos en la sesión guardada
            if not sender_id:
                session = await sio.get_session(sid)
                if session:
                    sender_id = session.get("sender_id")
            # Finalmente, fallback al sid
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
