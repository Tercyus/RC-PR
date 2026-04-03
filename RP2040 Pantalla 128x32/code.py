import time
import random
import board
import digitalio
import usb_hid
import json
import usb_cdc
import storage
import supervisor
import adafruit_neopixel
import busio
import displayio
import terminalio
import adafruit_imageload
from adafruit_display_text import label
from adafruit_displayio_ssd1306 import SSD1306
from adafruit_hid.mouse import Mouse
import calendar
import os
import math

# ============ CONSTANTES DE CONFIGURACIÓN ============
# Los valores se leen de settings.toml; si no existen, se usan los valores por defecto
TIEMPO_A_REPOSO = float(os.getenv("TIEMPO_A_REPOSO", "3.0"))
DEBOUNCE_BOTONES = float(os.getenv("DEBOUNCE_BOTONES", "0.15"))
DELAY_RAPID_FIRE_DEFAULT = 0.01
DISPAROS_BURST_DEFAULT = 5
INTERVALO_BURST_DEFAULT = 0.03
DELAY_NORMAL_DEFAULT = 0.05
MAX_MOVIMIENTO_MOUSE = 30
MIN_MOVIMIENTO_MOUSE = 1
OLED_ADDRESS = 0x3C
OLED_WIDTH = 128
OLED_HEIGHT = 32
UTC_OFFSET = int(os.getenv("UTC_OFFSET", "-18000"))

# Constantes de precisión (configurables desde settings.toml)
USAR_GAUSSIANA = os.getenv("USAR_GAUSSIANA", "1") == "1"
SUAVIZAR_MOVIMIENTOS = os.getenv("SUAVIZAR_MOVIMIENTOS", "1") == "1"
COMPENSACION_ACUMULATIVA = os.getenv("COMPENSACION_ACUMULATIVA", "1") == "1"
PRECISION_SUB_PIXEL = os.getenv("PRECISION_SUB_PIXEL", "1") == "1"
MAX_COMPENSACION = 2.0  # Máximo de compensación acumulativa

# ============ INICIALIZACIÓN BÁSICA ============

time.sleep(0.05)

# Inicializar NeoPixel
pixel = adafruit_neopixel.NeoPixel(board.GP16, 1, brightness=0.4, auto_write=True)
pixel[0] = (0, 0, 0)

# Inicializar botones con pull-up
btn_disparo = digitalio.DigitalInOut(board.GP9)
btn_disparo.direction = digitalio.Direction.INPUT
btn_disparo.pull = digitalio.Pull.UP

btn_cambio_perfil = digitalio.DigitalInOut(board.GP3)
btn_cambio_perfil.direction = digitalio.Direction.INPUT
btn_cambio_perfil.pull = digitalio.Pull.UP

btn_cambio_modo = digitalio.DigitalInOut(board.GP8)
btn_cambio_modo.direction = digitalio.Direction.INPUT
btn_cambio_modo.pull = digitalio.Pull.UP

serial = usb_cdc.console

# Inicializar pantalla OLED
displayio.release_displays()
# Activar pull-ups internos del RP2040 antes de inicializar I2C
# (evita RuntimeError: No pull up found on SDA or SCL)
_sda = digitalio.DigitalInOut(board.GP4)
_sda.direction = digitalio.Direction.INPUT
_sda.pull = digitalio.Pull.UP
_scl = digitalio.DigitalInOut(board.GP5)
_scl.direction = digitalio.Direction.INPUT
_scl.pull = digitalio.Pull.UP
_sda.deinit()
_scl.deinit()
i2c = busio.I2C(scl=board.GP5, sda=board.GP4)
try:
    import i2cdisplaybus
    display_bus = i2cdisplaybus.I2CDisplayBus(i2c, device_address=0x3C)
except ImportError:
    display_bus = displayio.I2CDisplay(i2c, device_address=0x3C)
display = SSD1306(display_bus, width=128, height=32)
main_group = displayio.Group()
display.root_group = main_group
time.sleep(0.1)  # Pequeño delay para que la pantalla se inicialice completamente

# ============ VARIABLES DEL SISTEMA ============
conexion_flask = True
disparos_actual = 0
disparos_total = 3
disparos_totales_sesion = 0  # Estadísticas
modo_disparo = "normal"
rapid_fire_delay = DELAY_RAPID_FIRE_DEFAULT
DISPAROS_BURST = DISPAROS_BURST_DEFAULT
INTERVALO_BURST = INTERVALO_BURST_DEFAULT
delay_normal = DELAY_NORMAL_DEFAULT

ultimo_disparo = time.monotonic()
estado_pantalla = "hud"
ultimo_ping = time.monotonic()
ultima_actualizacion_reposo = time.monotonic()
TIMEOUT_CONEXION = 5.0  # segundos sin ping = desconectado
offset_tiempo = 0  # Offset para calcular hora cuando no hay RTC
texto_inicio = "RECOIL"  # Texto personalizable para pantalla de inicio

# Caché para evitar actualizaciones innecesarias de pantalla
cache_pantalla = {
    "perfil": "",
    "modo": "",
    "estado": "",
    "conexion": None,
    "disparos": (0, 0)
}

# Estados previos de botones para debounce
btn_perfil_anterior = True
btn_modo_anterior = True
btn_disparo_anterior = True


def validar_perfil(p):
    campos = ["nombre", "ajuste_x", "ajuste_y", "variacion"]
    return all(k in p for k in campos)

perfiles = []
try:
    with open("perfiles.json", "r") as f:
        cargados = json.load(f)
        perfiles = [p for p in cargados if validar_perfil(p)]
        print(f"Perfiles cargados: {len(perfiles)}")
except FileNotFoundError:
    pass
except Exception as e:
    print(f"Error cargando perfiles: {e}")

if not perfiles:
    perfiles = [{
        "nombre": "default",
        "ajuste_x": 0,
        "ajuste_y": 5,
        "variacion": 0.3,
        "color": [0, 0, 255]
    }]

perfil_actual = 0
mouse = Mouse(usb_hid.devices)

# ============ FUNCIONES DE PANTALLA OLED ============
def pantalla_inicio():
    """Muestra imagen de inicio con un arma."""
    try:
        # Cargar imagen .bmp desde almacenamiento interno
        bitmap, palette = adafruit_imageload.load("/Default.bmp", bitmap=displayio.Bitmap, palette=displayio.Palette)
        
        tile_grid = displayio.TileGrid(bitmap, pixel_shader=palette)
        group = displayio.Group()
        group.append(tile_grid)
        display.root_group = group
        
        # Esperar unos segundos antes de continuar
        time.sleep(2)
    except Exception as e:
        print("No se pudo cargar imagen de inicio:", e)
        # Si falla, mostrar texto alternativo
        for x in range(-60, 40, 2):
            g = displayio.Group()
            g.append(label.Label(terminalio.FONT, text="XgamerS", scale=3, x=x, y=18))
            display.root_group = g
            time.sleep(0.05)

def pantalla_reposo():
    """Muestra pantalla de reposo con la imagen del perfil activo o su nombre."""
    perfil = perfiles[perfil_actual]
    imagen_path = perfil.get("imagen", "")

    # Intentar cargar imagen del perfil
    if imagen_path:
        try:
            bitmap, palette = adafruit_imageload.load(
                imagen_path, bitmap=displayio.Bitmap, palette=displayio.Palette)
            tile_grid = displayio.TileGrid(bitmap, pixel_shader=palette)
            g = displayio.Group()
            g.append(tile_grid)
            perfil_nombre = perfil["nombre"]
            g.append(label.Label(terminalio.FONT, text=perfil_nombre,
                                 x=max(0, (128 - len(perfil_nombre) * 6) // 2), y=24))
            display.root_group = g
            return
        except Exception as e:
            print(f"No se pudo cargar imagen {imagen_path}: {e}")

    # Fallback: mostrar nombre del perfil centrado
    perfil_nombre = perfil["nombre"]
    if len(main_group):
        main_group.pop()
    g = displayio.Group()
    etiqueta = label.Label(
        terminalio.FONT,
        text=perfil_nombre,
        scale=2,
        x=(OLED_WIDTH - len(perfil_nombre) * 12) // 2,
        y=16
    )
    g.append(etiqueta)
    display.root_group = g

def actualizar_pantalla(disparo=False):
    """Actualiza la pantalla HUD (exactamente igual al código funcional)."""
    if len(main_group):
        main_group.pop()

    perfil = perfiles[perfil_actual]["nombre"][:12]
    modo = modo_disparo.upper()

    icono_conexion = "*" if conexion_flask else "X"
    icono_modo = {
        "burst": "B",
        "rapid": "R",
        "off": "O",
        "normal": "N"
    }.get(modo_disparo, "?")

    valor_modo = ""
    if modo_disparo == "burst":
        valor_modo = f"{DISPAROS_BURST}"
    elif modo_disparo == "rapid":
        valor_modo = f"{rapid_fire_delay:.2f}s"

    grupo = displayio.Group()
    grupo.append(label.Label(terminalio.FONT, text=f"Perfil: {perfil}", x=0, y=4))
    grupo.append(label.Label(terminalio.FONT, text=icono_conexion, x=110, y=4))
    grupo.append(label.Label(terminalio.FONT, text=f"M: {modo}", x=0, y=14))
    grupo.append(label.Label(terminalio.FONT, text=icono_modo, x=96, y=14))
    grupo.append(label.Label(terminalio.FONT, text=valor_modo, x=110, y=14))
    grupo.append(label.Label(terminalio.FONT, text=f"Estado: {'DISPARO!' if disparo else 'Listo'}", x=0, y=24))
    grupo.append(label.Label(terminalio.FONT, text=f"* {disparos_actual}/{disparos_total}", x=90, y=24))
    display.root_group = grupo

    
# ============ FUNCIONES DE RECOIL Y LED ============
def _gauss(mu, sigma):
    """Box-Muller: random.gauss no existe en CircuitPython."""
    u1 = random.random()
    u2 = random.random()
    if u1 < 1e-10:
        u1 = 1e-10
    z = math.sqrt(-2.0 * math.log(u1)) * math.cos(2.0 * math.pi * u2)
    return mu + sigma * z

def gaussiana_limite(media, desviacion, limite_min, limite_max):
    """Genera un valor gaussiano limitado entre min y max."""
    while True:
        valor = _gauss(media, desviacion)
        if limite_min <= valor <= limite_max:
            return valor
        # Si está fuera de límites, usar valor más cercano al límite
        if valor < limite_min:
            valor = limite_min + abs(valor - limite_min) * 0.1
        else:
            valor = limite_max - abs(valor - limite_max) * 0.1
        if limite_min <= valor <= limite_max:
            return valor

def suavizar_movimiento(valor, max_suavizado=5.0):
    """Suaviza movimientos grandes dividiéndolos en pasos más pequeños."""
    if abs(valor) <= max_suavizado:
        return valor
    # Para movimientos grandes, aplicar factor de suavizado
    signo = 1 if valor >= 0 else -1
    valor_abs = abs(valor)
    # Reducir movimientos grandes progresivamente
    factor = max_suavizado / valor_abs if valor_abs > max_suavizado else 1.0
    return signo * (valor_abs * factor + max_suavizado * (1 - factor))

def aplicar_recoil(perfil):
    """Aplica el ajuste de recoil según el perfil activo."""
    variacion = perfil["variacion"]

    # Calcular movimiento base según modo de precisión
    if USAR_GAUSSIANA:
        dx = gaussiana_limite(perfil["ajuste_x"], variacion,
                              perfil["ajuste_x"] - variacion * 3,
                              perfil["ajuste_x"] + variacion * 3)
        dy = gaussiana_limite(perfil["ajuste_y"], variacion,
                              perfil["ajuste_y"] - variacion * 3,
                              perfil["ajuste_y"] + variacion * 3)
    else:
        dx = perfil["ajuste_x"] + random.uniform(-variacion, variacion)
        dy = perfil["ajuste_y"] + random.uniform(-variacion, variacion)

    # Suavizar movimientos grandes
    if SUAVIZAR_MOVIMIENTOS:
        dx = suavizar_movimiento(dx)
        dy = suavizar_movimiento(dy)

    # Precisión sub-píxel y compensación acumulativa
    if PRECISION_SUB_PIXEL or COMPENSACION_ACUMULATIVA:
        global recoil_acum_x, recoil_acum_y
        recoil_acum_x += dx - int(dx)
        recoil_acum_y += dy - int(dy)
        if COMPENSACION_ACUMULATIVA:
            recoil_acum_x = max(-MAX_COMPENSACION, min(MAX_COMPENSACION, recoil_acum_x))
            recoil_acum_y = max(-MAX_COMPENSACION, min(MAX_COMPENSACION, recoil_acum_y))
        extra_x = int(recoil_acum_x)
        extra_y = int(recoil_acum_y)
        recoil_acum_x -= extra_x
        recoil_acum_y -= extra_y
        dx = int(dx) + extra_x
        dy = int(dy) + extra_y

    mouse.move(int(dx), int(dy))

def resetear_compensacion():
    """Resetea las compensaciones acumulativas."""
    global compensacion_acumulativa_x, compensacion_acumulativa_y
    global contador_disparos_racha, ultimo_reset_compensacion
    compensacion_acumulativa_x = 0.0
    compensacion_acumulativa_y = 0.0
    contador_disparos_racha = 0
    ultimo_reset_compensacion = time.monotonic()
    global recoil_acum_x, recoil_acum_y
    recoil_acum_x = recoil_acum_y = 0.0

def encender_led_perfil():
    """Enciende el LED con el color del perfil actual."""
    color = perfiles[perfil_actual].get("color", [255, 255, 255])
    pixel[0] = tuple(color)

def encender_led_modo():
    """Enciende el LED con el color del modo actual."""
    colores = {
        "normal": (0, 0, 255),      # Azul
        "rapid": (255, 165, 0),     # Naranja
        "burst": (255, 0, 255),     # Magenta
        "off": (30, 30, 30)         # Muy oscuro
    }
    pixel[0] = colores.get(modo_disparo, (255, 255, 255))

def animar_cambio_perfil():
    """Muestra la imagen BMP del perfil nuevo brevemente, luego vuelve al HUD."""
    perfil = perfiles[perfil_actual]
    imagen_path = perfil.get("imagen", "")
    if imagen_path:
        try:
            bitmap, palette = adafruit_imageload.load(
                imagen_path, bitmap=displayio.Bitmap, palette=displayio.Palette)
            tile_grid = displayio.TileGrid(bitmap, pixel_shader=palette)
            g = displayio.Group()
            g.append(tile_grid)
            nombre = perfil["nombre"]
            g.append(label.Label(terminalio.FONT, text=nombre,
                                 x=max(0, (128 - len(nombre) * 6) // 2), y=24))
            display.root_group = g
            time.sleep(0.8)
            return
        except Exception as e:
            print(f"No se pudo animar perfil {imagen_path}: {e}")
    # Fallback: mostrar nombre del perfil 0.5 s
    nombre = perfil["nombre"]
    g = displayio.Group()
    g.append(label.Label(terminalio.FONT, text=nombre, scale=2,
                         x=(OLED_WIDTH - len(nombre) * 12) // 2, y=16))
    display.root_group = g
    time.sleep(0.5)

# ============ FUNCIONES DE GESTIÓN DE PERFILES Y MODOS ============
def cambiar_modo_disparo():
    """Cambia al siguiente modo de disparo."""
    global modo_disparo
    modos = ["normal", "rapid", "burst", "off"]
    modo_disparo = modos[(modos.index(modo_disparo) + 1) % len(modos)]
    print(f"Modo de disparo: {modo_disparo}")
    encender_led_modo()
    actualizar_pantalla()  # Actualizar al cambiar modo

def cambiar_perfil():
    """Cambia al siguiente perfil con animación."""
    global perfil_actual
    perfil_actual = (perfil_actual + 1) % len(perfiles)
    print(f"Cambiado a perfil: {perfiles[perfil_actual]['nombre']}")
    encender_led_perfil()
    animar_cambio_perfil()
    actualizar_pantalla()

def cambiar_perfil_por_nombre(nombre):
    """Cambia al perfil con el nombre especificado con animación."""
    global perfil_actual
    for i, p in enumerate(perfiles):
        if p["nombre"] == nombre:
            perfil_actual = i
            print(f"Cambiado a perfil: {nombre}")
            encender_led_perfil()
            animar_cambio_perfil()
            actualizar_pantalla()
            return True
    return False

def guardar_perfiles():
    try:
        datos = json.dumps(perfiles)
        with open("perfiles.json", "w") as f:
            f.write(datos)
        return True
    except Exception as e:
        print(f"Error guardando perfiles: {e}")
        return False

# ============ FUNCIONES DE COMUNICACIÓN ============
def mover_mouse(coordenadas):
    """Mueve el mouse según las coordenadas especificadas."""
    try:
        partes = coordenadas.strip().split()
        if len(partes) != 2:
            return "ERROR: Formato MOVE inválido. Usa: MOVE <dx> <dy>"
        dx = float(partes[0])
        dy = float(partes[1])
        # Limitar movimiento
        dx = max(-MAX_MOVIMIENTO_MOUSE, min(MAX_MOVIMIENTO_MOUSE, dx))
        dy = max(-MAX_MOVIMIENTO_MOUSE, min(MAX_MOVIMIENTO_MOUSE, dy))
        if abs(dx) < MIN_MOVIMIENTO_MOUSE and abs(dy) < MIN_MOVIMIENTO_MOUSE:
            return "Movimiento insignificante"
        mouse.move(int(dx), int(dy))
        return f"Mouse movido ({int(dx)}, {int(dy)})"
    except ValueError:
        return "ERROR: Valores numéricos inválidos"
    except Exception as e:
        return f"ERROR en MOVE: {e}"
# ============ PROCESAMIENTO DE COMANDOS ============
def procesar_comando(comando, fuente="serial"):
    """Procesa comandos recibidos por serial o Bluetooth.
    
    Args:
        comando: Comando a procesar
        fuente: "serial" o "bt" para actualizar conexión
    """
    global perfil_actual, modo_disparo, rapid_fire_delay
    global DISPAROS_BURST, INTERVALO_BURST, ultimo_ping, delay_normal
    global conexion_flask, disparos_totales_sesion
    global USAR_GAUSSIANA, SUAVIZAR_MOVIMIENTOS, COMPENSACION_ACUMULATIVA, PRECISION_SUB_PIXEL

    ahora = time.monotonic()
    if fuente == "serial":
        conexion_flask = True
        ultimo_ping = ahora
    
    try:
        comando = comando.strip()
        if not comando:
            return "Comando vacío"

        if comando == "LIST":
            # Devolver siempre una lista válida
            return json.dumps(perfiles)
        
        elif comando == "GET_STATUS":
            estado = {
                "perfil_actual": perfiles[perfil_actual]["nombre"],
                "modo": modo_disparo,
                "disparos_sesion": disparos_totales_sesion,
                "conexion_serial": conexion_flask
            }
            return json.dumps(estado)
        
        elif comando == "GET_CONFIG":
            config = {
                "rapid_fire_delay": rapid_fire_delay,
                "delay_normal": delay_normal,
                "disparos_burst": DISPAROS_BURST,
                "intervalo_burst": INTERVALO_BURST,
                "tiempo_reposo": TIEMPO_A_REPOSO
            }
            return json.dumps(config)
        
        elif comando == "HELP" or comando == "?":
            ayuda = (
                "Comandos disponibles:\n"
                "LIST - Lista perfiles\n"
                "GET_STATUS - Estado del sistema\n"
                "GET_CONFIG - Configuración actual\n"
                "SET <nombre> - Cambiar perfil\n"
                "SAVE <json> - Guardar perfil\n"
                "DEL <nombre> - Eliminar perfil\n"
                "SET_MODE <modo> - Cambiar modo\n"
                "SET_DELAY <valor> - Delay rapid fire\n"
                "SET_BURST <cant> <intervalo> - Config burst\n"
                "SET_COLOR <nombre> R G B - Color perfil\n"
                "MOVE <dx> <dy> - Mover mouse\n"
                "SET_TIME <timestamp> o SET_TIME <año> <mes> <día> <hora> <min> <seg> - Establecer hora\n"
                "RESET_STATS - Reset estadísticas"
            )
            return ayuda

        elif comando.startswith("SET "):
            nombre = comando[4:].strip()
            if cambiar_perfil_por_nombre(nombre):
                return f"Perfil activo: {nombre}"
            return "Perfil no encontrado"

        elif comando.startswith("SAVE "):
            try:
                data = json.loads(comando[5:])
                if not validar_perfil(data):
                    return "ERROR: Perfil inválido. Campos requeridos: nombre, ajuste_x, ajuste_y, variacion"
                sobrescribir = data.get("sobrescribir", False)
                for i, p in enumerate(perfiles):
                    if p["nombre"] == data["nombre"]:
                        if sobrescribir:
                            perfiles[i] = data
                            guardar_perfiles()
                            return "Perfil actualizado"
                        else:
                            return "ERROR: Ya existe un perfil con ese nombre. Usa sobrescribir=true"
                perfiles.append(data)
                guardar_perfiles()
                return "Perfil agregado"
            except json.JSONDecodeError:
                return "ERROR: JSON inválido en SAVE"

        elif comando.startswith("DEL "):
            nombre = comando[4:].strip()
            if len(perfiles) <= 1:
                return "ERROR: No se puede eliminar el último perfil"
            perfiles[:] = [p for p in perfiles if p["nombre"] != nombre]
            if perfil_actual >= len(perfiles):
                perfil_actual = 0
            guardar_perfiles()
            encender_led_perfil()
            actualizar_pantalla()
            return "Perfil eliminado"

        elif comando.startswith("SET_MODE "):
            modo = comando[9:].strip().lower()
            if modo in ["normal", "rapid", "burst", "off"]:
                modo_disparo = modo
                encender_led_modo()
                actualizar_pantalla()
                return f"Modo cambiado a: {modo}"
            return "ERROR: Modo no válido (normal, rapid, burst, off)"

        elif comando.startswith("SET_DELAY "):
            try:
                nuevo_delay = float(comando[10:].strip())
                if 0.001 <= nuevo_delay <= 1.0:
                    rapid_fire_delay = nuevo_delay
                    return f"Delay rapid fire: {rapid_fire_delay:.3f}s"
                else:
                    return "ERROR: Valor fuera de rango (0.001 - 1.0)"
            except ValueError:
                return "ERROR: Formato inválido. Usa: SET_DELAY <valor>"

        elif comando.startswith("SET_BURST "):
            try:
                partes = comando[10:].strip().split()
                if len(partes) != 2:
                    return "ERROR: Formato inválido. Usa: SET_BURST <cantidad> <intervalo>"
                cantidad = int(partes[0])
                intervalo = float(partes[1])
                if 1 <= cantidad <= 20 and 0.01 <= intervalo <= 1.0:
                    DISPAROS_BURST = cantidad
                    INTERVALO_BURST = intervalo
                    return f"Burst: {DISPAROS_BURST} disparos cada {INTERVALO_BURST:.2f}s"
                else:
                    return "ERROR: Valores fuera de rango (cantidad: 1-20, intervalo: 0.01-1.0)"
            except ValueError:
                return "ERROR: Valores numéricos inválidos"
            except Exception as e:
                return f"ERROR en SET_BURST: {e}"

        elif comando.startswith("SET_COLOR "):
            try:
                partes = comando[10:].strip().split()
                if len(partes) != 4:
                    return "ERROR: Formato inválido. Usa: SET_COLOR <nombre> <R> <G> <B>"
                nombre = partes[0]
                r, g, b = [int(p) for p in partes[1:]]
                if not all(0 <= c <= 255 for c in (r, g, b)):
                    return "ERROR: Valores RGB fuera de rango (0-255)"
                for perfil in perfiles:
                    if perfil["nombre"] == nombre:
                        perfil["color"] = [r, g, b]
                        guardar_perfiles()
                        if perfiles[perfil_actual]["nombre"] == nombre:
                            encender_led_perfil()
                        return f"Color '{nombre}' actualizado: ({r}, {g}, {b})"
                return "ERROR: Perfil no encontrado"
            except ValueError:
                return "ERROR: Valores RGB inválidos"
            except Exception as e:
                return f"ERROR en SET_COLOR: {e}"

        elif comando.startswith("MOVE "):
            return mover_mouse(comando[5:])
        
        elif comando.startswith("SET_TIME "):
            global offset_tiempo
            try:
                partes = comando[9:].strip().split()
                if len(partes) == 1:
                    # Formato: SET_TIME <timestamp_unix>
                    timestamp = int(partes[0])
                    # Calcular offset desde monotonic actual
                    offset_tiempo = (timestamp + UTC_OFFSET) - time.monotonic()
                    # Calcular hora para mostrar usando el offset
                    tiempo_actual = time.monotonic() + offset_tiempo
                    t = time.localtime(int(tiempo_actual))
                    return f"Hora establecida: {t.tm_hour:02d}:{t.tm_min:02d}:{t.tm_sec:02d}"
                elif len(partes) >= 6:
                    # Formato: SET_TIME <año> <mes> <día> <hora> <minuto> <segundo>
                    año = int(partes[0])
                    mes = int(partes[1])
                    día = int(partes[2])
                    hora = int(partes[3])
                    minuto = int(partes[4])
                    segundo = int(partes[5]) if len(partes) > 5 else 0
                    # Crear tupla de tiempo y convertir a timestamp
                    t_tuple = (año, mes, día, hora, minuto, segundo, 0, 0, -1)
                    timestamp = calendar.timegm(t_tuple)
                    # Calcular offset desde monotonic actual
                    offset_tiempo = (timestamp + UTC_OFFSET) - time.monotonic()
                    return f"Hora establecida: {hora:02d}:{minuto:02d}:{segundo:02d}"
                else:
                    return "ERROR: Formato inválido. Usa: SET_TIME <timestamp> o SET_TIME <año> <mes> <día> <hora> <minuto> <segundo>"
            except ValueError as e:
                return f"ERROR: Valores numéricos inválidos: {e}"
            except Exception as e:
                return f"ERROR en SET_TIME: {e}"
        
        elif comando == "GET_TIME":
            """Obtiene la hora actual del dispositivo."""
            global offset_tiempo
            try:
                if offset_tiempo != 0:
                    tiempo_actual = time.monotonic() + offset_tiempo
                    t = time.localtime(int(tiempo_actual))
                    hora_str = f"{t.tm_hour:02d}:{t.tm_min:02d}:{t.tm_sec:02d}"
                    fecha_str = f"{t.tm_year}-{t.tm_mon:02d}-{t.tm_mday:02d}"
                    return json.dumps({
                        "hora": hora_str,
                        "fecha": fecha_str,
                        "timestamp": int(tiempo_actual),
                        "año": t.tm_year,
                        "mes": t.tm_mon,
                        "día": t.tm_mday,
                        "hora_num": t.tm_hour,
                        "minuto": t.tm_min,
                        "segundo": t.tm_sec
                    })
                else:
                    # Intentar obtener hora del sistema
                    t = time.localtime()
                    if t.tm_year >= 2020:
                        hora_str = f"{t.tm_hour:02d}:{t.tm_min:02d}:{t.tm_sec:02d}"
                        fecha_str = f"{t.tm_year}-{t.tm_mon:02d}-{t.tm_mday:02d}"
                        return json.dumps({
                            "hora": hora_str,
                            "fecha": fecha_str,
                            "timestamp": int(time.monotonic()),
                            "año": t.tm_year,
                            "mes": t.tm_mon,
                            "día": t.tm_mday,
                            "hora_num": t.tm_hour,
                            "minuto": t.tm_min,
                            "segundo": t.tm_sec
                        })
                    else:
                        return json.dumps({"error": "Hora no configurada"})
            except Exception as e:
                return json.dumps({"error": str(e)})
        
        elif comando == "RESET_STATS":
            disparos_totales_sesion = 0
            resetear_compensacion()
            return "Estadísticas y compensación reseteadas"
        
        elif comando.startswith("READ_FILE "):
            try:
                nombre_archivo = comando[10:].strip()
                if not nombre_archivo:
                    return "ERROR: Nombre de archivo vacío"
                if ".." in nombre_archivo or nombre_archivo.startswith("/lib"):
                    return "ERROR: Ruta no permitida"
                with open(nombre_archivo, "r") as f:
                    contenido = f.read()
                # Codificar en base64 para evitar problemas con caracteres especiales
                import base64
                contenido_b64 = base64.b64encode(contenido.encode()).decode()
                return f"FILE_CONTENT:{contenido_b64}"
            except FileNotFoundError:
                return "ERROR: Archivo no encontrado"
            except Exception as e:
                return f"ERROR: {e}"
        
        elif comando.startswith("WRITE_FILE "):
            try:
                # Formato: WRITE_FILE <nombre> <contenido_base64>
                partes = comando[11:].strip().split(" ", 1)
                if len(partes) != 2:
                    return "ERROR: Formato inválido. Usa: WRITE_FILE <nombre> <contenido_base64>"
                nombre_archivo = partes[0]
                if ".." in nombre_archivo or nombre_archivo.startswith("/lib"):
                    return "ERROR: Ruta no permitida"
                contenido_b64 = partes[1]
                import base64
                contenido = base64.b64decode(contenido_b64).decode()
                with open(nombre_archivo, "w") as f:
                    f.write(contenido)
                return f"Archivo '{nombre_archivo}' guardado exitosamente"
            except Exception as e:
                return f"ERROR: {e}"
        
        elif comando == "LIST_FILES":
            try:
                archivos = []
                for item in os.listdir("/"):
                    try:
                        stat = os.stat("/" + item)
                        archivos.append({
                            "nombre": item,
                            "tipo": "directorio" if stat[0] & 0o170000 == 0o040000 else "archivo",
                            "tamaño": stat[6]
                        })
                    except:
                        pass
                return json.dumps(archivos)
            except Exception as e:
                return f"ERROR: {e}"
        
        elif comando.startswith("SET_INIT_TEXT "):
            global texto_inicio
            try:
                nuevo_texto = comando[14:].strip()
                if not nuevo_texto:
                    return "ERROR: Texto vacío"
                if len(nuevo_texto) > 20:
                    return "ERROR: Texto muy largo (máximo 20 caracteres)"
                texto_inicio = nuevo_texto
                return f"Texto de inicio actualizado: '{texto_inicio}'"
            except Exception as e:
                return f"ERROR: {e}"
        
        elif comando == "GET_INIT_TEXT":
            global texto_inicio
            return texto_inicio
        
        elif comando.startswith("SET_PRECISION "):
            try:
                partes = comando[14:].strip().split()
                if len(partes) != 4:
                    return "ERROR: Formato inválido. Usa: SET_PRECISION <gaussiana> <suavizar> <compensacion> <subpixel> (0 o 1)"
                USAR_GAUSSIANA = bool(int(partes[0]))
                SUAVIZAR_MOVIMIENTOS = bool(int(partes[1]))
                COMPENSACION_ACUMULATIVA = bool(int(partes[2]))
                PRECISION_SUB_PIXEL = bool(int(partes[3]))
                return f"Precisión: Gauss={USAR_GAUSSIANA}, Suav={SUAVIZAR_MOVIMIENTOS}, Comp={COMPENSACION_ACUMULATIVA}, SubPx={PRECISION_SUB_PIXEL}"
            except (ValueError, IndexError):
                return "ERROR: Valores inválidos. Usa 0 o 1 para cada opción"

        else:
            return f"Comando desconocido: {comando}. Usa HELP para ver comandos"

    except Exception as e:
        return f"ERROR: {e}"

def parpadear_error():
    """Parpadea el LED en rojo para indicar error."""
    for _ in range(2):
        pixel[0] = (255, 0, 0)
        time.sleep(0.1)
        pixel[0] = (0, 0, 0)
        time.sleep(0.1)

# ============ FUNCIONES DE DISPARO ============
def disparar_modo_rapid(perfil):
    """Maneja el disparo en modo rapid fire (igual que código funcional)."""
    global disparos_actual, disparos_total
    disparos_actual = 0
    while not btn_disparo.value:
        disparos_actual += 1
        disparos_total = disparos_actual
        actualizar_pantalla(disparo=True)
        aplicar_recoil(perfil)
        mouse.click(Mouse.LEFT_BUTTON)
        time.sleep(rapid_fire_delay)

def disparar_modo_burst(perfil):
    """Maneja el disparo en modo burst (igual que código funcional)."""
    global disparos_actual, disparos_total
    disparos_actual = 0
    disparos_total = DISPAROS_BURST
    for _ in range(DISPAROS_BURST):
        disparos_actual += 1
        actualizar_pantalla(disparo=True)
        aplicar_recoil(perfil)
        mouse.click(Mouse.LEFT_BUTTON)
        time.sleep(INTERVALO_BURST)
    while not btn_disparo.value:
        time.sleep(0.01)

def disparar_modo_normal(perfil):
    """Maneja el disparo en modo normal."""
    global disparos_actual, disparos_total
    disparos_actual = 1
    disparos_total = 1
    actualizar_pantalla(disparo=True)
    while not btn_disparo.value:
        aplicar_recoil(perfil)
        time.sleep(delay_normal)

# ============ FUNCIONES DE DEBOUNCE ============
def boton_presionado(boton, estado_ant):
    """Detecta flanco bajada (True→False). Dispara una sola vez por pulsación.
    Retorna (accion, nuevo_estado_ant)."""
    actual = boton.value   # True=suelto, False=presionado
    accion = (not actual) and estado_ant
    return accion, actual

# ============ INICIALIZACIÓN DEL SISTEMA ============
print("Sistema recoil listo.")
print("Perfil:", perfiles[perfil_actual]["nombre"])
pantalla_inicio()
encender_led_perfil()
encender_led_modo()
actualizar_pantalla()

# Variables de debounce
tiempo_perfil = time.monotonic()
tiempo_modo = time.monotonic()
tiempo_disparo = time.monotonic()

# Variables de precisión y compensación
compensacion_acumulativa_x = 0.0
compensacion_acumulativa_y = 0.0
recoil_acum_x = recoil_acum_y = 0.0
contador_disparos_racha = 0
ultimo_reset_compensacion = time.monotonic()

# ============ BUCLE PRINCIPAL ============
while True:
    try:
        # Actualizar estado de conexiones (timeout)
        ahora = time.monotonic()
        if ahora - ultimo_ping > TIMEOUT_CONEXION:
            conexion_flask = False

        # Procesar comandos serial
        if supervisor.runtime.serial_connected and serial.in_waiting:
            try:
                raw = serial.readline()
                comando = raw.decode().strip()
                if comando:
                    respuesta = procesar_comando(comando, fuente="serial")
                    serial.write((respuesta + "\n").encode())
            except Exception as e:
                print(f"Error procesando comando serial: {e}")

        perfil = perfiles[perfil_actual]

        # Cambiar perfil con debounce
        accion_perf, btn_perfil_anterior = boton_presionado(
            btn_cambio_perfil, btn_perfil_anterior)
        if accion_perf:
            cambiar_perfil()

        # Cambiar modo con debounce
        accion_modo, btn_modo_anterior = boton_presionado(
            btn_cambio_modo, btn_modo_anterior)
        if accion_modo:
            cambiar_modo_disparo()

        # Disparar (igual que código funcional - lectura directa)
        if not btn_disparo.value and modo_disparo != "off":
            pixel[0] = (0, 255, 0)
            ultimo_disparo = time.monotonic()
            estado_pantalla = "hud"
            actualizar_pantalla(disparo=True)

            if modo_disparo == "rapid":
                disparar_modo_rapid(perfil)
            elif modo_disparo == "burst":
                disparar_modo_burst(perfil)
            else:  # modo normal
                disparar_modo_normal(perfil)

            actualizar_pantalla()
        else:
            encender_led_perfil()
            ahora = time.monotonic()
            
            # Cambiar a pantalla de reposo después de TIEMPO_A_REPOSO segundos sin disparar
            if ahora - ultimo_disparo > TIEMPO_A_REPOSO:
                if estado_pantalla != "reposo":
                    estado_pantalla = "reposo"
                    pantalla_reposo()
                    ultima_actualizacion_reposo = ahora
                # Actualizar la hora cada segundo cuando está en reposo
                elif ahora - ultima_actualizacion_reposo >= 1.0:
                    pantalla_reposo()
                    ultima_actualizacion_reposo = ahora
            else:
                if estado_pantalla != "hud":
                    estado_pantalla = "hud"
                    actualizar_pantalla()
            
            # Actualización adicional: si está en reposo, verificar cada segundo
            if estado_pantalla == "reposo" and ahora - ultima_actualizacion_reposo >= 1.0:
                pantalla_reposo()
                ultima_actualizacion_reposo = ahora
            
            time.sleep(0.01)

        time.sleep(0.005)  # Pequeño delay para evitar saturación de CPU

    except KeyboardInterrupt:
        raise
    except Exception as loop_error:
        print(f"ERROR GENERAL: {loop_error}")
        parpadear_error()
        time.sleep(0.5)
