# Chatbot de Citas para Taller

Este proyecto integra Rasa, Flask, SQLite y un frontend web responsive para ofrecer una experiencia completa de agendamiento y gestión de citas en un taller mecánico.

## Contenido

- [Instalación](#instalación)
- [Funcionalidades del chatbot](#funcionalidades-del-chatbot)
- [Características del proyecto](#características-del-proyecto)
- [Configuración de la URL del Socket](#configuración-de-la-url-del-socket)
- [Identificador de sesión fijo](#identificador-de-sesión-fijo)
- [Persistencia de citas](#persistencia-de-citas)
- [Persistencia del historial de conversaciones](#persistencia-del-historial-de-conversaciones)
- [Consulta de citas mediante la API](#consulta-de-citas-mediante-la-api)
- [Canal personalizado para SocketIO](#canal-personalizado-para-socketio)
- [Advertencia de SQLAlchemy](#advertencia-de-sqlalchemy)

## Instalación

1. Clona este repositorio y crea un entorno virtual:

```bash
python3 -m venv venv
source venv/bin/activate
```

2. Instala las dependencias necesarias:

```bash
pip install -r requirements.txt
```

3. Define la variable `SECRET_KEY` y ejecuta el backend:

```bash
export SECRET_KEY="alguna-clave-secreta"
python backend.py
```

4. En otra terminal inicia Rasa y sus acciones personalizadas:

```bash
rasa train
rasa run actions &
rasa run -m models --enable-api --cors "*" --credentials credentials.yml
```

## Funcionalidades del chatbot

- **Asistencia conversacional en español**: El bot inicia con saludos, despedidas y mensajes de agradecimiento personalizados para generar cercanía con el usuario.【F:domain.yml†L24-L55】
- **Información de servicios y horarios**: Explica qué servicios ofrece el taller, la duración aproximada de cada uno y el horario de atención antes de reservar.【F:domain.yml†L56-L94】
- **Agendamiento guiado de citas**: Utiliza formularios en Rasa para solicitar servicio, fecha y hora; valida servicios conocidos, interpreta fechas en lenguaje natural, convierte expresiones horarias en español y evita choques de agenda antes de confirmar la cita.【F:actions/actions.py†L495-L590】【F:actions/actions.py†L70-L169】
- **Reprogramación asistida**: Ofrece horarios alternativos para la nueva cita, valida que el formato de fecha y hora sea correcto y actualiza la cita solo si el espacio está disponible.【F:actions/actions.py†L370-L494】
- **Cancelación segura**: Permite cancelar la próxima cita activa del usuario, notificando el resultado y limpiando los datos del formulario para evitar reenvíos accidentales.【F:actions/actions.py†L591-L630】
- **Consulta de citas**: Responde con la próxima cita confirmada o reprogramada y puede listar el historial de servicios completados para que el cliente tenga seguimiento de sus visitas anteriores.【F:actions/actions.py†L632-L720】
- **Preguntas frecuentes mecánicas**: Contesta dudas comunes sobre mantenimiento, problemas mecánicos y recomendaciones básicas, escalando la consulta cuando es necesario.【F:actions/actions.py†L721-L760】
- **Fallback y control de sesión**: Saluda automáticamente al iniciar cada sesión, maneja frases no reconocidas con mensajes claros y mantiene el contexto con un `session_id` persistente ligado al número del cliente.【F:domain.yml†L95-L118】【F:actions/actions.py†L320-L358】

## Características del proyecto

- **Backend en Flask**: Proporciona registro y autenticación de usuarios y mecánicos, gestiona sesiones seguras con cookies y ofrece endpoints para historial y citas ligadas al usuario autenticado.【F:backend.py†L1-L207】【F:backend.py†L400-L478】
- **Panel administrativo**: Usuarios administradores pueden crear, editar o eliminar clientes, mecánicos y citas desde una interfaz HTML protegida por sesión.【F:backend.py†L208-L389】【F:frontend/admin.html†L1-L200】
- **Panel para mecánicos**: Cada mecánico autenticado visualiza su agenda diaria y los datos de contacto de los clientes asignados.【F:backend.py†L480-L575】【F:frontend/mecanico_panel.html†L1-L200】
- **Frontend web responsivo**: La vista del chatbot muestra el historial conversacional, las citas vigentes y un widget incrustado de Rasa Webchat que se conecta automáticamente al servidor de Rasa utilizando el identificador del usuario.【F:frontend/chatbot.html†L1-L208】
- **Persistencia centralizada**: Una base de datos SQLite única mantiene usuarios, mecánicos y citas. Tanto el backend como las acciones personalizadas de Rasa comparten el mismo archivo para garantizar consistencia.【F:backend.py†L24-L126】【F:actions/actions.py†L20-L118】
- **Integración con Rasa**: Las acciones personalizadas consultan y actualizan la base de datos, generan tablas con horarios disponibles y aplican lógica de negocio (validación de fechas, reasignación de slots, etc.).【F:actions/actions.py†L320-L630】
- **Historial conversacional**: Se consulta directamente el tracker de Rasa para mostrar los mensajes previos en el panel lateral y reanudar conversaciones pendientes.【F:backend.py†L28-L74】【F:frontend/chatbot.html†L180-L238】
- **API REST ligera**: Endpoints JSON permiten a otros componentes recuperar el historial y las citas del usuario autenticado, facilitando integraciones adicionales.【F:backend.py†L576-L610】

## Configuración de la URL del Socket

El archivo `frontend/chatbot.html` utiliza la variable de plantilla `{{ socket_url }}` para establecer la URL del WebSocket con el servidor de Rasa. Esta variable se define en `backend.py` a partir de la variable de entorno `SOCKET_URL`.

Si no se define `SOCKET_URL`, se usará `http://localhost:5005` por defecto.

Al desplegar la aplicación se puede ajustar esta URL estableciendo la variable de entorno antes de ejecutar el servidor:

```bash
export SOCKET_URL="https://mi-servidor-rasa:5005"
python backend.py
```

De esta forma el frontend se conectará al WebSocket indicado.

Si el navegador no recibe mensajes del bot, asegúrate de que el origen esté
autorizado en el canal SocketIO. Por defecto `channels.py` permite cualquier
origen usando la variable de entorno `SOCKET_CORS` (valor `"*"`). Puedes limitar
los dominios permitidos especificando una lista separada por comas:

```bash
export SOCKET_CORS="http://localhost:8000"
```

Luego inicia Rasa con:

```bash
rasa run -m models --enable-api --cors "*" --credentials credentials.yml
```


## Identificador de sesión fijo

El frontend utiliza el número de teléfono del usuario como `session_id` cuando se conecta al WebSocket. Esto permite que el historial de conversaciones y las citas queden vinculadas de forma permanente con la cuenta del usuario. El valor se envía mediante el evento `session_request` al iniciar la conexión, por lo que el mismo identificador se reutiliza aunque el usuario cierre y vuelva a abrir el navegador.

## Persistencia de citas

Cuando un usuario agenda una cita y la confirma, el bot registra el servicio,
fecha y hora en la base de datos SQLite `usuarios.db` dentro de la tabla
`citas`. Esta tabla ahora tiene una columna `estado` que
usa un *check constraint* para permitir solo los valores `confirmada`,
`reprogramada`, `cancelada` y `completada`.
El id_usuario enviado
por el frontend se usa como identificador del usuario, por lo que las citas
quedan asociadas a cada cuenta y pueden consultarse posteriormente mediante la
intención `consultar_cita_activa`.

## Persistencia del historial de conversaciones

El archivo `endpoints.yml` incluye un `tracker_store` basado en SQLite que
guarda los mensajes de cada usuario en `tracker.db`. Al iniciar sesión, el
frontend consulta `/historial` para mostrar los intercambios previos y así
continuar la charla incluso después de reiniciar el servidor de Rasa.

Para evitar que un nuevo usuario vea conversaciones ajenas, `chatbot.html`
comprueba el id_usuario en `localStorage` y lo compara con el
de la sesión activa. Si son diferentes, el historial guardado en el navegador se
elimina antes de inicializar el widget, garantizando que cada persona vea solo
sus propios mensajes.

## Consulta de citas mediante la API

El backend dispone de la ruta `/citas`, la cual devuelve todas las citas
asociadas al usuario autenticado. Esta función consulta la tabla `citas` de
`usuarios.db` id_usuario guardado en la sesión. Si no hay
citas registradas, la respuesta es una lista vacía.

## Canal personalizado para SocketIO

Se añadió el canal `session_socketio` definido en `channels.py`. Este canal
obtiene el identificador del usuario desde la cookie de sesión y lo usa como
`sender_id` al procesar los mensajes. De esta forma, cada persona conserva sus
citas y conversaciones aunque cambie la conexión WebSocket.

## Advertencia de SQLAlchemy

Al ejecutar el servidor de Rasa es posible que aparezca el mensaje:

```
MovedIn20Warning: Deprecated API features detected! ...
```