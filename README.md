# RP2040 Recoil Compensator

Dispositivo de compensación de recoil para juegos FPS basado en **Raspberry Pi Pico (RP2040)** y **CircuitPython**. Se conecta como mouse USB HID y aplica movimientos automáticos del mouse mientras el jugador mantiene pulsado el botón de disparo, compensando el retroceso de las armas.

---

## Características

- Compensación de recoil por perfil de arma (ajuste X/Y + variación gaussiana)
- 3 modos de disparo: **Normal**, **Rapid Fire** y **Burst**
- LED NeoPixel con color por perfil y por modo
- Pantalla OLED con HUD en tiempo real
- Animación al cambiar de perfil con nombre del arma en pantalla
- Perfiles editables por comandos Serial USB o desde botones físicos (versión 128×64)
- Guardado de perfiles en `perfiles.json`
- Configuración sin tocar el código mediante `settings.toml`
- Se identifica ante el PC como *Logitech USB Optical Mouse*
- La unidad `CIRCUITPY` **no aparece** en el PC (oculta por `storage.disable_usb_drive()`)

---

## Versiones

| Carpeta | Pantalla | Menú físico |
|---|---|---|
| `RP2040 Pantalla 128x32/` | SSD1306 128×32 | No |
| `RP2040 Pantalla 128x64/` | SSD1306 128×64 | Sí — navegar y editar perfiles con botones |

---

## Hardware

| Componente | Modelo |
|---|---|
| Microcontrolador | Raspberry Pi Pico / RP2040 |
| Pantalla | SSD1306 OLED I2C (128×32 o 128×64) |
| LED | NeoPixel WS2812 (1 LED) |

### Pines

| Función | Pin (128×32) | Pin (128×64) |
|---|---|---|
| Botón disparo | GP9 | GP9 |
| Botón cambio perfil | GP3 | GP2 |
| Botón cambio modo | GP8 | GP8 |
| NeoPixel | GP16 | GP16 |
| OLED SDA | GP4 | GP4 |
| OLED SCL | GP5 | GP5 |

> Todos los botones usan pull-up interno; conectar entre el pin y GND.

> **Nota:** En la versión 128×64 el botón de perfil usa GP2 en lugar de GP3. El pin GP3 es SWDIO (debug del RP2040) y puede causar conflictos.

---

## Instalación

### Requisitos
- [CircuitPython 8+](https://circuitpython.org/board/raspberry_pi_pico/) instalado en el Pico
- Librerías en la carpeta `lib/`:
  - `adafruit_hid`
  - `adafruit_neopixel`
  - `adafruit_displayio_ssd1306`
  - `adafruit_display_text`
  - `adafruit_display_shapes`
  - `adafruit_imageload`

### Pasos
1. Copiar todo el contenido de la carpeta del proyecto elegido a la raíz de `CIRCUITPY`
2. Desconectar y reconectar el USB para que `boot.py` surta efecto
3. El dispositivo queda listo — la unidad `CIRCUITPY` ya no aparecerá en el PC

---

## Configuración — `boot.py`

El `boot.py` configura el USB antes de que CircuitPython inicie el código principal:

```python
storage.disable_usb_drive()               # Oculta CIRCUITPY del PC y da escritura al Pico
usb_cdc.enable(console=True, data=False)  # Solo consola serial
usb_hid.enable((usb_hid.Device.MOUSE,))  # Solo mouse HID
supervisor.set_usb_identification(...)    # Identidad Logitech
```

> **Importante:** `storage.disable_usb_drive()` reemplaza a `storage.remount()`. No deben usarse juntos — `remount` puede contrarrestar el ocultamiento de la unidad. Con `disable_usb_drive()` el Pico tiene acceso de escritura completo al filesystem sin necesitar `remount`.

### Recuperar acceso a los archivos

Para editar archivos directamente cuando la unidad está oculta:

1. Mantener presionado **BOOTSEL** al conectar USB → aparece la unidad `RPI-RP2`
2. Copiar el `boot.py` con `storage.disable_usb_drive()` comentado
3. Reconectar → aparece `CIRCUITPY` para editar normalmente
4. Volver a activar `storage.disable_usb_drive()` cuando termines

---

## Configuración — `settings.toml`

Editar sin tocar el código principal:

```toml
UTC_OFFSET               = "-18000"   # Zona horaria en segundos (Colombia UTC-5)
TIEMPO_A_REPOSO          = "3.0"      # Segundos sin disparar para entrar en reposo
DEBOUNCE_BOTONES         = "0.15"     # Tiempo de debounce en segundos
LONG_PRESS_TIEMPO        = "1.5"      # Segundos para activar long press (versión 128×64)
USAR_GAUSSIANA           = "1"        # Distribución gaussiana para variación de recoil
SUAVIZAR_MOVIMIENTOS     = "1"        # Suavizado de movimientos grandes
COMPENSACION_ACUMULATIVA = "1"        # Compensación de drift acumulativo
PRECISION_SUB_PIXEL      = "1"        # Acumulación de fracciones de píxel
```

---

## Perfiles — `perfiles.json`

Cada perfil define el comportamiento del recoil para un arma:

```json
{
  "nombre": "Ar",
  "ajuste_x": -1,
  "ajuste_y": 6,
  "variacion": 0.2,
  "color": [0, 255, 255],
  "imagen": "/ar.bmp"
}
```

| Campo | Descripción |
|---|---|
| `ajuste_x` | Movimiento horizontal del mouse por disparo |
| `ajuste_y` | Movimiento vertical del mouse por disparo |
| `variacion` | Aleatoriedad aplicada (radio de dispersión gaussiana) |
| `color` | Color del LED NeoPixel `[R, G, B]` |
| `imagen` | Ruta al BMP mostrado en la pantalla OLED al cambiar perfil |

### Perfiles incluidos

| Nombre | AjX | AjY | Var | Color |
|---|---|---|---|---|
| Default | 0 | 5 | 0.30 | Azul |
| sniper | 0 | 10 | 0.10 | Rojo |
| smg | 1 | 3 | 0.40 | Verde |
| Ar | -1 | 6 | 0.20 | Cian |
| Pistol | 2 | 4 | 0.35 | Magenta |

---

## Menú físico (versión 128×64)

Mantener pulsado **MODO (GP8) durante 1.5 s** para entrar/salir del menú.

```
Hold MODO → MENU PRINCIPAL
              ├─ [Nombre perfil] → EDITAR PERFIL
              │     ├─ AjX  →  EDITAR VALOR
              │     ├─ AjY  →  EDITAR VALOR
              │     ├─ Var  →  EDITAR VALOR
              │     ├─ [Guardar perfil]
              │     └─ [Cancelar]
              ├─ [Guardar y Salir]
              └─ [Salir sin Guardar]
```

| Botón | Normal | Menú / Editar perfil | Editar valor |
|---|---|---|---|
| PERFIL (GP2) | Siguiente perfil | Cursor arriba | Incrementar (+) |
| MODO (GP8) corto | Cambiar modo | Cursor abajo | Decrementar (−) |
| MODO (GP8) largo | Entrar menú | Salir al HUD | — |
| DISPARO (GP9) | Disparar | Seleccionar | Confirmar |

---

## Comandos Serial

Conectar por monitor serial a **115200 baud**:

| Comando | Descripción |
|---|---|
| `LIST` | Lista todos los perfiles en JSON |
| `GET_STATUS` | Estado actual del sistema |
| `GET_CONFIG` | Configuración de delays y burst |
| `SET <nombre>` | Activar perfil por nombre |
| `SAVE <json>` | Agregar o actualizar perfil |
| `DEL <nombre>` | Eliminar perfil |
| `SET_MODE <modo>` | Cambiar modo: `normal` `rapid` `burst` `off` |
| `SET_DELAY <val>` | Delay de rapid fire en segundos (0.001–1.0) |
| `SET_BURST <n> <intervalo>` | Configurar modo burst |
| `SET_COLOR <nombre> R G B` | Cambiar color LED del perfil |
| `MOVE <dx> <dy>` | Mover el mouse manualmente |
| `SET_TIME <timestamp>` | Establecer hora (Unix timestamp) |
| `GET_TIME` | Obtener hora actual |
| `RESET_STATS` | Resetear estadísticas de sesión |
| `LIST_FILES` | Listar archivos en el sistema |
| `READ_FILE <ruta>` | Leer archivo (devuelve base64) |
| `WRITE_FILE <ruta> <b64>` | Escribir archivo (contenido en base64) |
| `SET_PRECISION <g> <s> <c> <p>` | Ajustar flags de precisión (0 o 1) |
| `HELP` | Lista de comandos disponibles |

---

## Modos de disparo

| Modo | Comportamiento | LED |
|---|---|---|
| `normal` | Aplica recoil mientras se mantiene el botón | Azul |
| `rapid` | Auto-click repetido con delay configurable | Naranja |
| `burst` | N disparos automáticos por pulsación | Magenta |
| `off` | Deshabilita el recoil completamente | Gris oscuro |

---

## Servidor Web (opcional)

La carpeta `Servidor serial/` contiene un servidor Flask que actúa como puente entre el RP-RC y una interfaz web o app móvil. Ver [Servidor serial/README.md](Servidor%20serial/README.md) para más detalles.

---

## Compatibilidad CircuitPython

El proyecto resuelve varias limitaciones de CircuitPython frente a Python estándar:

| Limitación | Solución aplicada |
|---|---|
| `random.gauss` no existe | Implementado con algoritmo Box-Muller |
| `import calendar` no disponible | Función `_timegm()` propia |
| `displayio.I2CDisplay` movido en CP8+ | Fallback automático a `i2cdisplaybus.I2CDisplayBus` |
| Atributos en funciones no soportados | Variables globales `recoil_acum_x/y` |
| `bytes.decode(errors=...)` no soportado | Filtro manual de bytes ASCII |
| `storage.remount` + `disable_usb_drive` conflicto | Usar solo `disable_usb_drive()` en boot.py |
| `json.dump()` escritura incremental incompleta | Reemplazado por `f.write(json.dumps(...))` atómico |
| GP3 (SWDIO) conflicto en versión 128×64 | Botón de perfil movido a GP2 |

---

## Estructura del proyecto

```
├── Completo y Final/
│   ├── boot.py           # USB HID, disable_usb_drive, identidad Logitech
│   ├── code.py           # Código principal (pantalla 128×32)
│   ├── settings.toml     # Configuración editable sin tocar el código
│   ├── perfiles.json     # Perfiles de armas
│   ├── *.bmp             # Imágenes para la pantalla OLED
│   └── lib/              # Librerías de CircuitPython
├── RP2040 Pantalla 128x64/
│   ├── boot.py           # USB HID, disable_usb_drive, identidad Logitech
│   ├── code.py           # Código principal (pantalla 128×64 + menú físico)
│   ├── settings.toml
│   ├── perfiles.json
│   ├── *.bmp
│   └── lib/
└── Servidor serial/
    ├── Servidor.pyw      # Servidor Flask + GUI tkinter
    └── web/
        └── index.html    # Interfaz web de control
```

---

## Licencia

**Terrycris Dual License v1.0** — uso personal y educativo libre, uso comercial requiere permiso del autor.

Ver [LICENSE](LICENSE) para los términos completos.  
Contacto para licencias comerciales: [github.com/Terrycris](https://github.com/Terrycris)
