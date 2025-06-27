from typing import Optional, Text, Dict, Any, Callable, Awaitable
import os
import json
import logging

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
        async def session_request(sid, session_id):
            # ahora recibimos directamente el string que envía Webchat
            if not isinstance(session_id, str):
                logger.warning(f"❌ session_id no es string: {session_id}")
                return

            # Guarda el sender_id en la sesión de Socket.IO
            await sio.save_session(sid, {"sender_id": session_id})
            logger.debug(f"✨ session_request OK, sender_id: {session_id}")

        @sio.on(self.user_message_evt, namespace=self.namespace)
        async def handle_message(sid: Text, data: Dict) -> None:
            output_channel = SocketIOOutput(sio, self.bot_message_evt)

            sender_id = data.get("session_id")
            if not sender_id:
                session = await sio.get_session(sid)
                if session:
                    sender_id = session.get("sender_id")
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
