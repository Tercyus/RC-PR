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
from adafruit_display_shapes.rect import Rect
from adafruit_hid.mouse import Mouse
import os
import math

def _timegm(año, mes, dia, hora, minuto, seg):
    """Convierte fecha UTC a timestamp Unix (reemplaza calendar.timegm)."""
    dias_mes = (0, 31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)
    dias = (año - 1970) * 365
    dias += (año - 1969) // 4 - (año - 1901) // 100 + (año - 1601) // 400
    for m in range(1, mes):
        dias += dias_mes[m]
    if mes > 2 and (año % 4 == 0 and (año % 100 != 0 or año % 400 == 0)):
        dias += 1
    dias += dia - 1
    return dias * 86400 + hora * 3600 + minuto * 60 + seg

# ============ CONSTANTES DE CONFIGURACIÓN ============
# Leídas de settings.toml; si no existen se usan los valores por defecto
TIEMPO_A_REPOSO    = float(os.getenv("TIEMPO_A_REPOSO",    "3.0"))
DEBOUNCE_BOTONES   = float(os.getenv("DEBOUNCE_BOTONES",   "0.15"))
LONG_PRESS_TIEMPO  = float(os.getenv("LONG_PRESS_TIEMPO",  "1.5"))
UTC_OFFSET         = int(  os.getenv("UTC_OFFSET",         "-18000"))

DELAY_RAPID_FIRE_DEFAULT = 0.01
DISPAROS_BURST_DEFAULT   = 5
INTERVALO_BURST_DEFAULT  = 0.03
DELAY_NORMAL_DEFAULT     = 0.05
MAX_MOVIMIENTO_MOUSE     = 30
MIN_MOVIMIENTO_MOUSE     = 1
OLED_ADDRESS = 0x3C
OLED_WIDTH   = 128
OLED_HEIGHT  = 64          # ← 128×64

# Precisión (configurables desde settings.toml)
USAR_GAUSSIANA        = os.getenv("USAR_GAUSSIANA",        "1") == "1"
SUAVIZAR_MOVIMIENTOS  = os.getenv("SUAVIZAR_MOVIMIENTOS",  "1") == "1"
COMPENSACION_ACUMULATIVA = os.getenv("COMPENSACION_ACUMULATIVA", "1") == "1"
PRECISION_SUB_PIXEL   = os.getenv("PRECISION_SUB_PIXEL",  "1") == "1"
MAX_COMPENSACION = 2.0

# ============ INICIALIZACIÓN BÁSICA ============
time.sleep(0.05)

pixel = adafruit_neopixel.NeoPixel(board.GP16, 1, brightness=0.4, auto_write=True)
pixel[0] = (0, 0, 0)

# Botones con pull-up
btn_disparo = digitalio.DigitalInOut(board.GP9)
btn_disparo.direction = digitalio.Direction.INPUT
btn_disparo.pull = digitalio.Pull.UP

btn_cambio_perfil = digitalio.DigitalInOut(board.GP2)
btn_cambio_perfil.direction = digitalio.Direction.INPUT
btn_cambio_perfil.pull = digitalio.Pull.UP

btn_cambio_modo = digitalio.DigitalInOut(board.GP8)
btn_cambio_modo.direction = digitalio.Direction.INPUT
btn_cambio_modo.pull = digitalio.Pull.UP

serial = usb_cdc.console

# Pantalla OLED 128×64
# CircuitPython 8+: I2CDisplay fue movido a i2cdisplaybus
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
    display_bus = i2cdisplaybus.I2CDisplayBus(i2c, device_address=OLED_ADDRESS)
except ImportError:
    display_bus = displayio.I2CDisplay(i2c, device_address=OLED_ADDRESS)
display = SSD1306(display_bus, width=OLED_WIDTH, height=OLED_HEIGHT, rotation=180)
main_group = displayio.Group()
display.root_group = main_group
time.sleep(0.1)

# ============ VARIABLES DEL SISTEMA ============
conexion_flask = True
disparos_actual = 0
disparos_total  = 3
disparos_totales_sesion = 0
modo_disparo   = "normal"
rapid_fire_delay = DELAY_RAPID_FIRE_DEFAULT
DISPAROS_BURST   = DISPAROS_BURST_DEFAULT
INTERVALO_BURST  = INTERVALO_BURST_DEFAULT
delay_normal     = DELAY_NORMAL_DEFAULT

ultimo_disparo          = time.monotonic()
estado_pantalla         = "hud"
ultimo_ping             = time.monotonic()
ultima_actualizacion_reposo = time.monotonic()
TIMEOUT_CONEXION        = 5.0
offset_tiempo           = 0

# Estados previos de botones (debounce)
btn_perfil_anterior = True
btn_modo_anterior   = True
btn_disparo_anterior = True
tiempo_perfil  = time.monotonic()
tiempo_modo    = time.monotonic()
tiempo_disparo = time.monotonic()

# Long press (botón MODO)
tiempo_inicio_modo      = 0.0
long_press_modo_detectado = False

# ============ VARIABLES DE MENÚ ============
#   estado_sistema: "normal" | "menu" | "editar_perfil" | "editar_valor"
estado_sistema  = "normal"
menu_cursor     = 0
menu_offset     = 0
perfil_editando = 0
campo_cursor    = 0
perfil_temp     = {}

# Campos editables del perfil y sus rangos
CAMPOS = [
    {"clave": "ajuste_x",  "label": "AjX",  "min": -20.0, "max": 20.0, "paso": 1.0,  "dec": 0},
    {"clave": "ajuste_y",  "label": "AjY",  "min":   0.0, "max": 30.0, "paso": 1.0,  "dec": 0},
    {"clave": "variacion", "label": "Var",  "min":   0.0, "max":  2.0, "paso": 0.05, "dec": 2},
]
MENU_VISIBLES = 4   # filas visibles en cualquier menú (encaja en 128×64 con header)

# ============ CARGA DE PERFILES ============
def validar_perfil(p):
    return all(k in p for k in ("nombre", "ajuste_x", "ajuste_y", "variacion"))

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
    perfiles = [{"nombre": "default", "ajuste_x": 0, "ajuste_y": 5,
                 "variacion": 0.3, "color": [0, 0, 255]}]

perfil_actual = 0
mouse = Mouse(usb_hid.devices)

# ============ PANTALLAS ============
def pantalla_inicio():
    try:
        bmp, pal = adafruit_imageload.load(
            "/Default.bmp", bitmap=displayio.Bitmap, palette=displayio.Palette)
        g = displayio.Group()
        g.append(displayio.TileGrid(bmp, pixel_shader=pal))
        display.root_group = g
        time.sleep(2)
    except Exception as e:
        print("Imagen inicio no disponible:", e)
        for x in range(-80, 30, 3):
            g = displayio.Group()
            g.append(label.Label(terminalio.FONT, text="RECOIL", scale=3, x=x, y=32))
            display.root_group = g
            time.sleep(0.03)
        time.sleep(1)

def pantalla_reposo():
    """Imagen BMP del perfil activo en reposo, o nombre como fallback."""
    perfil = perfiles[perfil_actual]
    img = perfil.get("imagen", "")
    if img:
        try:
            bmp, pal = adafruit_imageload.load(
                img, bitmap=displayio.Bitmap, palette=displayio.Palette)
            g = displayio.Group()
            g.append(displayio.TileGrid(bmp, pixel_shader=pal))
            nombre = perfil["nombre"]
            g.append(label.Label(terminalio.FONT, text=nombre,
                                 x=max(0, (OLED_WIDTH - len(nombre) * 6) // 2), y=54))
            display.root_group = g
            return
        except Exception as e:
            print(f"Imagen reposo no cargada: {e}")
    nombre = perfil["nombre"]
    g = displayio.Group()
    g.append(label.Label(terminalio.FONT, text=nombre, scale=2,
                         x=max(0, (OLED_WIDTH - len(nombre) * 12) // 2), y=28))
    g.append(label.Label(terminalio.FONT, text="Hold MODO = Menu", x=8, y=55))
    display.root_group = g

def actualizar_pantalla(disparo=False):
    """HUD completo para 128×64. 7 líneas de información."""
    p = perfiles[perfil_actual]
    nom  = p["nombre"][:14]
    cx   = "*" if conexion_flask else "X"
    im   = {"burst": "B", "rapid": "R", "off": "O", "normal": "N"}.get(modo_disparo, "?")
    vm   = f"x{DISPAROS_BURST}" if modo_disparo == "burst" else (
           f"{rapid_fire_delay:.2f}s" if modo_disparo == "rapid" else "")
    vals = f"X:{p['ajuste_x']} Y:{p['ajuste_y']} V:{p['variacion']:.2f}"
    est  = "!DISPARO!" if disparo else "  Listo  "

    g = displayio.Group()
    g.append(label.Label(terminalio.FONT, text=f"P:{nom}",                x=0,   y=4))
    g.append(label.Label(terminalio.FONT, text=cx,                        x=122, y=4))
    g.append(label.Label(terminalio.FONT, text=f"M:{modo_disparo.upper()} {vm}", x=0, y=14))
    g.append(label.Label(terminalio.FONT, text=im,                        x=122, y=14))
    g.append(label.Label(terminalio.FONT, text="-" * 21,                  x=0,   y=23))
    g.append(label.Label(terminalio.FONT, text=vals,                      x=0,   y=33))
    g.append(label.Label(terminalio.FONT, text=f"Tiros:{disparos_actual}/{disparos_total}", x=0, y=43))
    g.append(label.Label(terminalio.FONT, text=f"Est:{est}",              x=0,   y=53))
    g.append(label.Label(terminalio.FONT, text="[HoldMODO=Menu]",         x=0,   y=62))
    display.root_group = g

# ============ PANTALLAS DE MENÚ ============
def _items_menu():
    """Lista de ítems del menú principal."""
    return [p["nombre"] for p in perfiles] + ["[Guardar y Salir]", "[Salir sin Guardar]"]

def dibujar_menu():
    items = _items_menu()
    g = displayio.Group()
    # Barra de título sólida
    g.append(Rect(0, 0, OLED_WIDTH, 13, fill=0xFFFFFF))
    g.append(label.Label(terminalio.FONT, text="PERFILES", scale=1,
                         x=(OLED_WIDTH - 8*6)//2, y=5, color=0x000000))
    # Ítems con selección invertida
    for i in range(MENU_VISIBLES):
        idx = menu_offset + i
        if idx >= len(items):
            break
        y = 15 + i * 11
        if idx == menu_cursor:
            g.append(Rect(0, y - 1, OLED_WIDTH - 8, 10, fill=0xFFFFFF))
            g.append(label.Label(terminalio.FONT, text=items[idx][:20],
                                 x=2, y=y + 5, color=0x000000))
        else:
            g.append(label.Label(terminalio.FONT, text=items[idx][:20],
                                 x=2, y=y + 5, color=0xFFFFFF))
    # Indicadores de scroll
    if menu_offset > 0:
        g.append(label.Label(terminalio.FONT, text="▲", x=120, y=20))
    if menu_offset + MENU_VISIBLES < len(items):
        g.append(label.Label(terminalio.FONT, text="▼", x=120, y=54))
    # Barra de ayuda inferior
    g.append(Rect(0, 56, OLED_WIDTH, 8, fill=0xFFFFFF))
    g.append(label.Label(terminalio.FONT, text="P=^  M=v  D=OK  [M]=Sal",
                         x=0, y=61, color=0x000000))
    display.root_group = g

def _items_editar():
    """Genera la lista de ítems de la pantalla de edición."""
    items = []
    for c in CAMPOS:
        val = perfil_temp.get(c["clave"], 0)
        txt = f"{c['label']:3}: {int(val)}" if c["dec"] == 0 else f"{c['label']:3}: {val:.2f}"
        items.append(txt)
    return items + ["[Guardar perfil]", "[Cancelar]"]

def dibujar_editar_perfil():
    nombre = perfiles[perfil_editando]["nombre"][:14]
    items  = _items_editar()
    offset = max(0, campo_cursor - MENU_VISIBLES + 1)
    g = displayio.Group()
    # Barra de título con nombre del perfil
    g.append(Rect(0, 0, OLED_WIDTH, 13, fill=0xFFFFFF))
    titulo = f"< {nombre}"
    g.append(label.Label(terminalio.FONT, text=titulo, x=2, y=5, color=0x000000))
    # Ítems con selección invertida
    for i in range(MENU_VISIBLES):
        idx = offset + i
        if idx >= len(items):
            break
        y = 15 + i * 11
        if idx == campo_cursor:
            g.append(Rect(0, y - 1, OLED_WIDTH - 8, 10, fill=0xFFFFFF))
            g.append(label.Label(terminalio.FONT, text=items[idx][:20],
                                 x=2, y=y + 5, color=0x000000))
        else:
            g.append(label.Label(terminalio.FONT, text=items[idx][:20],
                                 x=2, y=y + 5, color=0xFFFFFF))
    # Indicadores de scroll
    if offset > 0:
        g.append(label.Label(terminalio.FONT, text="▲", x=120, y=20))
    if offset + MENU_VISIBLES < len(items):
        g.append(label.Label(terminalio.FONT, text="▼", x=120, y=54))
    # Barra de ayuda inferior
    g.append(Rect(0, 56, OLED_WIDTH, 8, fill=0xFFFFFF))
    g.append(label.Label(terminalio.FONT, text="P=^  M=v  D=OK  [M]=Menu",
                         x=0, y=61, color=0x000000))
    display.root_group = g

def dibujar_editar_valor():
    c   = CAMPOS[campo_cursor]
    val = perfil_temp.get(c["clave"], 0)
    nom = perfiles[perfil_editando]["nombre"][:14]
    val_str = str(int(val)) if c["dec"] == 0 else f"{val:.2f}"
    x_val = max(0, (OLED_WIDTH - len(val_str) * 12) // 2)

    # Barra de progreso: posición del valor entre min y max
    rango = c["max"] - c["min"]
    progreso = int((val - c["min"]) / rango * (OLED_WIDTH - 4)) if rango else 0
    progreso = max(0, min(OLED_WIDTH - 4, progreso))

    g = displayio.Group()
    # Barra de título
    g.append(Rect(0, 0, OLED_WIDTH, 13, fill=0xFFFFFF))
    g.append(label.Label(terminalio.FONT, text=f"{c['label']} - {nom}",
                         x=2, y=5, color=0x000000))
    # Rango
    g.append(label.Label(terminalio.FONT, text=f"min:{c['min']}",  x=0,  y=20))
    g.append(label.Label(terminalio.FONT, text=f"max:{c['max']}",  x=90, y=20))
    # Valor grande centrado
    g.append(label.Label(terminalio.FONT, text=val_str, scale=2, x=x_val, y=38))
    # Barra de progreso
    g.append(Rect(2, 46, OLED_WIDTH - 4, 5, fill=0x000000, outline=0xFFFFFF))
    if progreso > 0:
        g.append(Rect(2, 46, progreso, 5, fill=0xFFFFFF))
    # Barra de ayuda inferior
    g.append(Rect(0, 56, OLED_WIDTH, 8, fill=0xFFFFFF))
    g.append(label.Label(terminalio.FONT, text="P=+   M=-   DISP=OK",
                         x=4, y=61, color=0x000000))
    display.root_group = g

# ============ LÓGICA DE MENÚ ============
def entrar_menu():
    global estado_sistema, menu_cursor, menu_offset
    estado_sistema = "menu"
    menu_cursor = menu_offset = 0
    dibujar_menu()

def salir_menu():
    global estado_sistema
    estado_sistema = "normal"
    actualizar_pantalla()

def menu_arriba():
    global menu_cursor, menu_offset
    if menu_cursor > 0:
        menu_cursor -= 1
        if menu_cursor < menu_offset:
            menu_offset = menu_cursor
        dibujar_menu()

def menu_abajo():
    global menu_cursor, menu_offset
    items = _items_menu()
    if menu_cursor < len(items) - 1:
        menu_cursor += 1
        if menu_cursor >= menu_offset + MENU_VISIBLES:
            menu_offset = menu_cursor - MENU_VISIBLES + 1
        dibujar_menu()

def menu_seleccionar():
    global estado_sistema, perfil_editando, campo_cursor, perfil_temp
    n = len(perfiles)
    if menu_cursor < n:
        perfil_editando = menu_cursor
        campo_cursor = 0
        perfil_temp = dict(perfiles[perfil_editando])
        estado_sistema = "editar_perfil"
        dibujar_editar_perfil()
    elif menu_cursor == n:
        # Guardar y salir
        guardar_perfiles()
        _mostrar_mensaje("Guardado!")
        salir_menu()
    else:
        salir_menu()

def campo_arriba():
    global campo_cursor
    if campo_cursor > 0:
        campo_cursor -= 1
    dibujar_editar_perfil()

def campo_abajo():
    global campo_cursor
    total = len(CAMPOS) + 2   # campos + Guardar + Cancelar
    if campo_cursor < total - 1:
        campo_cursor += 1
    dibujar_editar_perfil()

def campo_seleccionar():
    global estado_sistema
    if campo_cursor < len(CAMPOS):
        # Editar valor
        estado_sistema = "editar_valor"
        dibujar_editar_valor()
    else:
        idx_extra = campo_cursor - len(CAMPOS)
        if idx_extra == 0:   # Guardar perfil
            perfiles[perfil_editando].update(perfil_temp)
            guardar_perfiles()
            _mostrar_mensaje("Guardado!")
        # Cancelar o tras guardar → volver al menú
        estado_sistema = "menu"
        dibujar_menu()

def valor_incrementar():
    c   = CAMPOS[campo_cursor]
    val = round(perfil_temp.get(c["clave"], 0) + c["paso"], 4)
    perfil_temp[c["clave"]] = min(c["max"], val)
    dibujar_editar_valor()

def valor_decrementar():
    c   = CAMPOS[campo_cursor]
    val = round(perfil_temp.get(c["clave"], 0) - c["paso"], 4)
    perfil_temp[c["clave"]] = max(c["min"], val)
    dibujar_editar_valor()

def valor_confirmar():
    global estado_sistema
    estado_sistema = "editar_perfil"
    dibujar_editar_perfil()

def _mostrar_mensaje(txt):
    g = displayio.Group()
    # Recuadro centrado
    g.append(Rect(14, 20, 100, 24, fill=0x000000, outline=0xFFFFFF))
    x = max(16, (OLED_WIDTH - len(txt) * 6) // 2)
    g.append(label.Label(terminalio.FONT, text=txt, scale=1, x=x, y=32))
    display.root_group = g
    time.sleep(1)

# ============ FUNCIONES DE RECOIL Y LED ============
def _gauss(mu, sigma):
    """Box-Muller: random.gauss no existe en CircuitPython."""
    u1 = random.random()
    u2 = random.random()
    if u1 < 1e-10:
        u1 = 1e-10
    z = math.sqrt(-2.0 * math.log(u1)) * math.cos(2.0 * math.pi * u2)
    return mu + sigma * z

def gaussiana_limite(media, desviacion, lmin, lmax):
    while True:
        v = _gauss(media, desviacion)
        if lmin <= v <= lmax:
            return v
        v = lmin + abs(v - lmin) * 0.1 if v < lmin else lmax - abs(v - lmax) * 0.1
        if lmin <= v <= lmax:
            return v

def suavizar_movimiento(valor, tope=5.0):
    if abs(valor) <= tope:
        return valor
    s = 1 if valor >= 0 else -1
    a = abs(valor)
    f = tope / a
    return s * (a * f + tope * (1 - f))

def aplicar_recoil(perfil):
    var = perfil["variacion"]
    if USAR_GAUSSIANA:
        dx = gaussiana_limite(perfil["ajuste_x"], var,
                              perfil["ajuste_x"] - var * 3, perfil["ajuste_x"] + var * 3)
        dy = gaussiana_limite(perfil["ajuste_y"], var,
                              perfil["ajuste_y"] - var * 3, perfil["ajuste_y"] + var * 3)
    else:
        dx = perfil["ajuste_x"] + random.uniform(-var, var)
        dy = perfil["ajuste_y"] + random.uniform(-var, var)

    if SUAVIZAR_MOVIMIENTOS:
        dx = suavizar_movimiento(dx)
        dy = suavizar_movimiento(dy)

    if PRECISION_SUB_PIXEL or COMPENSACION_ACUMULATIVA:
        global recoil_acum_x, recoil_acum_y
        recoil_acum_x += dx - int(dx)
        recoil_acum_y += dy - int(dy)
        if COMPENSACION_ACUMULATIVA:
            recoil_acum_x = max(-MAX_COMPENSACION, min(MAX_COMPENSACION, recoil_acum_x))
            recoil_acum_y = max(-MAX_COMPENSACION, min(MAX_COMPENSACION, recoil_acum_y))
        ex, ey = int(recoil_acum_x), int(recoil_acum_y)
        recoil_acum_x -= ex
        recoil_acum_y -= ey
        dx, dy = int(dx) + ex, int(dy) + ey

    mouse.move(int(dx), int(dy))

def resetear_compensacion():
    global compensacion_acumulativa_x, compensacion_acumulativa_y
    global contador_disparos_racha, ultimo_reset_compensacion
    compensacion_acumulativa_x = compensacion_acumulativa_y = 0.0
    contador_disparos_racha = 0
    ultimo_reset_compensacion = time.monotonic()
    global recoil_acum_x, recoil_acum_y
    recoil_acum_x = recoil_acum_y = 0.0

def encender_led_perfil():
    pixel[0] = tuple(perfiles[perfil_actual].get("color", [255, 255, 255]))

def encender_led_modo():
    pixel[0] = {"normal": (0, 0, 255), "rapid": (255, 165, 0),
                "burst": (255, 0, 255), "off": (30, 30, 30)}.get(modo_disparo, (255, 255, 255))

def animar_cambio_perfil():
    p   = perfiles[perfil_actual]
    img = p.get("imagen", "")
    if img:
        try:
            bmp, pal = adafruit_imageload.load(
                img, bitmap=displayio.Bitmap, palette=displayio.Palette)
            g = displayio.Group()
            g.append(displayio.TileGrid(bmp, pixel_shader=pal))
            nombre = p["nombre"]
            g.append(label.Label(terminalio.FONT, text=nombre,
                                 x=max(0, (OLED_WIDTH - len(nombre) * 6) // 2), y=54))
            display.root_group = g
            time.sleep(0.3)
            return
        except Exception as e:
            print(f"Animación perfil fallida: {e}")
    nombre = p["nombre"]
    g = displayio.Group()
    g.append(label.Label(terminalio.FONT, text=nombre, scale=2,
                         x=max(0, (OLED_WIDTH - len(nombre) * 12) // 2), y=32))
    display.root_group = g
    time.sleep(0.2)

# ============ GESTIÓN DE PERFILES Y MODOS ============
def cambiar_modo_disparo():
    global modo_disparo
    modos = ["normal", "rapid", "burst", "off"]
    modo_disparo = modos[(modos.index(modo_disparo) + 1) % len(modos)]
    print(f"Modo: {modo_disparo}")
    encender_led_modo()
    actualizar_pantalla()

def cambiar_perfil():
    global perfil_actual
    perfil_actual = (perfil_actual + 1) % len(perfiles)
    print(f"Perfil: {perfiles[perfil_actual]['nombre']}")
    encender_led_perfil()
    animar_cambio_perfil()
    actualizar_pantalla()

def cambiar_perfil_por_nombre(nombre):
    global perfil_actual
    for i, p in enumerate(perfiles):
        if p["nombre"] == nombre:
            perfil_actual = i
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

# ============ COMUNICACIÓN ============
def mover_mouse(coords):
    try:
        partes = coords.strip().split()
        if len(partes) != 2:
            return "ERROR: MOVE <dx> <dy>"
        dx = max(-MAX_MOVIMIENTO_MOUSE, min(MAX_MOVIMIENTO_MOUSE, float(partes[0])))
        dy = max(-MAX_MOVIMIENTO_MOUSE, min(MAX_MOVIMIENTO_MOUSE, float(partes[1])))
        if abs(dx) < MIN_MOVIMIENTO_MOUSE and abs(dy) < MIN_MOVIMIENTO_MOUSE:
            return "Movimiento insignificante"
        mouse.move(int(dx), int(dy))
        return f"Mouse movido ({int(dx)}, {int(dy)})"
    except Exception as e:
        return f"ERROR en MOVE: {e}"

# ============ PROCESAMIENTO DE COMANDOS ============
def procesar_comando(comando, fuente="serial"):
    global perfil_actual, modo_disparo, rapid_fire_delay, delay_normal
    global DISPAROS_BURST, INTERVALO_BURST, ultimo_ping, ultimo_ping_bt
    global conexion_flask, disparos_totales_sesion, offset_tiempo
    global USAR_GAUSSIANA, SUAVIZAR_MOVIMIENTOS, COMPENSACION_ACUMULATIVA, PRECISION_SUB_PIXEL

    ahora = time.monotonic()
    if fuente == "serial":
        conexion_flask = True;  ultimo_ping = ahora

    try:
        comando = comando.strip()
        if not comando:
            return "Comando vacío"

        if comando == "LIST":
            return json.dumps(perfiles)

        elif comando == "GET_STATUS":
            return json.dumps({
                "perfil_actual": perfiles[perfil_actual]["nombre"],
                "modo": modo_disparo,
                "disparos_sesion": disparos_totales_sesion,
                "conexion_serial": conexion_flask,
                "menu_activo": estado_sistema != "normal"
            })

        elif comando == "GET_CONFIG":
            return json.dumps({
                "rapid_fire_delay": rapid_fire_delay,
                "delay_normal": delay_normal,
                "disparos_burst": DISPAROS_BURST,
                "intervalo_burst": INTERVALO_BURST,
                "tiempo_reposo": TIEMPO_A_REPOSO
            })

        elif comando in ("HELP", "?"):
            return (
                "LIST  GET_STATUS  GET_CONFIG\n"
                "SET <nombre>  SAVE <json>  DEL <nombre>\n"
                "SET_MODE <modo>  SET_DELAY <val>\n"
                "SET_BURST <n> <intervalo>\n"
                "SET_COLOR <nombre> R G B\n"
                "MOVE <dx> <dy>  SET_TIME <ts>\n"
                "GET_TIME  RESET_STATS  LIST_FILES\n"
                "READ_FILE <ruta>  WRITE_FILE <ruta> <b64>"
            )

        elif comando.startswith("SET "):
            nombre = comando[4:].strip()
            return f"Perfil activo: {nombre}" if cambiar_perfil_por_nombre(nombre) else "Perfil no encontrado"

        elif comando.startswith("SAVE "):
            try:
                data = json.loads(comando[5:])
                if not validar_perfil(data):
                    return "ERROR: Perfil inválido"
                for i, p in enumerate(perfiles):
                    if p["nombre"] == data["nombre"]:
                        if data.get("sobrescribir", False):
                            perfiles[i] = data;  guardar_perfiles()
                            return "Perfil actualizado"
                        return "ERROR: Ya existe. Usa sobrescribir=true"
                perfiles.append(data);  guardar_perfiles()
                return "Perfil agregado"
            except json.JSONDecodeError:
                return "ERROR: JSON inválido"

        elif comando.startswith("DEL "):
            nombre = comando[4:].strip()
            if len(perfiles) <= 1:
                return "ERROR: No se puede eliminar el último perfil"
            perfiles[:] = [p for p in perfiles if p["nombre"] != nombre]
            if perfil_actual >= len(perfiles):
                perfil_actual = 0
            guardar_perfiles();  encender_led_perfil();  actualizar_pantalla()
            return "Perfil eliminado"

        elif comando.startswith("SET_MODE "):
            modo = comando[9:].strip().lower()
            if modo in ("normal", "rapid", "burst", "off"):
                modo_disparo = modo;  encender_led_modo();  actualizar_pantalla()
                return f"Modo: {modo}"
            return "ERROR: normal | rapid | burst | off"

        elif comando.startswith("SET_DELAY "):
            try:
                v = float(comando[10:].strip())
                if 0.001 <= v <= 1.0:
                    rapid_fire_delay = v
                    return f"Delay: {v:.3f}s"
                return "ERROR: rango 0.001-1.0"
            except ValueError:
                return "ERROR: valor numérico inválido"

        elif comando.startswith("SET_BURST "):
            try:
                p = comando[10:].strip().split()
                if len(p) != 2:
                    return "ERROR: SET_BURST <n> <intervalo>"
                cant, intv = int(p[0]), float(p[1])
                if 1 <= cant <= 20 and 0.01 <= intv <= 1.0:
                    DISPAROS_BURST = cant;  INTERVALO_BURST = intv
                    return f"Burst: {cant} c/ {intv:.2f}s"
                return "ERROR: cant 1-20, intv 0.01-1.0"
            except Exception as e:
                return f"ERROR: {e}"

        elif comando.startswith("SET_COLOR "):
            try:
                pts = comando[10:].strip().split()
                if len(pts) != 4:
                    return "ERROR: SET_COLOR <nombre> R G B"
                nombre = pts[0]
                r, g, b = int(pts[1]), int(pts[2]), int(pts[3])
                if not all(0 <= c <= 255 for c in (r, g, b)):
                    return "ERROR: RGB 0-255"
                for pf in perfiles:
                    if pf["nombre"] == nombre:
                        pf["color"] = [r, g, b];  guardar_perfiles()
                        if perfiles[perfil_actual]["nombre"] == nombre:
                            encender_led_perfil()
                        return f"Color {nombre}: ({r},{g},{b})"
                return "ERROR: Perfil no encontrado"
            except Exception as e:
                return f"ERROR: {e}"

        elif comando.startswith("MOVE "):
            return mover_mouse(comando[5:])

        elif comando.startswith("SET_TIME "):
            try:
                pts = comando[9:].strip().split()
                if len(pts) == 1:
                    ts = int(pts[0])
                    offset_tiempo = (ts + UTC_OFFSET) - time.monotonic()
                    t = time.localtime(int(time.monotonic() + offset_tiempo))
                    return f"Hora: {t.tm_hour:02d}:{t.tm_min:02d}:{t.tm_sec:02d}"
                elif len(pts) >= 6:
                    y, mo, d, h, mi = [int(x) for x in pts[:5]]
                    s = int(pts[5]) if len(pts) > 5 else 0
                    ts = _timegm(y, mo, d, h, mi, s)
                    offset_tiempo = (ts + UTC_OFFSET) - time.monotonic()
                    return f"Hora: {h:02d}:{mi:02d}:{s:02d}"
                return "ERROR: SET_TIME <timestamp> | <Y M D h m s>"
            except Exception as e:
                return f"ERROR: {e}"

        elif comando == "GET_TIME":
            try:
                t = time.localtime(int(time.monotonic() + offset_tiempo)) if offset_tiempo else time.localtime()
                if t.tm_year >= 2020:
                    return json.dumps({
                        "hora":  f"{t.tm_hour:02d}:{t.tm_min:02d}:{t.tm_sec:02d}",
                        "fecha": f"{t.tm_year}-{t.tm_mon:02d}-{t.tm_mday:02d}"
                    })
                return json.dumps({"error": "Hora no configurada"})
            except Exception as e:
                return json.dumps({"error": str(e)})

        elif comando == "RESET_STATS":
            disparos_totales_sesion = 0;  resetear_compensacion()
            return "Stats reseteadas"

        elif comando.startswith("READ_FILE "):
            try:
                ruta = comando[10:].strip()
                if not ruta or ".." in ruta or ruta.startswith("/lib"):
                    return "ERROR: Ruta no permitida"
                with open(ruta, "r") as f:
                    contenido = f.read()
                import base64
                return "FILE_CONTENT:" + base64.b64encode(contenido.encode()).decode()
            except FileNotFoundError:
                return "ERROR: Archivo no encontrado"
            except Exception as e:
                return f"ERROR: {e}"

        elif comando.startswith("WRITE_FILE "):
            try:
                pts = comando[11:].strip().split(" ", 1)
                if len(pts) != 2:
                    return "ERROR: WRITE_FILE <ruta> <b64>"
                ruta = pts[0]
                if ".." in ruta or ruta.startswith("/lib"):
                    return "ERROR: Ruta no permitida"
                import base64
                with open(ruta, "w") as f:
                    f.write(base64.b64decode(pts[1]).decode())
                return f"Guardado: {ruta}"
            except Exception as e:
                return f"ERROR: {e}"

        elif comando == "LIST_FILES":
            try:
                resultado = []
                for item in os.listdir("/"):
                    try:
                        st = os.stat("/" + item)
                        resultado.append({
                            "nombre": item,
                            "tipo": "dir" if st[0] & 0o170000 == 0o040000 else "file",
                            "bytes": st[6]
                        })
                    except:
                        pass
                return json.dumps(resultado)
            except Exception as e:
                return f"ERROR: {e}"

        elif comando.startswith("SET_PRECISION "):
            try:
                pts = comando[14:].strip().split()
                if len(pts) != 4:
                    return "ERROR: SET_PRECISION <g> <s> <c> <p> (0/1)"
                USAR_GAUSSIANA       = bool(int(pts[0]))
                SUAVIZAR_MOVIMIENTOS = bool(int(pts[1]))
                COMPENSACION_ACUMULATIVA = bool(int(pts[2]))
                PRECISION_SUB_PIXEL  = bool(int(pts[3]))
                return f"G={USAR_GAUSSIANA} S={SUAVIZAR_MOVIMIENTOS} C={COMPENSACION_ACUMULATIVA} P={PRECISION_SUB_PIXEL}"
            except (ValueError, IndexError):
                return "ERROR: usa 0 o 1"

        else:
            return f"Cmd desconocido: {comando}. Usa HELP"

    except Exception as e:
        return f"ERROR: {e}"

# ============ DISPARO ============
def parpadear_error():
    for _ in range(2):
        pixel[0] = (255, 0, 0);  time.sleep(0.1)
        pixel[0] = (0, 0, 0);    time.sleep(0.1)

def disparar_modo_rapid(perfil):
    global disparos_actual, disparos_total
    disparos_actual = 0
    while not btn_disparo.value:
        disparos_actual += 1;  disparos_total = disparos_actual
        actualizar_pantalla(disparo=True)
        aplicar_recoil(perfil);  mouse.click(Mouse.LEFT_BUTTON)
        time.sleep(rapid_fire_delay)

def disparar_modo_burst(perfil):
    global disparos_actual, disparos_total
    disparos_actual = 0;  disparos_total = DISPAROS_BURST
    for _ in range(DISPAROS_BURST):
        disparos_actual += 1
        actualizar_pantalla(disparo=True)
        aplicar_recoil(perfil);  mouse.click(Mouse.LEFT_BUTTON)
        time.sleep(INTERVALO_BURST)
    while not btn_disparo.value:
        time.sleep(0.01)

def disparar_modo_normal(perfil):
    global disparos_actual, disparos_total
    disparos_actual = disparos_total = 1
    actualizar_pantalla(disparo=True)
    while not btn_disparo.value:
        aplicar_recoil(perfil);  time.sleep(delay_normal)

# ============ DEBOUNCE ============
def boton_presionado(boton, estado_ant):
    """Detecta flanco bajada (True→False). Dispara una sola vez por pulsación.
    Retorna (accion, nuevo_estado_ant)."""
    actual = boton.value   # True=suelto, False=presionado
    accion = (not actual) and estado_ant   # solo en el primer ciclo presionado
    return accion, actual

# ============ INICIALIZACIÓN ============
print("Recoil 128x64 listo. Perfil:", perfiles[perfil_actual]["nombre"])
print("Hold MODO 1.5s → entrar/salir menú")
pantalla_inicio()
encender_led_perfil()
encender_led_modo()
actualizar_pantalla()

compensacion_acumulativa_x = compensacion_acumulativa_y = 0.0
recoil_acum_x = recoil_acum_y = 0.0
contador_disparos_racha = 0
ultimo_reset_compensacion = time.monotonic()

# ============ BUCLE PRINCIPAL ============
while True:
    try:
        ahora = time.monotonic()

        # Timeout conexión serial
        if ahora - ultimo_ping > TIMEOUT_CONEXION:  conexion_flask = False

        # Serial
        if supervisor.runtime.serial_connected and serial.in_waiting:
            try:
                cmd = serial.readline().decode().strip()
                if cmd:
                    serial.write((procesar_comando(cmd, "serial") + "\n").encode())
            except Exception as e:
                print(f"Error serial: {e}")

        # ── BOTÓN MODO (GP8) ─────────────────────────────────────────────
        # Short press → acción según estado  |  Long press → entrar/salir menú
        modo_val = btn_cambio_modo.value
        if not modo_val:   # presionado
            if tiempo_inicio_modo == 0.0:
                tiempo_inicio_modo = ahora
            elif not long_press_modo_detectado and ahora - tiempo_inicio_modo >= LONG_PRESS_TIEMPO:
                long_press_modo_detectado = True
                if estado_sistema == "normal":
                    entrar_menu()
                else:
                    salir_menu()
        else:              # suelto
            if tiempo_inicio_modo > 0.0 and not long_press_modo_detectado:
                # Short press
                if   estado_sistema == "normal":        cambiar_modo_disparo()
                elif estado_sistema == "menu":          menu_abajo()
                elif estado_sistema == "editar_perfil": campo_abajo()
                elif estado_sistema == "editar_valor":  valor_decrementar()
            tiempo_inicio_modo      = 0.0
            long_press_modo_detectado = False

        # ── BOTÓN PERFIL (GP3) ───────────────────────────────────────────
        accion_perf, btn_perfil_anterior = boton_presionado(
            btn_cambio_perfil, btn_perfil_anterior)
        if accion_perf:
            if   estado_sistema == "normal":        cambiar_perfil()
            elif estado_sistema == "menu":          menu_arriba()
            elif estado_sistema == "editar_perfil": campo_arriba()
            elif estado_sistema == "editar_valor":  valor_incrementar()

        # ── BOTÓN DISPARO (GP9) ──────────────────────────────────────────
        if estado_sistema == "normal":
            perfil = perfiles[perfil_actual]
            if not btn_disparo.value and modo_disparo != "off":
                pixel[0] = (0, 255, 0)
                ultimo_disparo = ahora;  estado_pantalla = "hud"
                actualizar_pantalla(disparo=True)
                if   modo_disparo == "rapid":  disparar_modo_rapid(perfil)
                elif modo_disparo == "burst":  disparar_modo_burst(perfil)
                else:                          disparar_modo_normal(perfil)
                actualizar_pantalla()
            else:
                encender_led_perfil()
                if ahora - ultimo_disparo > TIEMPO_A_REPOSO:
                    if estado_pantalla != "reposo":
                        estado_pantalla = "reposo"
                        pantalla_reposo()
                        ultima_actualizacion_reposo = ahora
                    elif ahora - ultima_actualizacion_reposo >= 1.0:
                        pantalla_reposo()
                        ultima_actualizacion_reposo = ahora
                else:
                    if estado_pantalla != "hud":
                        estado_pantalla = "hud";  actualizar_pantalla()
                time.sleep(0.01)
        else:
            # En menú: btn_disparo = SELECCIONAR
            accion_disp, btn_disparo_anterior = boton_presionado(
                btn_disparo, btn_disparo_anterior)
            if accion_disp:
                if   estado_sistema == "menu":          menu_seleccionar()
                elif estado_sistema == "editar_perfil": campo_seleccionar()
                elif estado_sistema == "editar_valor":  valor_confirmar()

        time.sleep(0.005)

    except KeyboardInterrupt:
        raise
    except Exception as err:
        print(f"ERROR GENERAL: {err}")
        parpadear_error()
        time.sleep(0.5)
