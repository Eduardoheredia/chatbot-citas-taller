from typing import Any, Text, Dict, List
from datetime import datetime, time
from dateparser import parse
from pytz import timezone
import logging

from rasa_sdk import Action, Tracker, FormValidationAction
from rasa_sdk.executor import CollectingDispatcher
from rasa_sdk.types import DomainDict
from rasa_sdk.events import SlotSet, FollowupAction

logger = logging.getLogger(__name__)
TZ = timezone("America/Mexico_City")

class ActionDefaultFallback(Action):
    def name(self) -> str:
        return "action_default_fallback"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: DomainDict) -> List[Dict[Text, Any]]:
        dispatcher.utter_message(text="🤖 No entendí. ¿Podrías repetirlo?")
        return []

class ActionAgendarCita(Action):
    def name(self) -> str:
        return "action_agendar_cita"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: DomainDict) -> List[Dict[Text, Any]]:
        servicio = tracker.get_slot("servicio") or "Servicio no especificado"
        fecha = tracker.get_slot("fecha") or "Fecha no definida"
        hora = tracker.get_slot("hora") or "Hora no definida"
        dispatcher.utter_message(
            text=f"✅ Cita confirmada:\n{servicio}\nFecha: {fecha}\nHora: {hora}"
        )
        # No reseteamos conversación aquí, solo los slots si se requiere después.
        return []

class ActionReprogramarCita(Action):
    def name(self) -> str:
        return "action_reprogramar_cita"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: DomainDict) -> List[Dict[Text, Any]]:
        dispatcher.utter_message(
            text=f"🔄 Cita reprogramada para {tracker.get_slot('fecha')} a las {tracker.get_slot('hora')}"
        )
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
        dispatcher.utter_message(text="✅ Cita cancelada exitosamente.")
        return [SlotSet("servicio", None), SlotSet("fecha", None), SlotSet("hora", None)]

class ActionConsultarCita(Action):
    def name(self) -> str:
        return "action_consultar_cita"

    def run(self, dispatcher, tracker, domain):
        servicio = tracker.get_slot("servicio")
        fecha = tracker.get_slot("fecha")
        hora = tracker.get_slot("hora")
        if servicio and fecha and hora:
            dispatcher.utter_message(
                text=f"📋 Tu próxima cita:\nServicio: {servicio}\nFecha: {fecha}\nHora: {hora}"
            )
        else:
            dispatcher.utter_message(
                text="No tienes citas programadas. ¿Quieres agendar una?"
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


       # dispatcher.utter_message(respuesta)
        #if tracker.active_loop:
            # Continuar con el formulario activo
         #   return [SlotSet("requested_slot", None), FollowupAction(tracker.active_loop)]
        #else:
            # Reiniciar para nueva conversación
         #   return [Restarted()]
        

