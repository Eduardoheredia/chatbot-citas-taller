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
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS usuarios (
                id_usuario TEXT PRIMARY KEY,
                telefono INTEGER UNIQUE NOT NULL,
                contrasena TEXT NOT NULL
            )
        ''')
        

def obtener_citas(id_usuario: str):
    """Return all appointments associated with a user."""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id_citas, servicio, fecha, hora, estado FROM citas WHERE id_usuario = ? ORDER BY fecha ASC, hora ASC",
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
        }
        for cid, s, f, h, e in rows
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
        return redirect(url_for("chatbot_view"))  # 302 Redirect
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