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
    """Inicializa la base de datos con todas las tablas necesarias."""
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
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                id_usuario TEXT NOT NULL,
                id_servicio INTEGER NOT NULL,
                id_mecanico INTEGER NOT NULL,
                fecha TEXT NOT NULL,
                hora_inicio TEXT NOT NULL,
                hora_fin TEXT NOT NULL,
                estado TEXT NOT NULL CHECK (estado IN ('confirmada','reprogramada','cancelada','completada')),
                FOREIGN KEY(id_usuario) REFERENCES usuarios(id_usuario),
                FOREIGN KEY(id_servicio) REFERENCES servicios(id),
                FOREIGN KEY(id_mecanico) REFERENCES mecanicos(id)
            )
            """
        )

        cursor.execute(
            """
            CREATE TRIGGER IF NOT EXISTS trg_solapamiento_insert
            BEFORE INSERT ON citas
            BEGIN
                SELECT CASE
                WHEN EXISTS (
                    SELECT 1 FROM citas
                    WHERE id_mecanico = NEW.id_mecanico
                      AND fecha = NEW.fecha
                      AND datetime(NEW.fecha || ' ' || NEW.hora_inicio) < datetime(fecha || ' ' || hora_fin, '+10 minutes')
                      AND datetime(NEW.fecha || ' ' || NEW.hora_fin) > datetime(fecha || ' ' || hora_inicio, '-10 minutes')
                ) THEN
                    RAISE(ABORT, 'Conflicto de horario')
                END;
            END;
            """
        )

        cursor.execute(
            """
            CREATE TRIGGER IF NOT EXISTS trg_solapamiento_update
            BEFORE UPDATE ON citas
            BEGIN
                SELECT CASE
                WHEN EXISTS (
                    SELECT 1 FROM citas
                    WHERE id_mecanico = NEW.id_mecanico
                      AND fecha = NEW.fecha
                      AND id != OLD.id
                      AND datetime(NEW.fecha || ' ' || NEW.hora_inicio) < datetime(fecha || ' ' || hora_fin, '+10 minutes')
                      AND datetime(NEW.fecha || ' ' || NEW.hora_fin) > datetime(fecha || ' ' || hora_inicio, '-10 minutes')
                ) THEN
                    RAISE(ABORT, 'Conflicto de horario')
                END;
            END;
            """
        )

        if inicial:
            cursor.execute(
                "INSERT INTO usuarios (id_usuario, telefono, contrasena, es_admin) VALUES (?,?,?,1)",
                ("admin", 99999999, hash_contrasena("admin123")),
            )
            cursor.executemany(
                "INSERT INTO servicios (nombre, duracion_min) VALUES (?, ?)",
                [
                    ("Cambio de aceite", 60),
                    ("Revisión general", 90),
                    ("Alineación", 45),
                ],
            )
        conn.commit()
        

def obtener_citas(id_usuario: str):
    """Devuelve todas las citas asociadas a un usuario."""
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
            "id_cita": cid,
            "servicio": serv,
            "mecanico": mec,
            "fecha": f,
            "hora_inicio": hi,
            "hora_fin": hf,
            "estado": e,
        }
        for cid, serv, mec, f, hi, hf, e in rows
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
        query += " AND c.fecha = ?"
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

    filtros = {"servicio": servicio or "", "fecha": fecha or "", "hora": hora or ""}
    return render_template("admin.html", usuarios=usuarios, citas=citas, filtros=filtros)


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
        cursor.execute("SELECT id_servicio FROM citas WHERE id = ?", (id_cita,))
        row = cursor.fetchone()
        if not row:
            return redirect(url_for("admin_view"))
        dur = cursor.execute(
            "SELECT duracion_min FROM servicios WHERE id = ?", (row[0],)
        ).fetchone()[0]
        from datetime import datetime, timedelta

        hi_dt = datetime.strptime(hora, "%H:%M")
        hf_dt = hi_dt + timedelta(minutes=dur)

        cursor.execute(
            "UPDATE citas SET fecha = ?, hora_inicio = ?, hora_fin = ?, estado = ? WHERE id = ?",
            (fecha, hora, hf_dt.strftime("%H:%M"), estado, id_cita),
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
        "id_cita",
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


@app.route("/admin/mecanicos", methods=["GET", "POST"])
def admin_mecanicos():
    if not session.get("es_admin"):
        return redirect(url_for("index"))

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        cursor = conn.cursor()
        if request.method == "POST":
            nombre = request.form.get("nombre")
            especialidad = request.form.get("especialidad")
            if nombre:
                cursor.execute(
                    "INSERT INTO mecanicos (nombre, especialidad) VALUES (?, ?)",
                    (nombre, especialidad),
                )
                conn.commit()
                return redirect(url_for("admin_mecanicos"))

        mecanicos = cursor.execute(
            "SELECT id, nombre, especialidad FROM mecanicos ORDER BY nombre"
        ).fetchall()

    return render_template("mecanicos.html", mecanicos=mecanicos)


@app.route("/admin/mecanicos/update/<int:mec_id>", methods=["POST"])
def update_mecanico(mec_id):
    if not session.get("es_admin"):
        return redirect(url_for("index"))
    nombre = request.form.get("nombre")
    especialidad = request.form.get("especialidad")
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE mecanicos SET nombre = ?, especialidad = ? WHERE id = ?",
            (nombre, especialidad, mec_id),
        )
        conn.commit()
    return redirect(url_for("admin_mecanicos"))


@app.route("/admin/mecanicos/delete/<int:mec_id>", methods=["POST"])
def delete_mecanico(mec_id):
    if not session.get("es_admin"):
        return redirect(url_for("index"))
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        cursor = conn.cursor()
        cursor.execute("DELETE FROM mecanicos WHERE id = ?", (mec_id,))
        conn.commit()
    return redirect(url_for("admin_mecanicos"))


@app.route("/admin/asignaciones", methods=["GET", "POST"])
def admin_asignaciones():
    if not session.get("es_admin"):
        return redirect(url_for("index"))

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        cursor = conn.cursor()

        if request.method == "POST":
            servicio_id = request.form.get("servicio_id")
            mecanico_id = request.form.get("mecanico_id")
            if servicio_id and mecanico_id:
                cursor.execute(
                    "INSERT OR IGNORE INTO servicio_mecanico (id_servicio, id_mecanico) VALUES (?, ?)",
                    (servicio_id, mecanico_id),
                )
                conn.commit()
                return redirect(url_for("admin_asignaciones"))

        servicios = cursor.execute(
            "SELECT id, nombre, duracion_min FROM servicios ORDER BY nombre"
        ).fetchall()
        mecanicos = cursor.execute(
            "SELECT id, nombre FROM mecanicos ORDER BY nombre"
        ).fetchall()
        rows = cursor.execute(
            """
            SELECT s.id, s.nombre, m.id, m.nombre
            FROM servicios s
            LEFT JOIN servicio_mecanico sm ON sm.id_servicio = s.id
            LEFT JOIN mecanicos m ON sm.id_mecanico = m.id
            ORDER BY s.nombre, m.nombre
            """
        ).fetchall()

    asign_dict = {}
    for sid, sname, mid, mname in rows:
        asign_dict.setdefault(sid, {"id_servicio": sid, "servicio": sname, "mecanicos": []})
        if mid:
            asign_dict[sid]["mecanicos"].append((mid, mname))
    asignaciones = list(asign_dict.values())

    return render_template(
        "asignaciones.html",
        servicios=servicios,
        mecanicos=mecanicos,
        asignaciones=asignaciones,
    )


@app.route("/admin/asignaciones/delete", methods=["POST"])
def delete_asignacion():
    if not session.get("es_admin"):
        return redirect(url_for("index"))
    sid = request.form.get("servicio_id")
    mid = request.form.get("mecanico_id")
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM servicio_mecanico WHERE id_servicio = ? AND id_mecanico = ?",
            (sid, mid),
        )
        conn.commit()
    return redirect(url_for("admin_asignaciones"))


@app.route("/admin/nueva_cita", methods=["GET", "POST"])
def nueva_cita():
    if not session.get("es_admin"):
        return redirect(url_for("index"))

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        cursor = conn.cursor()
        if request.method == "POST":
            id_usuario = request.form.get("id_usuario")
            servicio_id = request.form.get("servicio_id")
            mecanico_id = request.form.get("mecanico_id")
            fecha = request.form.get("fecha")
            hora_inicio = request.form.get("hora_inicio")
            dur = cursor.execute(
                "SELECT duracion_min FROM servicios WHERE id = ?",
                (servicio_id,),
            ).fetchone()[0]
            from datetime import datetime, timedelta

            hi = datetime.strptime(hora_inicio, "%H:%M")
            hf = hi + timedelta(minutes=dur)
            cursor.execute(
                """
                INSERT INTO citas (id_usuario, id_servicio, id_mecanico, fecha, hora_inicio, hora_fin, estado)
                VALUES (?,?,?,?,?,?,?)
                """,
                (
                    id_usuario,
                    servicio_id,
                    mecanico_id,
                    fecha,
                    hora_inicio,
                    hf.strftime("%H:%M"),
                    "confirmada",
                ),
            )
            conn.commit()
            return redirect(url_for("admin_view"))

        usuarios = cursor.execute(
            "SELECT id_usuario, telefono FROM usuarios"
        ).fetchall()
        servicios = cursor.execute(
            "SELECT id, nombre, duracion_min FROM servicios"
        ).fetchall()
        mecanicos = cursor.execute(
            "SELECT id, nombre FROM mecanicos ORDER BY nombre"
        ).fetchall()

    return render_template(
        "nueva_cita.html",
        usuarios=usuarios,
        servicios=servicios,
        mecanicos=mecanicos,
    )


@app.route("/disponibilidad")
def disponibilidad():
    servicio_id = request.args.get("servicio_id")
    mecanico_id = request.args.get("mecanico_id")
    fecha = request.args.get("fecha")
    if not servicio_id or not mecanico_id or not fecha:
        return jsonify([])

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        cursor = conn.cursor()
        row = cursor.execute(
            "SELECT duracion_min FROM servicios WHERE id = ?", (servicio_id,)
        ).fetchone()
        if not row:
            return jsonify([])
        dur = row[0]
        citas = cursor.execute(
            "SELECT hora_inicio, hora_fin FROM citas WHERE fecha = ? AND id_mecanico = ?",
            (fecha, mecanico_id),
        ).fetchall()

    from datetime import datetime, timedelta

    inicio = datetime.strptime("08:00", "%H:%M")
    fin = datetime.strptime("18:00", "%H:%M")
    buffer = timedelta(minutes=10)
    disponibles = []
    actual = inicio
    while actual + timedelta(minutes=dur) <= fin:
        hi = actual
        hf = hi + timedelta(minutes=dur)
        solapa = False
        for ci, cf in citas:
            ci_dt = datetime.strptime(ci, "%H:%M") - buffer
            cf_dt = datetime.strptime(cf, "%H:%M") + buffer
            if hi < cf_dt and hf > ci_dt:
                solapa = True
                break
        if not solapa:
            disponibles.append(hi.strftime("%H:%M"))
        actual += timedelta(minutes=30)

    return jsonify(disponibles)

if __name__ == "__main__":
    crear_bd()
    app.run(debug=True, port=8000)
