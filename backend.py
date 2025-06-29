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
    """Inicializa la base de datos y crea un usuario administrador."""
    inicial = not os.path.exists(DB_PATH)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        cursor = conn.cursor()
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
            CREATE TABLE IF NOT EXISTS servicios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre TEXT UNIQUE NOT NULL,
                duracion_min INTEGER NOT NULL
            )
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS mecanicos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre TEXT NOT NULL,
                especialidad TEXT
            )
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS servicio_mecanico (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                id_servicio INTEGER NOT NULL,
                id_mecanico INTEGER NOT NULL,
                FOREIGN KEY(id_servicio) REFERENCES servicios(id) ON DELETE CASCADE,
                FOREIGN KEY(id_mecanico) REFERENCES mecanicos(id) ON DELETE CASCADE,
                UNIQUE(id_servicio, id_mecanico)
            )
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS citas (
                id TEXT PRIMARY KEY,
                id_usuario TEXT NOT NULL,
                id_servicio INTEGER NOT NULL,
                id_mecanico INTEGER NOT NULL,
                fecha TEXT NOT NULL,
                hora_inicio TEXT NOT NULL,
                hora_fin TEXT NOT NULL,
                estado TEXT NOT NULL CHECK(
                    estado IN ('confirmada','reprogramada','cancelada','completada')
                ),
                FOREIGN KEY(id_usuario) REFERENCES usuarios(id_usuario) ON DELETE CASCADE,
                FOREIGN KEY(id_servicio) REFERENCES servicios(id) ON DELETE CASCADE,
                FOREIGN KEY(id_mecanico) REFERENCES mecanicos(id) ON DELETE CASCADE
            )
            """
        )

        cursor.execute(
            """
            CREATE TRIGGER IF NOT EXISTS trg_no_overlap_insert
            BEFORE INSERT ON citas
            BEGIN
                SELECT CASE WHEN EXISTS (
                    SELECT 1 FROM citas
                    WHERE id_mecanico = NEW.id_mecanico
                      AND fecha = NEW.fecha
                      AND NOT (
                        time(hora_fin, '+10 minutes') <= NEW.hora_inicio OR
                        time(NEW.hora_fin, '+10 minutes') <= hora_inicio
                    )
                ) THEN RAISE(ABORT, 'solapamiento') END;
            END;
            """
        )

        cursor.execute(
            """
            CREATE TRIGGER IF NOT EXISTS trg_no_overlap_update
            BEFORE UPDATE ON citas
            BEGIN
                SELECT CASE WHEN EXISTS (
                    SELECT 1 FROM citas
                    WHERE id != NEW.id
                      AND id_mecanico = NEW.id_mecanico
                      AND fecha = NEW.fecha
                      AND NOT (
                        time(hora_fin, '+10 minutes') <= NEW.hora_inicio OR
                        time(NEW.hora_fin, '+10 minutes') <= hora_inicio
                    )
                ) THEN RAISE(ABORT, 'solapamiento') END;
            END;
            """
        )

        if inicial:
            cursor.execute(
                "INSERT INTO usuarios (id_usuario, telefono, contrasena, es_admin) VALUES (?,?,?,1)",
                ("admin", 99999999, hash_contrasena("admin123"))
            )
            cursor.executemany(
                "INSERT INTO servicios (nombre, duracion_min) VALUES (?, ?)",
                [
                    ("Cambio de aceite", 30),
                    ("Revisión general", 60),
                    ("Alineación", 45),
                    ("Balanceo", 30),
                    ("Mantenimiento preventivo", 120),
                ],
            )
        conn.commit()
        

def obtener_citas(id_usuario: str):
    """Return all appointments associated with a user."""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT c.id, s.nombre, m.nombre, c.fecha, c.hora_inicio, c.hora_fin, c.estado
                FROM citas c
                JOIN servicios s ON c.id_servicio = s.id
                JOIN mecanicos m ON c.id_mecanico = m.id
                WHERE c.id_usuario = ?
                ORDER BY c.fecha ASC, c.hora_inicio ASC
                """,
                (id_usuario,),
            )
            rows = cursor.fetchall()
    except Exception:
        rows = []
    return [
        {
            "id_citas": cid,
            "servicio": s,
            "mecanico": m,
            "fecha": f,
            "hora": h,
            "hora_fin": hf,
            "estado": e,
        }
        for cid, s, m, f, h, hf, e in rows
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
                "INSERT INTO usuarios (id_usuario, telefono, contrasena) VALUES (?, ?, ?)",
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
            "SELECT * FROM usuarios WHERE telefono = ? AND contrasena = ?",
            (telefono, hash_contrasena(contrasena))
        )
        usuario = cursor.fetchone()
    if usuario:
        session["id_usuario"] = usuario[0]
        session["es_admin"] = bool(usuario[3])
        if session["es_admin"]:
            return redirect(url_for("admin_view"))
        return redirect(url_for("chatbot_view"))  
    else:
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


@app.route("/admin")
def admin_view():
    """Muestra y filtra las tablas de usuarios y citas."""
    if not session.get("es_admin"):
        return redirect(url_for("index"))

    servicio = request.args.get("servicio")
    fecha = request.args.get("fecha")
    hora = request.args.get("hora")

    query = (
        "SELECT c.id, c.id_usuario, s.nombre, m.nombre, c.fecha, c.hora_inicio, c.hora_fin, c.estado "
        "FROM citas c "
        "JOIN servicios s ON c.id_servicio = s.id "
        "JOIN mecanicos m ON c.id_mecanico = m.id WHERE 1=1"
    )
    params = []
    if servicio:
        query += " AND s.nombre LIKE ?"
        params.append(f"%{servicio}%")
    if fecha:
        query += " AND fecha = ?"
        params.append(fecha)
    if hora:
        query += " AND c.hora_inicio = ?"
        params.append(hora)
    query += " ORDER BY c.fecha ASC, c.hora_inicio ASC"

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        cursor = conn.cursor()
        usuarios = cursor.execute(
            "SELECT id_usuario, telefono, es_admin FROM usuarios"
        ).fetchall()
        citas = cursor.execute(query, params).fetchall()
        mecanicos = cursor.execute(
            "SELECT id, nombre, especialidad FROM mecanicos"
        ).fetchall()
        servicios = cursor.execute(
            "SELECT id, nombre FROM servicios"
        ).fetchall()
        asignaciones = cursor.execute(
            """
            SELECT s.id, m.id
            FROM servicio_mecanico sm
            JOIN servicios s ON sm.id_servicio = s.id
            JOIN mecanicos m ON sm.id_mecanico = m.id
            """
        ).fetchall()

    filtros = {"servicio": servicio or "", "fecha": fecha or "", "hora": hora or ""}
    return render_template(
        "admin.html",
        usuarios=usuarios,
        citas=citas,
        mecanicos=mecanicos,
        servicios=servicios,
        asignaciones=asignaciones,
        filtros=filtros,
    )


@app.route("/admin/update_cita", methods=["POST"])
def update_cita():
    """Permite modificar fecha, hora o estado de una cita."""
    if not session.get("es_admin"):
        return redirect(url_for("index"))

    id_cita = request.form.get("id_citas")
    fecha = request.form.get("fecha")
    hora = request.form.get("hora")
    estado = request.form.get("estado")

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        cursor = conn.cursor()
        dur = cursor.execute(
            "SELECT s.duracion_min FROM citas c JOIN servicios s ON c.id_servicio = s.id WHERE c.id = ?",
            (id_cita,),
        ).fetchone()
        duracion = dur[0] if dur else 0
        from datetime import datetime, timedelta
        hora_fin = (
            datetime.strptime(hora, "%H:%M") + timedelta(minutes=duracion)
        ).strftime("%H:%M")
        cursor.execute(
            "UPDATE citas SET fecha = ?, hora_inicio = ?, hora_fin = ?, estado = ? WHERE id = ?",
            (fecha, hora, hora_fin, estado, id_cita),
        )
        conn.commit()
    return redirect(url_for("admin_view"))


@app.route("/admin/delete_cita", methods=["POST"])
def delete_cita():
    """Elimina una cita de la base de datos."""
    if not session.get("es_admin"):
        return redirect(url_for("index"))
    id_cita = request.form.get("id_citas")
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        cursor = conn.cursor()
        cursor.execute("DELETE FROM citas WHERE id = ?", (id_cita,))
        conn.commit()
    return redirect(url_for("admin_view"))


@app.route("/admin/export_csv")
def export_csv():
    """Exporta las citas agendadas en formato CSV."""
    if not session.get("es_admin"):
        return redirect(url_for("index"))
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        cursor = conn.cursor()
        rows = cursor.execute(
            """
            SELECT c.id, c.id_usuario, s.nombre, m.nombre, c.fecha, c.hora_inicio, c.hora_fin, c.estado
            FROM citas c
            JOIN servicios s ON c.id_servicio = s.id
            JOIN mecanicos m ON c.id_mecanico = m.id
            """
        ).fetchall()
    import csv
    from io import StringIO
    si = StringIO()
    writer = csv.writer(si)
    writer.writerow([
        "id_citas",
        "id_usuario",
        "servicio",
        "mecanico",
        "fecha",
        "hora_inicio",
        "hora_fin",
        "estado",
    ])
    writer.writerows(rows)
    output = make_response(si.getvalue())
    output.headers["Content-Disposition"] = "attachment; filename=citas.csv"
    output.headers["Content-type"] = "text/csv"
    return output


@app.route("/admin/add_mecanico", methods=["POST"])
def add_mecanico():
    if not session.get("es_admin"):
        return redirect(url_for("index"))
    nombre = request.form.get("nombre")
    especialidad = request.form.get("especialidad")
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO mecanicos (nombre, especialidad) VALUES (?, ?)",
            (nombre, especialidad),
        )
        conn.commit()
    return redirect(url_for("admin_view"))


@app.route("/admin/update_mecanico", methods=["POST"])
def update_mecanico():
    if not session.get("es_admin"):
        return redirect(url_for("index"))
    mid = request.form.get("id")
    nombre = request.form.get("nombre")
    especialidad = request.form.get("especialidad")
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE mecanicos SET nombre = ?, especialidad = ? WHERE id = ?",
            (nombre, especialidad, mid),
        )
        conn.commit()
    return redirect(url_for("admin_view"))


@app.route("/admin/delete_mecanico", methods=["POST"])
def delete_mecanico():
    if not session.get("es_admin"):
        return redirect(url_for("index"))
    mid = request.form.get("id")
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        cursor = conn.cursor()
        cursor.execute("DELETE FROM mecanicos WHERE id = ?", (mid,))
        conn.commit()
    return redirect(url_for("admin_view"))


@app.route("/admin/asignar_servicios", methods=["POST"])
def asignar_servicios():
    if not session.get("es_admin"):
        return redirect(url_for("index"))
    servicio_id = request.form.get("servicio_id")
    mecanicos_sel = request.form.getlist("mecanicos")
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM servicio_mecanico WHERE id_servicio = ?",
            (servicio_id,),
        )
        for mid in mecanicos_sel:
            cursor.execute(
                "INSERT INTO servicio_mecanico (id_servicio, id_mecanico) VALUES (?, ?)",
                (servicio_id, mid),
            )
        conn.commit()
    return redirect(url_for("admin_view"))


def calcular_disponibilidad(citas, duracion):
    from datetime import datetime, timedelta
    start = datetime.strptime("08:00", "%H:%M")
    end = datetime.strptime("18:00", "%H:%M")
    delta = timedelta(minutes=duracion)
    buffer = timedelta(minutes=10)
    intervals = [
        (datetime.strptime(i, "%H:%M"), datetime.strptime(f, "%H:%M"))
        for i, f in citas
    ]
    intervals.sort()
    horarios = []
    actual = start
    for ini, fin in intervals:
        while actual + delta <= ini - buffer:
            horarios.append(actual.strftime("%H:%M"))
            actual += timedelta(minutes=30)
        if actual < fin + buffer:
            actual = fin + buffer
    while actual + delta <= end:
        horarios.append(actual.strftime("%H:%M"))
        actual += timedelta(minutes=30)
    return horarios


@app.route("/admin/disponibilidad")
def disponibilidad():
    if not session.get("es_admin"):
        return jsonify({})
    servicio_id = request.args.get("servicio_id")
    fecha = request.args.get("fecha")
    if not servicio_id or not fecha:
        return jsonify({})
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        cursor = conn.cursor()
        dur = cursor.execute(
            "SELECT duracion_min FROM servicios WHERE id = ?",
            (servicio_id,),
        ).fetchone()
        if not dur:
            return jsonify({})
        duracion = dur[0]
        mecanicos = cursor.execute(
            """
            SELECT m.id, m.nombre FROM mecanicos m
            JOIN servicio_mecanico sm ON m.id = sm.id_mecanico
            WHERE sm.id_servicio = ?
            """,
            (servicio_id,),
        ).fetchall()
        resultado = {}
        for mid, nombre in mecanicos:
            citas = cursor.execute(
                "SELECT hora_inicio, hora_fin FROM citas WHERE id_mecanico = ? AND fecha = ? ORDER BY hora_inicio",
                (mid, fecha),
            ).fetchall()
            resultado[mid] = {
                "nombre": nombre,
                "horarios": calcular_disponibilidad(citas, duracion),
            }
    return jsonify(resultado)

if __name__ == "__main__":
    crear_bd()
    app.run(debug=True, port=8000)