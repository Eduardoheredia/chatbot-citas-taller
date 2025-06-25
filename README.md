# Chatbot de Citas para Taller

Este proyecto incluye un backend en Flask y un frontend sencillo para interactuar con un asistente Rasa.

## Configuración de la URL del Socket

El archivo `frontend/chatbot.html` utiliza la variable de plantilla `{{ socket_url }}` para establecer la URL del WebSocket con el servidor de Rasa. Esta variable se define en `backend.py` a partir de la variable de entorno `SOCKET_URL`.

Si no se define `SOCKET_URL`, se usará `http://localhost:5005` por defecto.

Al desplegar la aplicación se puede ajustar esta URL estableciendo la variable de entorno antes de ejecutar el servidor:

```bash
export SOCKET_URL="https://mi-servidor-rasa:5005"
python backend.py
```

De esta forma el frontend se conectará al WebSocket indicado.

## Identificador de sesión fijo

El frontend utiliza el número de teléfono del usuario como `session_id` cuando se conecta al WebSocket. Esto permite que el historial de conversaciones y las citas queden vinculadas de forma permanente con la cuenta del usuario. El valor se envía mediante el evento `session_request` al iniciar la conexión, por lo que el mismo identificador se reutiliza aunque el usuario cierre y vuelva a abrir el navegador.

## Persistencia de citas

Cuando un usuario agenda una cita y la confirma, el bot registra el servicio,
fecha y hora en la base de datos SQLite `usuarios.db` dentro de la tabla
`citas`. Desde esta actualización la tabla incluye una columna `estado` que
indica si la cita está `confirmada` o `cancelada`. El número de teléfono enviado
por el frontend se usa como identificador del usuario, por lo que las citas
quedan asociadas a cada cuenta y pueden consultarse posteriormente mediante la
intención `consultar_cita_activa`.

## Persistencia del historial de conversaciones

El archivo `endpoints.yml` incluye un `tracker_store` basado en SQLite que
guarda los mensajes de cada usuario en `tracker.db`. Al iniciar sesión, el
frontend consulta `/historial` para mostrar los intercambios previos y así
continuar la charla incluso después de reiniciar el servidor de Rasa.

Para evitar que un nuevo usuario vea conversaciones ajenas, `chatbot.html`
comprueba el número de teléfono almacenado en `localStorage` y lo compara con el
de la sesión activa. Si son diferentes, el historial guardado en el navegador se
elimina antes de inicializar el widget, garantizando que cada persona vea solo
sus propios mensajes.

## Consulta de citas mediante la API

El backend dispone de la ruta `/citas`, la cual devuelve todas las citas
asociadas al usuario autenticado. Esta función consulta la tabla `citas` de
`usuarios.db` utilizando el número de teléfono guardado en la sesión. Si no hay
citas registradas, la respuesta es una lista vacía.

## Canal personalizado para SocketIO

Se añadió el canal `session_socketio` definido en `channels.py`. Este canal
obtiene el identificador del usuario desde la cookie de sesión y lo usa como
`sender_id` al procesar los mensajes. De esta forma, cada persona conserva sus
citas y conversaciones aunque cambie la conexión WebSocket.