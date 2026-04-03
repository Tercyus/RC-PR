import tkinter as tk
from tkinter import ttk, messagebox
import serial
import serial.tools.list_ports
import threading
import json
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import os
import sys
import time
import socket

# === Backend Flask ===
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, static_folder=os.path.join(BASE_DIR, "web"))
CORS(app)

@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")

puerto_serial = None
serial_obj = None  # conexión persistente
perfil_actual_nombre = None

def conectar_serial():
    global puerto_serial, serial_obj
    if not puerto_serial:
        raise RuntimeError("Puerto no configurado")

    try:
        if serial_obj and serial_obj.is_open:
            return serial_obj
        serial_obj = serial.Serial(puerto_serial, 115200, timeout=1)
        time.sleep(1.0)
        return serial_obj
    except serial.SerialException:
        serial_obj = None
        raise

def enviar_comando(comando):
    global serial_obj, puerto_serial
    try:
        if serial_obj is None or not serial_obj.is_open:
            print("[INFO] Reintentando conexión al RP-RC.")
            serial_obj = serial.Serial(puerto_serial, 115200, timeout=2)
            time.sleep(0.1)

        serial_obj.reset_input_buffer()
        serial_obj.write((comando + "\n").encode())

        # Leer línea completa con timeout de 3 segundos
        respuesta = b""
        start = time.time()
        while time.time() - start < 3:
            if serial_obj.in_waiting:
                respuesta += serial_obj.read(serial_obj.in_waiting)
                # Respuesta completa cuando termina en \n
                if respuesta.endswith(b"\n"):
                    break
            else:
                time.sleep(0.02)

        decoded = respuesta.decode(errors="ignore").strip()
        print(f"[COMANDO] {comando}\n[RESPUESTA] {decoded}")
        return decoded

    except serial.SerialException as e:
        print(f"[ERROR SERIAL] {e}")
        if serial_obj:
            try:
                serial_obj.close()
            except:
                pass
        serial_obj = None
        return "ERROR: RP-RC desconectado"

@app.route("/reconectar", methods=["POST"])
def reconectar():
    global serial_obj
    try:
        if serial_obj:
            serial_obj.close()
        serial_obj = serial.Serial(puerto_serial, 115200, timeout=1)
        time.sleep(1.0)
        return jsonify({"estado": "Reconexión exitosa"}), 200
    except:
        return jsonify({"estado": "Fallo al reconectar"}), 500

@app.route("/estado", methods=["GET"])
def estado():
    global serial_obj
    if serial_obj and serial_obj.is_open:
        return jsonify({"estado": "conectado"}), 200
    return jsonify({"estado": "desconectado"}), 200

@app.route("/set-modo", methods=["POST"])
def set_modo():
    data = request.get_json()
    modo = data.get("modo", "")
    if modo not in ["normal", "rapid", "burst", "off"]:
        return jsonify({"respuesta": "Modo no válido"}), 400
    res = enviar_comando(f"SET_MODE {modo}")
    return jsonify({"respuesta": res})

@app.route("/set_port", methods=["POST"])
def set_port():
    global puerto_serial
    data = request.get_json()
    puerto = data.get("puerto", "")
    if not puerto:
        return jsonify({"error": "Puerto no especificado"}), 400
    puerto_serial = puerto
    return jsonify({"mensaje": f"Puerto configurado: {puerto}"}), 200

@app.route("/listar_puertos", methods=["GET"])
def listar_puertos():
    puertos = [p.device for p in serial.tools.list_ports.comports()]
    return jsonify(puertos)

@app.route("/ping")
def ping():
    return "OK", 200

@app.route("/listar", methods=["GET"])
def listar_perfiles():
    res = enviar_comando("LIST")
    print(f"[DEBUG] Respuesta LIST del RP-RC:\n{res}")
    if not res or res.strip() == "":
        print("[ERROR] El RP-RC no respondió al comando LIST.")
        return jsonify([]), 500

    try:
        perfiles = json.loads(res)
        if isinstance(perfiles, list):
            return jsonify(perfiles), 200
        else:
            print("[ERROR] La respuesta no es una lista válida.")
            return jsonify([]), 500
    except json.JSONDecodeError as e:
        print(f"[ERROR] No se pudo decodificar JSON: {e}")
        print(f"[RESPUESTA RAW]: {res}")
        return jsonify([]), 500

@app.route("/activo", methods=["GET"])
def perfil_activo():
    global perfil_actual_nombre
    return jsonify({"nombre": perfil_actual_nombre or "default"})

@app.route("/guardar", methods=["POST"])
def guardar_perfil():
    perfil = request.get_json()
    res = enviar_comando("SAVE " + json.dumps(perfil))
    return jsonify({"respuesta": res})

@app.route("/activar", methods=["POST"])
def activar_perfil():
    global perfil_actual_nombre
    perfil = request.get_json()
    nombre = perfil.get("nombre", "")
    res = enviar_comando("SET " + nombre)
    if "Perfil activo" in res:
        perfil_actual_nombre = nombre
    return jsonify({"respuesta": res})

@app.route("/eliminar", methods=["POST"])
def eliminar_perfil():
    data = request.get_json()
    nombre = data.get("nombre", "")
    res = enviar_comando("DEL " + nombre)
    return jsonify({"respuesta": res})

# ✅ NUEVO: Soporte universal para Flutter -> /comando
@app.route("/comando", methods=["POST"])
def comando():
    data = request.get_json()
    cmd = data.get("cmd", "").strip()
    print("📲 Comando recibido desde Flutter:", cmd)

    if not cmd:
        return jsonify({"error": "Comando vacío"}), 400

    res = enviar_comando(cmd)
    try:
        parsed = json.loads(res)
        return jsonify(parsed), 200
    except:
        return jsonify({"respuesta": res}), 200

# === GUI tkinter ===
def run_flask():
    app.run(host="0.0.0.0", port=5000, debug=False)

def iniciar_app():
    puerto = combo.get()
    if not puerto:
        messagebox.showerror("Error", "Seleccione un puerto.")
        return
    global puerto_serial
    puerto_serial = puerto
    root.withdraw()  # Oculta la ventana
    threading.Thread(target=run_flask, daemon=True).start()

    # Ocultar consola (solo en Windows)
    if os.name == 'nt':
        import ctypes
        ctypes.windll.user32.ShowWindow(ctypes.windll.kernel32.GetConsoleWindow(), 0)

def cerrar_app(event=None):
    print("🛑 F8 presionado: cerrando servidor y puerto serial.")
    global serial_obj
    try:
        if serial_obj and serial_obj.is_open:
            serial_obj.close()
    except:
        pass
    os._exit(0)

def actualizar_puertos():
    combo['values'] = [p.device for p in serial.tools.list_ports.comports()]
    if combo['values']:
        combo.current(0)

def obtener_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "No disponible"

root = tk.Tk()
root.title("Seleccionar puerto RP-RC")
root.geometry("300x180")
root.resizable(False, False)

ip_label = tk.Label(root, text=f"IP del servidor: {obtener_ip()}:5000",
                    font=("Arial", 10, "bold"), fg="blue")
ip_label.pack(pady=(10, 0))

tk.Label(root, text="Puerto Serial:").pack(pady=6)
combo = ttk.Combobox(root, state="readonly")
combo.pack()
actualizar_puertos()

boton_frame = tk.Frame(root)
boton_frame.pack(pady=10)

ttk.Button(boton_frame, text="Actualizar", command=actualizar_puertos).pack(side="left", padx=5)
ttk.Button(boton_frame, text="Iniciar", command=iniciar_app).pack(side="left", padx=5)

root.bind("<F8>", cerrar_app)
root.mainloop()
