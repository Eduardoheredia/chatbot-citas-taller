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

## Persistencia de citas

Cuando un usuario agenda una cita y la confirma, el bot registra el servicio,
fecha y hora en la base de datos SQLite `usuarios.db` dentro de la tabla
`citas`. El número de teléfono enviado por el frontend se usa como identificador
del usuario, por lo que las citas quedan asociadas a cada cuenta y pueden
consultarse posteriormente mediante la intención `consultar_cita`.