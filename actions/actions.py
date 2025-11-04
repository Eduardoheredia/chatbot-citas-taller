from typing import Any, Text, Dict, List, Optional
from datetime import datetime, time, timedelta
from dateparser import parse
from pytz import timezone
import logging
import sqlite3
import os
import re
import unicodedata
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

PM_INDICATORS = {
    "pm",
    "p m",
    "p. m",
    "tarde",
    "de la tarde",
    "de la noche",
    "noche",
}

AM_INDICATORS = {
    "am",
    "a m",
    "a. m",
    "mañana",
    "de la mañana",
    "madrugada",
    "de la madrugada",
}

NUMERIC_WORDS = {
    "cero": 0,
    "un": 1,
    "uno": 1,
    "una": 1,
    "dos": 2,
    "tres": 3,
    "cuatro": 4,
    "cinco": 5,
    "seis": 6,
    "siete": 7,
    "ocho": 8,
    "nueve": 9,
    "diez": 10,
    "once": 11,
    "doce": 12,
    "trece": 13,
    "catorce": 14,
    "quince": 15,
    "dieciseis": 16,
    "dieciséis": 16,
    "diecisiete": 17,
    "dieciocho": 18,
}


def _strip_accents(value: Text) -> Text:
    return "".join(
        char
        for char in unicodedata.normalize("NFD", value)
        if unicodedata.category(char) != "Mn"
    )


def _texto_a_numero(token: Text) -> Optional[int]:
    token = _strip_accents(token.lower())
    return NUMERIC_WORDS.get(token)


def _detectar_periodo(texto: Text) -> Dict[str, bool]:
    texto_normalizado = texto.lower()
    compacto = re.sub(r"[\s\.]", "", texto_normalizado)
    indicadores_pm = any(ind in texto_normalizado for ind in PM_INDICATORS) or "pm" in compacto
    indicadores_am = any(ind in texto_normalizado for ind in AM_INDICATORS) or "am" in compacto
    return {"pm": indicadores_pm, "am": indicadores_am}


def _aplicar_periodo(base_hour: int, minute: int, texto: Text) -> time:
    periodo = _detectar_periodo(texto)
    hour = base_hour % 24
    if periodo["pm"]:
        if hour < 12:
            hour = (hour + 12) % 24
    elif periodo["am"]:
        if hour == 12:
            hour = 0
    else:
        if hour < 8 and hour + 12 <= 23:
            hour += 12
    return time(hour, minute)


def _replace_text_numbers(texto: Text) -> Text:
    def reemplazar(match: re.Match) -> Text:
        palabra = match.group(0)
        numero = _texto_a_numero(palabra)
        if numero is not None:
            return str(numero)
        return palabra

    return re.sub(r"\b[\wáéíóúñ]+\b", reemplazar, texto)


def parse_hora_es(value: Optional[Text]) -> Optional[time]:
    if not value:
        return None

    texto = value.strip().lower()
    if not texto:
        return None

    texto = texto.replace("\u200b", "")
    texto = texto.replace("hrs", "")
    texto = texto.replace("horas", "")
    texto = texto.replace("hora", "")
    texto = texto.replace("hs", "")
    texto = re.sub(r"(\d{1,2})\s*h\s*(\d{2})", r"\1:\2", texto)
    texto = re.sub(r"(\d{1,2})\s*h\b", r"\1", texto)
    texto = texto.replace("p.m.", " pm ")
    texto = texto.replace("a.m.", " am ")
    texto = texto.replace("p.m", " pm ")
    texto = texto.replace("a.m", " am ")
    texto = re.sub(r"[\.\,]", " ", texto)
    texto = re.sub(r"\s+", " ", texto).strip()

    if not texto:
        return None

    texto_sin_acentos = _strip_accents(texto)

    if "medianoche" in texto_sin_acentos or "media noche" in texto_sin_acentos:
        return time(0, 0)
    if "mediodia" in texto_sin_acentos or "medio dia" in texto_sin_acentos:
        return time(12, 0)

    match = re.search(r"cuarto\s+para\s+las?\s+([\wáéíóúñ]+)", texto)
    if match:
        objetivo = match.group(1)
        numero = _texto_a_numero(objetivo) or (int(objetivo) if objetivo.isdigit() else None)
        if numero is not None:
            base_hour = (numero - 1) % 24
            return _aplicar_periodo(base_hour, 45, texto)

    match = re.search(r"([\wáéíóúñ]+)\s+y\s+media", texto)
    if match:
        numero = _texto_a_numero(match.group(1))
        if numero is None and match.group(1).isdigit():
            numero = int(match.group(1))
        if numero is not None:
            return _aplicar_periodo(numero, 30, texto)

    match = re.search(r"([\wáéíóúñ]+)\s+y\s+cuarto", texto)
    if match:
        numero = _texto_a_numero(match.group(1))
        if numero is None and match.group(1).isdigit():
            numero = int(match.group(1))
        if numero is not None:
            return _aplicar_periodo(numero, 15, texto)

    reemplazado = _replace_text_numbers(texto)
    match = re.search(r"(\d{1,2})(?:[:](\d{1,2}))?", reemplazado)
    if match:
        hour = int(match.group(1))
        minute = int(match.group(2)) if match.group(2) else 0
        if "y media" in texto:
            minute = 30
        elif "y cuarto" in texto:
            minute = 15
        if minute >= 60:
            return None
        return _aplicar_periodo(hour, minute, texto)

    try:
        parsed = parse(
            value,
            languages=["es"],
            settings={
                "TIMEZONE": TZ.zone,
                "RETURN_AS_TIMEZONE_AWARE": False,
            },
        )
        if parsed:
            return _aplicar_periodo(parsed.hour, parsed.minute, texto)
    except Exception:
        return None

    return None

# Reuse la misma base de datos que utiliza el backend para almacenar
# usuarios. Aquí agregamos una tabla simple para las citas de cada
# usuario. La columna "id_usuario" actúa como identificador del cliente
# ya que el frontend envía el ID de usuario como `sender` al conectarse
# al socket de Rasa.
DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "usuarios.db")

def _init_db() -> None:
    """Asegúrese de que la tabla de citas exista con las columnas adecuadas."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS citas (
                id_citas TEXT PRIMARY KEY,
                id_usuario TEXT NOT NULL,
                servicio TEXT NOT NULL,
                fecha TEXT NOT NULL,
                hora TEXT NOT NULL,
                estado TEXT NOT NULL CHECK (
                    estado IN ('confirmada','reprogramada','cancelada','completada')
                ),
                id_mecanico TEXT,
                FOREIGN KEY(id_usuario) REFERENCES usuarios(id_usuario),
                FOREIGN KEY(id_mecanico) REFERENCES mecanicos(id_mecanico)
            )
        ''')
        # Add the column id_mecanico if the table already existed
        cursor.execute("PRAGMA table_info(citas)")
        cols = [c[1] for c in cursor.fetchall()]
        if "id_mecanico" not in cols:
            cursor.execute(
                "ALTER TABLE citas ADD COLUMN id_mecanico TEXT REFERENCES mecanicos(id_mecanico)"
            )
        conn.commit()


# Create the table on module import so actions can write de inmediato
_init_db()


def obtener_horarios_disponibles(fecha: Text) -> List[Text]:
    """Return available 2-hour time slots for the given date."""
    ocupados: set = set()
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            cursor = conn.cursor()
            cursor.execute(
                "SELECT hora FROM citas WHERE fecha = ? AND estado IN ('confirmada','reprogramada')",
                (fecha,),
            )
            ocupados = {row[0] for row in cursor.fetchall()}
    except Exception as exc:
        logger.error(f"Error consultando horarios: {exc}")

    horarios: List[Text] = []
    inicio = datetime.strptime("08:00", "%H:%M")
    fin = datetime.strptime("18:00", "%H:%M")
    actual = inicio
    while actual <= fin:
        hora_str = actual.strftime("%H:%M")
        if hora_str not in ocupados:
            horarios.append(hora_str)
        actual += timedelta(hours=2)
    return horarios


def tabla_horarios(horarios: List[Text], html: bool = False) -> Text:
    """Return the available times formatted either as plain text or Markdown.

    When ``html`` is ``True`` a Markdown table is generated so that the
    webchat renders a table instead of showing raw HTML tags. If no horarios
    are provided a short message is returned.
    """
    if not horarios:
        return "No hay horarios disponibles para ese día."

    if html:
        filas = "\n".join(f"| {h} |" for h in horarios)
        return "| Horario disponible |\n| --- |\n" + filas

    return ", ".join(horarios)


def _get_horarios_disponibles(fecha: Text, servicio: Optional[Text] = None) -> List[Text]:
    """Wrapper to reuse the existing helper for fetching available slots."""

    return obtener_horarios_disponibles(fecha)


class ActionSessionStart(Action):
    """Greets the user once when a new session starts."""

    def name(self) -> Text:
        return "action_session_start"

    async def run(
        self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: DomainDict
    ) -> List[EventType]:
        greeted_before = any(
            event.get("event") == "bot" and event.get("name") == "utter_saludo"
            for event in tracker.events
        )

        if not greeted_before:
            dispatcher.utter_message(response="utter_saludo")

        return [SessionStarted(), ActionExecuted("action_listen")]

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
        
        from uuid import uuid4

        def generar_id_cita():
            """Return a unique identifier for a new appointment."""
            return uuid4().hex

        servicio = tracker.get_slot("servicio") or "Servicio no especificado"
        fecha = tracker.get_slot("fecha") or "Fecha no definida"
        hora = tracker.get_slot("hora") or "Hora no definida"

        # Almacenar la cita en la base de datos utilizando "id_usuario" e  
        # "id_citas" que el frontend envía como sender ID.
        # El frontend envía el id_usuario en los metadata de cada
        # mensaje como `sender`. Usamos ese valor para persistir la cita de
        # forma consistente aún cuando el session_id de Rasa cambie entre
        # conexiones.
        id_usuario = tracker.sender_id

        id_cita = generar_id_cita()
        try:
            with sqlite3.connect(DB_PATH) as conn:
                conn.execute("PRAGMA foreign_keys = ON")
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT 1 FROM citas WHERE fecha = ? AND hora = ? AND estado IN ('confirmada','reprogramada')",
                    (fecha, hora),
                )
                if cursor.fetchone():
                    dispatcher.utter_message(response="utter_hora_ocupada")
                    return []
                cursor.execute(
                     "INSERT INTO citas (id_citas, id_usuario, servicio, fecha, hora, estado) VALUES (?, ?, ?, ?, ?, ?)",
                    (id_cita, id_usuario, servicio, fecha, hora, "confirmada"),
                )
                conn.commit()
        except Exception as exc:
            logger.error(f"Error al guardar la cita: {exc}")
            dispatcher.utter_message(text="⚠️ Ocurrió un error al guardar tu cita.")
            return []

        dispatcher.utter_message(
            text=f"✅ Cita confirmada:\n{servicio}\nFecha: {fecha}\nHora: {hora}"
        )
        return [SlotSet("horarios_disponibles", None)]


class ValidateReprogramarCitaForm(FormValidationAction):
    def name(self) -> Text:
        return "validate_reprogramar_cita_form"

    async def validate_fecha(self, slot_value, dispatcher, tracker, domain):
        value = (slot_value or "").strip()
        if (
            not value
            or len(value) != 10
            or value[4] != "-"
            or value[7] != "-"
        ):
            dispatcher.utter_message(text="Formato de fecha inválido. Usa AAAA-MM-DD.")
            return {"fecha": None, "horarios_disponibles": []}

        try:
            datetime.strptime(value, "%Y-%m-%d")
        except ValueError:
            dispatcher.utter_message(text="Formato de fecha inválido. Usa AAAA-MM-DD.")
            return {"fecha": None, "horarios_disponibles": []}

        servicio = tracker.get_slot("servicio")
        horarios = _get_horarios_disponibles(value, servicio)
        if not horarios:
            dispatcher.utter_message(
                text="No hay horarios disponibles para esa fecha. Por favor elige otra."
            )
            return {"fecha": None, "horarios_disponibles": []}

        dispatcher.utter_message(text=tabla_horarios(horarios, html=True))
        return {"fecha": value, "horarios_disponibles": horarios}

    async def validate_hora(self, slot_value, dispatcher, tracker, domain):
        value = (slot_value or "").strip()
        horarios = tracker.get_slot("horarios_disponibles") or []
        if value not in horarios:
            dispatcher.utter_message(
                text="⚠️ Debes elegir una hora mostrada en la lista disponible."
            )
            if horarios:
                dispatcher.utter_message(text=tabla_horarios(horarios, html=True))
            return {"hora": None}

        return {"hora": value}


class ActionReprogramarCita(Action):
    def name(self) -> str:
        return "action_reprogramar_cita"

    def run(
        self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: DomainDict
    ) -> List[Dict[Text, Any]]:
        nueva_fecha = tracker.get_slot("fecha")
        nueva_hora = tracker.get_slot("hora")
        id_usuario = tracker.sender_id
        servicio_actual = tracker.get_slot("servicio")

        events: List[EventType] = [
            SlotSet("horarios_disponibles", None),
            SlotSet("requested_slot", None),
        ]

        if not nueva_fecha or not nueva_hora:
            dispatcher.utter_message(
                "ℹ️ Necesito la nueva fecha y hora para poder reprogramar tu cita."
            )
            return events

        row = None
        try:
            with sqlite3.connect(DB_PATH) as conn:
                conn.execute("PRAGMA foreign_keys = ON")
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT id_citas, servicio, fecha, hora
                    FROM citas
                    WHERE id_usuario = ?
                      AND estado IN ('confirmada','reprogramada')
                    ORDER BY fecha ASC, hora ASC
                    """,
                    (id_usuario,),
                )
                row = cursor.fetchone()
                if row:
                    id_cita, servicio_registrado, fecha_actual, hora_actual = row
                    if not servicio_actual:
                        servicio_actual = servicio_registrado
                    if (nueva_fecha, nueva_hora) != (fecha_actual, hora_actual):
                        cursor.execute(
                            """
                            SELECT 1 FROM citas
                            WHERE fecha = ? AND hora = ?
                              AND estado IN ('confirmada','reprogramada')
                              AND id_citas != ?
                            """,
                            (nueva_fecha, nueva_hora, id_cita),
                        )
                        if cursor.fetchone():
                            dispatcher.utter_message(response="utter_hora_ocupada")
                            return events
                    cursor.execute(
                        "UPDATE citas SET fecha = ?, hora = ?, estado = 'reprogramada' WHERE id_citas = ?",
                        (nueva_fecha, nueva_hora, id_cita),
                    )
                    conn.commit()
        except Exception as exc:
            logger.error(f"Error reprogramando cita: {exc}")
            dispatcher.utter_message(text="⚠️ Ocurrió un error al reprogramar tu cita.")
            return events

        if row:
            dispatcher.utter_message(
                response="utter_reprogramacion_exitosa",
                fecha=nueva_fecha,
                hora=nueva_hora,
            )
            if servicio_actual:
                events.append(SlotSet("servicio", servicio_actual))
            return events

        dispatcher.utter_message(response="utter_no_hay_cita_activa")
        return events

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
            parsed = parse(
                slot_value,
                settings={
                    'TIMEZONE': TZ.zone,
                    'PREFER_DATES_FROM': 'future',
                    'RELATIVE_BASE': datetime.now(TZ),
                },
            )
            if not parsed:
                raise ValueError("Formato no reconocido")
            fecha = parsed.date()
            hoy = datetime.now(TZ).date()
            if fecha < hoy:
                dispatcher.utter_message(response="utter_error_fecha")
                return {"fecha": None}
            fecha_str = fecha.isoformat()
            horarios = obtener_horarios_disponibles(fecha_str)
            tabla = tabla_horarios(horarios, html=True)
            dispatcher.utter_message(text=tabla)
            if not horarios:
                dispatcher.utter_message(
                    text="Por favor ingresa otra fecha con horarios disponibles."
                )
                return {"fecha": None, "horarios_disponibles": []}

            return {"fecha": fecha_str, "horarios_disponibles": horarios}
        except Exception as e:
            logger.error(f"Error validando fecha: {str(e)}")
            dispatcher.utter_message(response="utter_error_fecha")
            return {"fecha": None, "horarios_disponibles": []}

    async def validate_hora(self, slot_value, dispatcher, tracker, domain):
        if not slot_value:
            dispatcher.utter_message(response="utter_error_hora")
            return {"hora": None}

        hora = parse_hora_es(slot_value)
        if not hora:
            dispatcher.utter_message(response="utter_error_hora")
            return {"hora": None}

        if hora < time(8, 0) or hora > time(18, 0):
            dispatcher.utter_message(response="utter_error_hora")
            return {"hora": None}

        hora_str = hora.strftime("%H:%M")
        fecha = tracker.get_slot("fecha")
        horarios_disponibles = tracker.get_slot("horarios_disponibles") or []
        if horarios_disponibles and hora_str not in horarios_disponibles:
            dispatcher.utter_message(
                text="⚠️ Debes elegir una de las horas mostradas en la lista disponible."
            )
            dispatcher.utter_message(
                text=tabla_horarios(horarios_disponibles, html=True)
            )
            return {"hora": None}

        if fecha:
            try:
                with sqlite3.connect(DB_PATH) as conn:
                    conn.execute("PRAGMA foreign_keys = ON")
                    cursor = conn.cursor()
                    cursor.execute(
                        "SELECT 1 FROM citas WHERE fecha = ? AND hora = ? AND estado IN ('confirmada','reprogramada')",
                        (fecha, hora_str),
                    )
                    if cursor.fetchone():
                        dispatcher.utter_message(response="utter_hora_ocupada")
                        return {"hora": None}
            except Exception as exc:
                logger.error(f"Error validando hora ocupada: {exc}")

        return {"hora": hora_str}

class ActionCancelarCita(Action):
    def name(self) -> str:
        return "action_cancelar_cita"

    def run(self, dispatcher, tracker, domain):
        id_usuario = tracker.sender_id

        row = None
        try:
            with sqlite3.connect(DB_PATH) as conn:
                conn.execute("PRAGMA foreign_keys = ON")
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT id_citas, servicio, fecha, hora FROM citas
                    WHERE id_usuario = ? AND estado IN ('confirmada','reprogramada')
                    ORDER BY fecha ASC, hora ASC
                    """,
                    (id_usuario,),
                )
                row = cursor.fetchone()
                if row:
                    cursor.execute(
                        "UPDATE citas SET estado = 'cancelada' WHERE id_citas = ?",
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
        dispatcher.utter_message(response="utter_cancelar_cita")
        return [SlotSet("servicio", None), SlotSet("fecha", None), SlotSet("hora", None)]

class ActionMostrarHistorial(Action):
    """Devuelve las citas pasadas del usuario cuando se activa el
    intent `consultar_historial_citas`."""
    def name(self) -> str:
        return "action_mostrar_historial"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: DomainDict) -> List[Dict[Text, Any]]:
        id_usuario = tracker.sender_id

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
        id_usuario = tracker.sender_id

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