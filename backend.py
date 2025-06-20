from flask import Flask, render_template, request, jsonify, redirect, url_for, session
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
    if "telefono" not in session:
        return redirect(url_for("index"))
    telefono = session["telefono"]
    socket_url = os.environ.get("SOCKET_URL", "http://localhost:5005")
    return render_template("chatbot.html", telefono=telefono, socket_url=socket_url)

if __name__ == "__main__":
    crear_bd()
    app.run(debug=True, port=8000)
