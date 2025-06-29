from flask import Flask, render_template, request, jsonify, redirect, url_for, session, make_response
import requests
from flask_cors import CORS
import sqlite3
import hashlib
import os
import random
import string
from dotenv import load_dotenv

load_dotenv()

SECRET_KEY = os.environ.get("SECRET_KEY")
if not SECRET_KEY:
    raise RuntimeError("Falta la variable de entorno SECRET_KEY")

app = Flask(
    __name__,
    template_folder="frontend",  # aquí están tus HTML
    static_folder="frontend"     # y tus assets estáticos
)
app.secret_key = SECRET_KEY
CORS(app)

DB_PATH = os.path.join(os.path.dirname(__file__), "usuarios.db")

def generar_id_aleatorio(longitud=8):
    return ''.join(random.choices(string.ascii_letters + string.digits, k=longitud))

def obtener_historial(id_usuario: str):
    """Get conversation history for a user from the Rasa server."""
    rasa_url = os.environ.get("RASA_URL", "http://localhost:5005")
    try:
        resp = requests.get(
            f"{rasa_url}/conversations/{id_usuario}/tracker",
            params={"include_events": "after_restart"},
            timeout=5,
        )
        if resp.status_code != 200:
            return []
        data = resp.json()
        messages = []
        for ev in data.get("events", []):
            if ev.get("event") == "user" and ev.get("text"):
                messages.append({"sender": "user", "text": ev.get("text")})
            elif ev.get("event") == "bot" and ev.get("text"):
                messages.append({"sender": "bot", "text": ev.get("text")})
        return messages
    except Exception:
        return []

def crear_bd():
    """Ensure DB schema exists and create a default admin user."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        cursor = conn.cursor()
        # Tabla de usuarios con columna es_admin para privilegios
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS usuarios (
                id_usuario TEXT PRIMARY KEY,
                telefono INTEGER UNIQUE NOT NULL,
                contrasena TEXT NOT NULL,
                es_admin INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS mecanicos (
                id_mecanico TEXT PRIMARY KEY,
                nombre TEXT NOT NULL,
                telefono INTEGER UNIQUE NOT NULL
            )
            """
        )
    
        # Si la base ya existía sin la columna es_admin la añadimos
        cursor.execute("PRAGMA table_info(usuarios)")
        cols = [c[1] for c in cursor.fetchall()]
        if "es_admin" not in cols:
            cursor.execute(
                "ALTER TABLE usuarios ADD COLUMN es_admin INTEGER NOT NULL DEFAULT 0"
            )
            
        # Crear un usuario administrador por defecto
        admin_phone = os.environ.get("ADMIN_PHONE", "99999999")
        admin_pass = os.environ.get("ADMIN_PASS", "admin123")
        cursor.execute(
            """
            INSERT OR IGNORE INTO usuarios (id_usuario, telefono, contrasena, es_admin)
            VALUES (?, ?, ?, 1)
            """,
            ("admin", admin_phone, hash_contrasena(admin_pass)),
        )
        cursor.execute(
            """
            INSERT OR IGNORE INTO mecanicos (id_mecanico, nombre, telefono)
            VALUES ('mec1', 'Mecánico Ejemplo', '00000000')
            """
        )
        conn.commit()
        

def obtener_citas(id_usuario: str):
    """Return all appointments associated with a user."""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id_citas, servicio, fecha, hora, estado, id_mecanico FROM citas WHERE id_usuario = ? ORDER BY fecha ASC, hora ASC",
                (id_usuario,),
            )
            rows = cursor.fetchall()
    except Exception:
        rows = []
    return [
        {
            "id_citas": cid,
            "servicio": s,
            "fecha": f,
            "hora": h,
            "estado": e,
            "id_mecanico": m,
        }
        for cid, s, f, h, e, m in rows
    ]

def hash_contrasena(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/registro", methods=["POST"])
def registro():
    datos = request.get_json()
    telefono = datos.get("telefono")
    contrasena = datos.get("contrasena")

    if not telefono or not contrasena:
        return jsonify({"error": "RELLENE LOS CAMPOS"}), 400
    if not telefono:
        return jsonify({"error": "El número de teléfono es obligatorio"}), 400
    if not contrasena:
        return jsonify({"error": "La contraseña es obligatoria"}), 400
    if not telefono.isdigit() or len(telefono) != 8:
        return jsonify({"error": "El número de teléfono debe tener exactamente 8 dígitos numéricos para bolivia"}), 400
    if len(contrasena) < 6:
        return jsonify({"error": "La contraseña debe tener al menos 6 caracteres"}), 400

    
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        cursor = conn.cursor()
        intentos = 0
        while True:
            id_usuario = generar_id_aleatorio()
            cursor.execute("SELECT 1 FROM usuarios WHERE id_usuario = ?", (id_usuario,))
            if not cursor.fetchone():
                break
            intentos += 1
            if intentos > 10:
                return jsonify({"error": "No se pudo generar un ID único"}), 500

    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO usuarios (id_usuario, telefono, contrasena, es_admin) VALUES (?, ?, ?, 0)",
                (id_usuario, telefono, hash_contrasena(contrasena))
            )
            conn.commit()
        return jsonify({"mensaje": "Registro exitoso"}), 200
    except sqlite3.IntegrityError:
        return jsonify({"error": "Número ya registrado"}), 409

@app.route("/login", methods=["POST"])
def login():
    datos = request.get_json()
    telefono = datos.get("telefono")
    contrasena = datos.get("contrasena")

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id_usuario, es_admin FROM usuarios WHERE telefono = ? AND contrasena = ?",
            (telefono, hash_contrasena(contrasena))
        )
        usuario = cursor.fetchone()

    if usuario:
        # Guardamos el ID y si es administrador en la sesión
        session["id_usuario"] = usuario[0]
        session["es_admin"] = bool(usuario[1])
        # Si el usuario es admin redirigimos a su panel
        if usuario[1]:
            return redirect(url_for("admin_panel"))
        return redirect(url_for("chatbot_view"))

    return jsonify({"error": "Credenciales incorrectas"}), 401

@app.route("/chatbot")
def chatbot_view():
    """Renderiza la interfaz del chatbot con la información del usuario."""
    if "id_usuario" not in session:
        return redirect(url_for("index"))

    id_usuario = session["id_usuario"]
    socket_url = os.environ.get("SOCKET_URL", "http://localhost:5005")

    # Enviamos el id_usuario al frontend para que sea utilizado
    # como identificador de sesión al conectar con el WebSocket de Rasa.
    resp = make_response(render_template(
        "chatbot.html",
        id_usuario=id_usuario,
        socket_url=socket_url,
    ))

    resp.set_cookie("session_id", id_usuario, httponly=True, samesite="Lax")
    return resp


@app.route("/admin")
def admin_panel():
    """Muestra todas las tablas si el usuario es administrador."""
    if not session.get("es_admin"):
        return redirect(url_for("index"))

    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT id_usuario, telefono, es_admin FROM usuarios")
        usuarios = cursor.fetchall()
        cursor.execute(
            """
            SELECT c.id_citas, c.id_usuario, u.telefono, c.servicio,
                   c.fecha, c.hora, c.estado, c.id_mecanico,
                   m.nombre AS nombre_mecanico
            FROM citas AS c
            JOIN usuarios AS u ON c.id_usuario = u.id_usuario
            LEFT JOIN mecanicos AS m ON c.id_mecanico = m.id_mecanico
            """
        )
        citas = cursor.fetchall()
        cursor.execute(
            "SELECT id_mecanico, nombre, telefono FROM mecanicos"
        )
        mecanicos = cursor.fetchall()

    return render_template("admin.html", usuarios=usuarios, citas=citas, mecanicos=mecanicos)

@app.route("/admin/actualizar_cita/<id_cita>", methods=["POST"])
def actualizar_cita(id_cita):
    """Permite modificar una cita desde el panel de administración."""
    if not session.get("es_admin"):
        return redirect(url_for("index"))

    servicio = request.form.get("servicio")
    fecha = request.form.get("fecha")
    hora = request.form.get("hora")
    estado = request.form.get("estado")
    id_mecanico = request.form.get("id_mecanico")

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE citas SET servicio = ?, fecha = ?, hora = ?, estado = ?, id_mecanico = ? WHERE id_citas = ?",
            (servicio, fecha, hora, estado, id_mecanico, id_cita),
        )
        conn.commit()

    return redirect(url_for("admin_panel"))

@app.route("/admin/agregar_cita", methods=["POST"])
def agregar_cita():
    """Agregar una nueva cita desde el panel de administración."""
    if not session.get("es_admin"):
        return redirect(url_for("index"))

    id_usuario = request.form.get("id_usuario")
    servicio = request.form.get("servicio")
    fecha = request.form.get("fecha")
    hora = request.form.get("hora")
    estado = request.form.get("estado") or "confirmada"
    id_mecanico = request.form.get("id_mecanico")

    id_cita = generar_id_aleatorio()
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO citas (id_citas, id_usuario, servicio, fecha, hora, estado, id_mecanico) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (id_cita, id_usuario, servicio, fecha, hora, estado, id_mecanico),
        )
        conn.commit()

    return redirect(url_for("admin_panel"))

@app.route("/admin/eliminar_cita/<id_cita>", methods=["POST"])
def eliminar_cita(id_cita):
    """Eliminar una cita de la base de datos."""
    if not session.get("es_admin"):
        return redirect(url_for("index"))

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM citas WHERE id_citas = ?",
            (id_cita,),
        )
        conn.commit()

    return redirect(url_for("admin_panel"))

@app.route("/admin/agregar_mecanico", methods=["POST"])
def agregar_mecanico():
    """Agregar un nuevo mecánico desde el panel de administración."""
    if not session.get("es_admin"):
        return redirect(url_for("index"))

    nombre = request.form.get("nombre")
    telefono = request.form.get("telefono")
    if not nombre:
        return redirect(url_for("admin_panel"))

    id_mecanico = generar_id_aleatorio()
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO mecanicos (id_mecanico, nombre, telefono) VALUES (?, ?, ?)",
            (id_mecanico, nombre, telefono),
        )
        conn.commit()

    return redirect(url_for("admin_panel"))

@app.route("/admin/actualizar_mecanico/<id_mecanico>", methods=["POST"])
def actualizar_mecanico(id_mecanico):
    """Editar los datos de un mecánico."""
    if not session.get("es_admin"):
        return redirect(url_for("index"))

    nombre = request.form.get("nombre")
    telefono = request.form.get("telefono")
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE mecanicos SET nombre = ?, telefono = ? WHERE id_mecanico = ?",
            (nombre, telefono, id_mecanico),
        )
        conn.commit()

    return redirect(url_for("admin_panel"))

@app.route("/admin/eliminar_mecanico/<id_mecanico>", methods=["POST"])
def eliminar_mecanico(id_mecanico):
    """Eliminar un mecánico de la base de datos."""
    if not session.get("es_admin"):
        return redirect(url_for("index"))

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM mecanicos WHERE id_mecanico = ?",
            (id_mecanico,),
        )
        conn.commit()

    return redirect(url_for("admin_panel"))

@app.route("/logout")
def logout():
    session.pop("id_usuario", None)
    session.pop("es_admin", None)
    return redirect(url_for("index"))

@app.route("/historial", methods=["GET"])
def historial():
    """Return chat history for the authenticated user."""
    id_usuario = session.get("id_usuario")
    if not id_usuario:
        # If the user is not logged in, return empty history with 401 status
        return jsonify([]), 401

    history = obtener_historial(id_usuario)
    return jsonify(history)

@app.route("/citas")
def citas():
    """Devolver todas las citas del usuario autenticado."""
    if "id_usuario" not in session:
        return jsonify([])
    id_usuario = session["id_usuario"]
    return jsonify(obtener_citas(id_usuario))

if __name__ == "__main__":
    crear_bd()
    app.run(debug=True, port=8000)