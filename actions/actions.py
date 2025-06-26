from typing import Any, Text, Dict, List
from datetime import datetime, time
from dateparser import parse
from pytz import timezone
import logging
import sqlite3
from rasa_sdk import Action, Tracker, FormValidationAction
from rasa_sdk.executor import CollectingDispatcher
from rasa_sdk.types import DomainDict
from rasa_sdk.events import (
    SlotSet,
    FollowupAction,
    SessionStarted,
    ActionExecuted,
    EventType,
)

logger = logging.getLogger(__name__)
TZ = timezone("America/La_Paz")

# Reuse la misma base de datos que utiliza el backend para almacenar
# usuarios. Aquí agregamos una tabla simple para las citas de cada
# usuario. La columna "id_usuario" actúa como identificador del cliente
# ya que el frontend envía el ID de usuario como `sender` al conectarse
# al socket de Rasa.
DB_PATH = "usuarios.db"

def _init_db() -> None:
    """Asegúrese de que la tabla de citas exista con las columnas adecuadas."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS citas (
                id TEXT PRIMARY KEY,
                id_usuario TEXT NOT NULL,
                servicio TEXT NOT NULL,
                fecha TEXT NOT NULL,
                hora TEXT NOT NULL,
                estado TEXT NOT NULL CHECK (
                    estado IN ('confirmada','reprogramada','cancelada','completada')
                ),
                FOREIGN KEY(id_usuario) REFERENCES usuarios(id)
            )
        ''')
        conn.commit()


# Create the table on module import so actions can write de inmediato
_init_db()

class ActionDefaultFallback(Action):
    def name(self) -> str:
        return "action_default_fallback"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: DomainDict) -> List[Dict[Text, Any]]:
        dispatcher.utter_message(text="🤖 No entendí. ¿Podrías repetirlo?")
        return []

class ActionAgendarCita(Action):
    def name(self) -> str:
        return "action_agendar_cita"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: DomainDict,
    ) -> List[Dict[Text, Any]]:
        servicio = tracker.get_slot("servicio") or "Servicio no especificado"
        fecha = tracker.get_slot("fecha") or "Fecha no definida"
        hora = tracker.get_slot("hora") or "Hora no definida"

        # Almacenar la cita en la base de datos utilizando el identificador de
        # usuario (número de teléfono) que el frontend envía como sender ID.
        # El frontend envía el número de teléfono en los metadata de cada
        # mensaje como `sender`. Usamos ese valor para persistir la cita de
        # forma consistente aún cuando el session_id de Rasa cambie entre
        # conexiones.
        id_usuario = (
            tracker.latest_message.get("metadata", {}).get("sender")
            or tracker.sender_id
        )
        try:
            with sqlite3.connect(DB_PATH) as conn:
                conn.execute("PRAGMA foreign_keys = ON")
                cursor = conn.cursor()
                cursor.execute(
                     "INSERT INTO citas (id_usuario, servicio, fecha, hora, estado) VALUES (?, ?, ?, ?, ?)",
                    (id_usuario, servicio, fecha, hora, "confirmada"),
                )
                conn.commit()
        except Exception as exc:
            logger.error(f"Error al guardar la cita: {exc}")

        dispatcher.utter_message(
            text=f"✅ Cita confirmada:\n{servicio}\nFecha: {fecha}\nHora: {hora}"
        )
        return []

class ActionReprogramarCita(Action):
    def name(self) -> str:
        return "action_reprogramar_cita"

    def run(
        self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: DomainDict
    ) -> List[Dict[Text, Any]]:
        nueva_fecha = tracker.get_slot("fecha")
        nueva_hora = tracker.get_slot("hora")
        id_usuario = (
            tracker.latest_message.get("metadata", {}).get("sender") or tracker.sender_id
        )
        row = None
        try:
            with sqlite3.connect(DB_PATH) as conn:
                conn.execute("PRAGMA foreign_keys = ON")
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT id, servicio FROM citas
                    WHERE id_usuario = ? AND estado IN ('confirmada','reprogramada')
                    ORDER BY fecha ASC, hora ASC
                    """,
                    (id_usuario,),
                )
                row = cursor.fetchone()
                if row:
                    cursor.execute(
                        "UPDATE citas SET fecha = ?, hora = ?, estado = 'reprogramada' WHERE id = ?",
                        (nueva_fecha, nueva_hora, row[0]),
                    )
                    conn.commit()
        except Exception as exc:
            logger.error(f"Error reprogramando cita: {exc}")

        if row:
            dispatcher.utter_message(
                text=f"🔄 Cita reprogramada para {nueva_fecha} a las {nueva_hora}"
            )
        else:
            dispatcher.utter_message("ℹ️ No tienes citas activas para reprogramar.")
        return []

class ValidateAgendarCitaForm(FormValidationAction):
    def name(self) -> Text:
        return "validate_agendar_cita_form"

    async def validate_servicio(self, slot_value, dispatcher, tracker, domain):
        servicios = {
            "cambio de aceite": ["cambio de aceite", "aceite", "cambio aceite", "aceite y filtro"],
            "revisión general": ["revisión general", "revisión", "general", "revision", "revisión completa", "diagnóstico general"],
            "alineación": ["alineación", "alineacion", "alinear", "alinear las llantas"],
            "balanceo": ["balanceo", "balancear"],
            "mantenimiento preventivo": ["mantenimiento preventivo", "mantenimiento", "preventivo", "50,000 km"]
        }
        if slot_value:
            servicio = slot_value.strip().lower()
            for key, variants in servicios.items():
                if any(variant in servicio for variant in variants):
                    return {"servicio": key}
        dispatcher.utter_message(response="utter_ask_servicio")
        return {"servicio": None}

    async def validate_fecha(self, slot_value, dispatcher, tracker, domain):
        try:
            parsed = parse(slot_value, settings={
                'TIMEZONE': TZ.zone,
                'PREFER_DATES_FROM': 'future',
                'RELATIVE_BASE': datetime.now(TZ)
            })
            if not parsed:
                raise ValueError("Formato no reconocido")
            fecha = parsed.date()
            hoy = datetime.now(TZ).date()
            if fecha < hoy:
                dispatcher.utter_message(response="utter_error_fecha")
                return {"fecha": None}
            return {"fecha": fecha.isoformat()}
        except Exception as e:
            logger.error(f"Error validando fecha: {str(e)}")
            dispatcher.utter_message(response="utter_error_fecha")
            return {"fecha": None}

    async def validate_hora(self, slot_value, dispatcher, tracker, domain):
        if not slot_value:
            dispatcher.utter_message(response="utter_error_hora")
            return {"hora": None}

        try:
            hora_str = ''.join(
                filter(lambda x: x.isdigit() or x == ':', slot_value)
            )
            parsed = parse(hora_str, settings={"TIMEZONE": TZ.zone})
            if not parsed:
                raise ValueError
            hora = parsed.time()
            if hora < time(8, 0) or hora > time(18, 0):
                dispatcher.utter_message(response="utter_error_hora")
                return {"hora": None}
            return {"hora": hora.strftime("%H:%M")}
        except Exception:
            dispatcher.utter_message(response="utter_error_hora")
            return {"hora": None}

class ActionCancelarCita(Action):
    def name(self) -> str:
        return "action_cancelar_cita"

    def run(self, dispatcher, tracker, domain):
        id_usuario = (
            tracker.latest_message.get("metadata", {}).get("sender")
            or tracker.sender_id
        )
        row = None
        try:
            with sqlite3.connect(DB_PATH) as conn:
                conn.execute("PRAGMA foreign_keys = ON")
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT id, servicio, fecha, hora FROM citas
                    WHERE id_usuario = ? AND estado IN ('confirmada','reprogramada')
                    ORDER BY fecha ASC, hora ASC
                    """,
                    (id_usuario,),
                )
                row = cursor.fetchone()
                if row:
                    cursor.execute(
                        "UPDATE citas SET estado = 'cancelada' WHERE id = ?",
                        (row[0],),
                    )
                    conn.commit()
        except Exception as exc:
            logger.error(f"Error cancelando cita: {exc}")

        if not row:
            dispatcher.utter_message("ℹ️ No tienes citas confirmadas para cancelar.")
            return []

        servicio, fecha, hora = row[1], row[2], row[3]
        dispatcher.utter_message(
            f"✅ Tu cita de {servicio} el {fecha} a las {hora} ha sido cancelada."
        )
        return [SlotSet("servicio", None), SlotSet("fecha", None), SlotSet("hora", None)]

class ActionMostrarHistorial(Action):
    """Devuelve las citas pasadas del usuario cuando se activa el
    intent `consultar_historial_citas`."""
    def name(self) -> str:
        return "action_mostrar_historial"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: DomainDict) -> List[Dict[Text, Any]]:
        id_usuario = (
            tracker.latest_message.get("metadata", {}).get("sender")
            or tracker.sender_id
        )
        try:
            with sqlite3.connect(DB_PATH) as conn:
                conn.execute("PRAGMA foreign_keys = ON")
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT servicio, fecha, hora FROM citas
                    WHERE id_usuario = ? AND estado IN ('confirmada','reprogramada','completada')
                    ORDER BY fecha DESC, hora DESC
                    """,
                    (id_usuario,),
                )
                rows = cursor.fetchall()
        except Exception as exc:
            logger.error(f"Error consultando historial: {exc}")
            rows = []

        ahora = datetime.now(TZ)
        citas_pasadas: List[tuple] = []
        for s, f, h in rows:
            try:
                fecha_dt = datetime.fromisoformat(f)
                hora_dt = datetime.strptime(h, "%H:%M").time()
                cita_dt = TZ.localize(datetime.combine(fecha_dt, hora_dt))
                if cita_dt < ahora:
                    citas_pasadas.append((s, f, h))
            except Exception as exc:
                logger.error(f"Error procesando cita almacenada: {exc}")

        if citas_pasadas:
            mensajes = ["\n".join([f"Servicio: {s}", f"Fecha: {f}", f"Hora: {h}"]) for s, f, h in citas_pasadas]
            texto = "\n---\n".join(mensajes)
            dispatcher.utter_message(text=f"📚 Historial de citas:\n{texto}")
        else:
            dispatcher.utter_message(text="No se encontraron citas previas.")

        return []

class ActionConsultarCita(Action):
    """Informa la próxima cita del usuario cuando se activa el
    intent `consultar_cita_activa`."""
    def name(self) -> str:
        return "action_consultar_cita"

    def run(self, dispatcher, tracker, domain):
        # Utilizar el sender_id persistente como identificador del usuario
        # Este valor coincide con el número de teléfono que el frontend envía
        # como session_id al conectarse con el bot
        id_usuario = (
            tracker.latest_message.get("metadata", {}).get("sender")
            or tracker.sender_id
        )
        try:
            with sqlite3.connect(DB_PATH) as conn:
                conn.execute("PRAGMA foreign_keys = ON")
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT servicio, fecha, hora FROM citas
                    WHERE id_usuario = ? AND estado IN ('confirmada','reprogramada')
                    ORDER BY fecha ASC, hora ASC
                    """,
                    (id_usuario,),
                )
                rows = cursor.fetchall()
        except Exception as exc:
            logger.error(f"Error consultando cita: {exc}")
            rows = []

        servicio = fecha = hora = None
        ahora = datetime.now(TZ)
        for s, f, h in rows:
            try:
                fecha_dt = datetime.fromisoformat(f)
                hora_dt = datetime.strptime(h, "%H:%M").time()
                cita_dt = TZ.localize(datetime.combine(fecha_dt, hora_dt))
                if cita_dt >= ahora:
                    servicio, fecha, hora = s, f, h
                    break
            except Exception as exc:
                logger.error(f"Error procesando cita almacenada: {exc}")

        if servicio and fecha and hora:
            dispatcher.utter_message(
                text=f"📋 Tu próxima cita:\nServicio: {servicio}\nFecha: {fecha}\nHora: {hora}"
            )
        else:
            dispatcher.utter_message(
                text="No hay citas activas en este momento."
            )
        return []

class ActionResponderConsultaMecanica(Action):
    def name(self) -> str:
        return "action_responder_consulta_mecanica"

    def run(self, dispatcher, tracker, domain):
        pregunta = tracker.latest_message.get("text", "").lower()
        respuesta = "Déjame consultarlo con un mecánico especialista."
        if "cambiar el aceite" in pregunta:
            respuesta = "El aceite del motor se debe cambiar cada 5,000 a 10,000 km o cada 6 meses, dependiendo del uso y las recomendaciones del fabricante."
        elif "no enciende" in pregunta or "no arranca" in pregunta:
            respuesta = "Las causas pueden ser: batería descargada, falla en el motor de arranque, problema con la llave o sistema de encendido. Revisa la batería y los terminales primero."
        elif "correa de distribución" in pregunta:
            respuesta = "Se recomienda cambiar la correa de distribución cada 60,000 a 100,000 km, según el fabricante."
        elif "recalienta" in pregunta:
            respuesta = "Si el motor se recalienta, apágalo de inmediato. Puede ser por bajo nivel de refrigerante, fugas, termostato defectuoso o falla en el ventilador. Revisa el nivel de agua/refrigerante."
        elif "ruido extraño" in pregunta:
            respuesta = "Un ruido extraño puede deberse a desgaste de piezas, falta de lubricación o problemas en la suspensión."
        elif "no hago el mantenimiento" in pregunta:
            respuesta = "Si no haces el mantenimiento preventivo puedes provocar fallas graves, menor vida útil y mayor costo de reparación."
        elif "vibra el volante" in pregunta:
            respuesta = "La vibración del volante suele indicar problemas de balanceo de ruedas, alineación o desgaste de neumáticos."
        elif "presión" in pregunta and "llantas" in pregunta:
            respuesta = "La presión recomendada suele estar entre 30 y 35 psi, pero lo mejor es consultar el manual o la etiqueta de la puerta del conductor."
        elif "check engine" in pregunta:
            respuesta = "Si se prende el 'check engine', acude lo antes posible al taller para un diagnóstico."
        dispatcher.utter_message(respuesta)
        return []


class ActionSessionStart(Action):
    """Inicia una nueva sesión sin limpiar los slots previos."""

    def name(self) -> str:
        return "action_session_start"

    async def run(
        self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: DomainDict
    ) -> List[EventType]:
        events: List[EventType] = [SessionStarted()]
        for slot, value in tracker.current_slot_values().items():
            events.append(SlotSet(slot, value))
        events.append(ActionExecuted("action_listen"))
        return events