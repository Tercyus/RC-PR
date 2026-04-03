# RP-RC Servidor Serial

Servidor puente que conecta el dispositivo **RP-RC** (Raspberry Pi Pico) con una interfaz web o app móvil. Expone una API HTTP REST que traduce las peticiones a comandos por puerto serial, y sirve la interfaz web integrada.

---

## Arquitectura

```
Navegador / App móvil
        │  HTTP (puerto 5000)
        ▼
  Servidor Flask (s.pyw)
        │  Serial USB 115200 baud
        ▼
    RP-RC (RP2040)
```

---

## Requisitos

### Python 3.8+
```
pip install flask flask-cors pyserial
```

### Dependencias
| Paquete | Uso |
|---|---|
| `flask` | Servidor HTTP REST |
| `flask-cors` | Permite peticiones desde otros orígenes (app móvil) |
| `pyserial` | Comunicación con el RP-RC por USB serial |
| `tkinter` | GUI de selección de puerto (incluido con Python) |

---

## Uso

1. Conectar el RP-RC por USB
2. Ejecutar el servidor:
   ```
   pythonw Servidor.pyw
   ```
   o doble clic en `Servidor.pyw`
3. Seleccionar el puerto COM del RP-RC en el desplegable
4. Presionar **Iniciar**
5. Abrir el navegador en `http://<IP mostrada>:5000`

> La IP del equipo se muestra en la ventana de selección de puerto. Usar esa dirección para acceder desde el celular u otro dispositivo en la misma red.

### Cerrar el servidor
Presionar **F8** en la ventana de selección de puerto.

---

## Interfaz web

La interfaz web está en `web/index.html` y es servida automáticamente por Flask en la ruta raíz `/`.

Funcionalidades:
- Indicador de estado de conexión (conectado / desconectado)
- Selección de modo de disparo: Normal, Rapid Fire, Burst, Off
- Listado de perfiles con botón de activar
- Crear y editar perfiles (nombre, AjX, AjY, variación, color LED)
- Eliminar perfiles
- Botón de reconexión manual

---

## API REST

Todas las rutas aceptan y devuelven JSON.

### Estado y conexión

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/` | Sirve la interfaz web (`index.html`) |
| GET | `/ping` | Verificar que el servidor está activo (`OK`) |
| GET | `/estado` | Estado de la conexión serial (`conectado` / `desconectado`) |
| POST | `/reconectar` | Forzar reconexión al RP-RC |

### Puertos

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/listar_puertos` | Lista los puertos COM disponibles |
| POST | `/set_port` | Configurar el puerto a usar `{"puerto": "COM3"}` |

### Perfiles

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/listar` | Lista todos los perfiles del RP-RC |
| GET | `/activo` | Nombre del perfil actualmente activo |
| POST | `/activar` | Activar un perfil `{"nombre": "Ar"}` |
| POST | `/guardar` | Crear o actualizar un perfil (objeto perfil completo) |
| POST | `/eliminar` | Eliminar un perfil `{"nombre": "Ar"}` |

### Modo de disparo

| Método | Ruta | Descripción |
|---|---|---|
| POST | `/set-modo` | Cambiar modo `{"modo": "normal"}` — valores: `normal` `rapid` `burst` `off` |

### Comandos directos

| Método | Ruta | Descripción |
|---|---|---|
| POST | `/comando` | Enviar cualquier comando al RP-RC `{"cmd": "GET_STATUS"}` |

---

## Ejemplos de uso con curl

```bash
# Listar perfiles
curl http://localhost:5000/listar

# Activar perfil
curl -X POST http://localhost:5000/activar \
     -H "Content-Type: application/json" \
     -d '{"nombre": "Ar"}'

# Cambiar a modo rapid
curl -X POST http://localhost:5000/set-modo \
     -H "Content-Type: application/json" \
     -d '{"modo": "rapid"}'

# Comando directo
curl -X POST http://localhost:5000/comando \
     -H "Content-Type: application/json" \
     -d '{"cmd": "GET_STATUS"}'
```

---

## Notas técnicas

- El servidor usa **115200 baud** para coincidir con el RP-RC
- La conexión serial es **persistente** — se reconecta automáticamente si se pierde
- Las respuestas del RP-RC se leen con timeout de **3 segundos**, esperando `\n` final
- La ventana tkinter se oculta automáticamente al iniciar el servidor; la consola de Windows también se oculta
- El servidor escucha en `0.0.0.0:5000` — accesible desde cualquier dispositivo en la red local

---

## Estructura

```
Servidor serial/
├── Servidor.pyw    # Servidor Flask + GUI tkinter (ejecutar directamente)
├── web/
│   └── index.html  # Interfaz web dark-theme
└── README.md
```
