# Chatbot de Citas para Taller

Este proyecto incluye un backend en Flask y un frontend sencillo para interactuar con un asistente Rasa.

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