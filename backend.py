from flask import Flask, render_template, request, jsonify, redirect, url_for, session
import requests
from flask_cors import CORS
import sqlite3
import hashlib
import os

app = Flask(
    __name__,
    template_folder="frontend",  # aquí están tus HTML
    static_folder="frontend"     # y tus assets estáticos
)
app.secret_key = os.environ.get("SECRET_KEY", "poner_un_valor_seguro")
CORS(app)

DB_PATH = "usuarios.db"


def obtener_historial(telefono: str):
    """Get conversation history for a user from the Rasa server."""
    rasa_url = os.environ.get("RASA_URL", "http://localhost:5005")
    try:
        resp = requests.get(
            f"{rasa_url}/conversations/{telefono}/tracker",
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
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS usuarios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telefono TEXT UNIQUE NOT NULL,
                contrasena TEXT NOT NULL
            )
        ''')
        conn.commit()

def obtener_citas(telefono: str):
    """Return all appointments associated with a user."""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT servicio, fecha, hora, estado FROM citas WHERE telefono = ? ORDER BY fecha ASC, hora ASC",
                (telefono,),
            )
            rows = cursor.fetchall()
    except Exception:
        rows = []
    return [
        {
            "servicio": s,
            "fecha": f,
            "hora": h,
            "estado": e,
        }
        for s, f, h, e in rows
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
        return jsonify({"error": "Faltan datos"}), 400

    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO usuarios (telefono, contrasena) VALUES (?, ?)",
                (telefono, hash_contrasena(contrasena))
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
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM usuarios WHERE telefono = ? AND contrasena = ?",
            (telefono, hash_contrasena(contrasena))
        )
        usuario = cursor.fetchone()
    if usuario:
        session["telefono"] = telefono
        return redirect(url_for("chatbot_view"))  # 302 Redirect
    else:
        return jsonify({"error": "Credenciales incorrectas"}), 401

@app.route("/chatbot")
def chatbot_view():
    """Renderiza la interfaz del chatbot con la información del usuario."""
    if "telefono" not in session:
        return redirect(url_for("index"))

    telefono = session["telefono"]
    socket_url = os.environ.get("SOCKET_URL", "http://localhost:5005")

    # Enviamos el número de teléfono al frontend para que sea utilizado
    # como identificador de sesión al conectar con el WebSocket de Rasa.
    return render_template(
        "chatbot.html",
        telefono=telefono,
        socket_url=socket_url,
    )


@app.route("/logout")
def logout():
    session.pop("telefono", None)
    return redirect(url_for("index"))


@app.route("/historial")
def historial():
    if "telefono" not in session:
        return jsonify([])
    telefono = session["telefono"]
    return jsonify(obtener_historial(telefono))


@app.route("/citas")
def citas():
    """Return all appointments for the authenticated user."""
    if "telefono" not in session:
        return jsonify([])
    telefono = session["telefono"]
    return jsonify(obtener_citas(telefono))

if __name__ == "__main__":
    crear_bd()
    app.run(debug=True, port=8000)