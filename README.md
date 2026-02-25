# Chatbot de Citas para Taller Mecánico

Aplicación integral para gestionar citas de un taller mecánico con **Rasa + Flask + SQLite + Frontend Web**.

El sistema permite:
- Atención conversacional para clientes.
- Registro/login de usuarios, administradores y mecánicos.
- Gestión de citas desde chatbot, panel admin y panel de mecánico.
- Persistencia de historial conversacional y citas.

---

## Tabla de contenido

- [Arquitectura del proyecto](#arquitectura-del-proyecto)
- [Funciones principales](#funciones-principales)
  - [1) Chatbot (Rasa)](#1-chatbot-rasa)
  - [2) Backend (Flask)](#2-backend-flask)
  - [3) Frontend](#3-frontend)
- [Mejoras implementadas](#mejoras-implementadas)
- [Estructura de base de datos](#estructura-de-base-de-datos)
- [Rutas HTTP disponibles](#rutas-http-disponibles)
- [Instalación y ejecución](#instalación-y-ejecución)
- [Variables de entorno](#variables-de-entorno)
- [Flujo recomendado de ejecución](#flujo-recomendado-de-ejecución)
- [Notas operativas](#notas-operativas)

---

## Arquitectura del proyecto

- **Rasa**: motor conversacional (NLU + reglas + historias + formularios + acciones personalizadas).
- **Actions Server** (`actions/actions.py`): lógica de negocio del chatbot (validación de fecha/hora, agenda, reprogramación, cancelación, historial, FAQ mecánica).
- **Flask Backend** (`backend.py`): autenticación, sesiones, administración, vista del chatbot, APIs de historial/citas y panel de mecánicos.
- **Canal SocketIO personalizado** (`channels.py`): mantiene el identificador de sesión de usuario para continuidad conversacional.
- **SQLite** (`usuarios.db` + `tracker.db`): persistencia de usuarios, mecánicos, citas y eventos conversacionales de Rasa.

---

## Funciones principales

## 1) Chatbot (Rasa)

### Funcionalidades conversacionales
- Saludo inicial automático por sesión (`action_session_start`).
- Fallback personalizado cuando no entiende una consulta.
- Consulta de servicios del taller.
- Agendamiento guiado por formulario (`agendar_cita_form`).
- Reprogramación de cita activa (`reprogramar_cita_form`).
- Cancelación de la próxima cita activa del usuario.
- Consulta de cita activa y consulta de historial de citas.
- Respuestas de preguntas frecuentes de mecánica.

### Validaciones inteligentes de fecha y hora
- Interpreta múltiples formatos de hora en español:
  - `10`, `10:00`, `10 am`, `2 pm`, `dos y media`, `cuarto para las 3`, etc.
- Soporta normalización de texto con acentos y expresiones coloquiales.
- Restringe la agenda a horarios permitidos del taller:
  - `08:00`, `10:00`, `12:00`, `14:00`, `16:00`, `18:00`.
- Evita colisiones de horario al confirmar o reprogramar.
- Muestra horarios disponibles en formato tabla para mejor lectura en webchat.

### Intenciones principales configuradas
- `solicitar_cita`, `reprogramar_cita`, `cancelar_cita`
- `consultar_cita_activa`, `consultar_historial_citas`
- `consultar_servicios`, `consultar_horarios_disponibles`
- `consulta_mecanica`, `faq_duracion_servicios`
- `saludo`, `agradecer`, `despedirse`, `confirmar`, `negar`

---

## 2) Backend (Flask)

### Autenticación y roles
- Registro de clientes con validaciones (teléfono boliviano de 8 dígitos, contraseña mínima).
- Inicio de sesión para:
  - Cliente
  - Administrador
  - Mecánico
- Gestión de sesión con `SECRET_KEY` y control de acceso por rol.

### Panel de administración
- CRUD de usuarios.
- CRUD de mecánicos.
- CRUD de citas.
- Restricciones de seguridad:
  - evita eliminar el admin base,
  - evita dejar el sistema sin administradores,
  - evita quitar privilegios al propio admin en sesión.
- Calendario de disponibilidad y ocupación para visualizar agenda general.

### Panel de mecánico
- Visualización de citas asignadas.
- Cambio de estado de citas (por ejemplo, en progreso/completada según flujo).
- Vista centrada en la operación diaria del mecánico.

### APIs auxiliares
- `GET /historial`: devuelve eventos de conversación (usuario/bot) desde tracker de Rasa.
- `GET /citas`: devuelve citas asociadas al usuario autenticado.

---

## 3) Frontend

- Páginas HTML para:
  - Inicio,
  - Login/acceso,
  - Chatbot,
  - Administración,
  - Panel de mecánico.
- Integración con widget webchat de Rasa en `frontend/chatbot.html`.
- Uso de `socket_url` para conectar dinámicamente a Rasa por entorno.
- Limpieza/aislamiento de historial local cuando cambia el usuario autenticado.

---

## Mejoras implementadas

- **Persistencia completa de citas** con estados controlados:
  - `confirmada`, `reprogramada`, `en progreso`, `cancelada`, `completada`.
- **Control de conflictos de agenda** tanto en chatbot como en panel admin.
- **Normalización robusta de horas en español** con soporte de expresiones naturales.
- **Canal SocketIO con continuidad de identidad** para mantener el historial por usuario.
- **Creación y migración defensiva de esquema SQLite** para compatibilidad con versiones previas.
- **Administrador y mecánico por defecto** inicializados automáticamente para arranque rápido.
- **Consulta de disponibilidad en calendario** para facilitar operación y planificación.

---

## Estructura de base de datos

### Tabla `usuarios`
- `id_usuario` (PK)
- `telefono` (único)
- `contrasena` (hash SHA-256)
- `es_admin` (0/1)

### Tabla `mecanicos`
- `id_mecanico` (PK)
- `nombre`
- `telefono` (único)
- `contrasena` (hash SHA-256)

### Tabla `citas`
- `id_citas` (PK)
- `id_usuario` (FK -> usuarios)
- `servicio`
- `fecha`
- `hora`
- `estado`
- `id_mecanico` (FK -> mecanicos)

### Tabla `estados_cita`
- catálogo de estados válidos para operación del sistema.

---

## Rutas HTTP disponibles

### Públicas / acceso
- `GET /` → pantalla principal
- `GET /acceso` → login
- `POST /registro` → crear usuario
- `POST /login` → autenticación

### Cliente autenticado
- `GET /chatbot` → interfaz chatbot
- `GET /historial` → historial de conversación
- `GET /citas` → citas del usuario
- `GET /logout` → cerrar sesión

### Administrador
- `GET /admin`
- `GET /admin/calendario`
- `POST /admin/agregar_usuario`
- `POST /admin/actualizar_usuario/<id_usuario>`
- `POST /admin/eliminar_usuario/<id_usuario>`
- `POST /admin/agregar_mecanico`
- `POST /admin/actualizar_mecanico/<id_mecanico>`
- `POST /admin/eliminar_mecanico/<id_mecanico>`
- `POST /admin/agregar_cita`
- `POST /admin/actualizar_cita/<id_cita>`
- `POST /admin/eliminar_cita/<id_cita>`

### Mecánico
- `GET /mecanico`
- `POST /mecanico/cita/<id_cita>/estado`

---

## Instalación y ejecución

1. Crear entorno virtual:

```bash
python3 -m venv venv
source venv/bin/activate
```

2. Instalar dependencias:

```bash
pip install -r requirements.txt
```

3. Definir variables mínimas y ejecutar backend:

```bash
export SECRET_KEY="una-clave-segura"
python backend.py
```

4. En otra terminal, entrenar y levantar Rasa:

```bash
rasa train
rasa run actions
rasa run -m models --enable-api --cors "*" --credentials credentials.yml
```

---

## Variables de entorno

### Obligatorias
- `SECRET_KEY`: clave de sesión de Flask.

### Recomendadas
- `RASA_URL` (default `http://localhost:5005`): URL base de Rasa para consulta de tracker.
- `SOCKET_URL` (default `http://localhost:5005`): URL usada por el frontend para webchat/socket.
- `SOCKET_CORS` (default `*`): orígenes permitidos del canal socket.
- `ADMIN_PHONE` (default `99999999`): teléfono del admin inicial.
- `ADMIN_PASS` (default `admin123`): contraseña del admin inicial.
- `MECANICO_PASS` (default `123456`): contraseña del mecánico inicial.

---

## Flujo recomendado de ejecución

1. Arrancar backend Flask.
2. Arrancar `rasa run actions`.
3. Arrancar `rasa run` con `credentials.yml`.
4. Ingresar por `/acceso` y probar:
   - registro/login cliente,
   - agendamiento por chatbot,
   - gestión administrativa,
   - actualización de estado por mecánico.

---

## Notas operativas

- El proyecto utiliza SQLite para facilitar desarrollo local.
- Si cambias de entorno (local, staging, producción), revisa `SOCKET_URL`, `RASA_URL` y CORS.
- Para trazabilidad conversacional persistente, mantener habilitado el `tracker_store` en `endpoints.yml`.
