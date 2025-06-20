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