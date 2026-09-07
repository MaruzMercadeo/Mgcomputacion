# MGComputacion Platform Starter

Base profesional en **Flask + SQLite** para desarrollar en **Windows local** y desplegar después en **Ubuntu VPS**.

Incluye:

- sitio público base
- registro de clientes
- login con aprobación manual por admin
- panel del cliente
- panel del administrador
- empresa por cliente
- productos por cliente
- categorías principales y secundarias
- configuración del agente IA por cliente
- carga de PDF con previsualización básica
- API protegida por API Key para integraciones de agentes
- comandos CLI para iniciar base de datos, crear admin y generar API keys

## 1. Requisitos

- Python 3.11+
- pip
- entorno virtual (`venv`)

## 2. Instalación local (Windows)

```powershell
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
flask --app run.py init-db
flask --app run.py seed-admin --email admin@mg.local --password Admin123! --name "Administrador"
flask --app run.py run
```

La app quedará en:

- http://127.0.0.1:5000

## 3. Instalación local (Ubuntu)

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
flask --app run.py init-db
flask --app run.py seed-admin --email admin@mg.local --password Admin123! --name "Administrador"
python run.py
```

Con `HOST=0.0.0.0` (valor por defecto) la app queda visible para el resto de
equipos de tu red local. Ver la seccion 12.

## 4. Usuario administrador

Crea el primer admin con el comando:

```bash
flask --app run.py seed-admin --email admin@mg.local --password Admin123! --name "Administrador"
```

## 5. Flujo principal

### Cliente
1. entra a `/register`
2. crea su cuenta y empresa
3. queda en estado `pending`
4. cuando el admin lo aprueba, ya puede entrar al panel

### Admin
1. entra con su cuenta admin
2. revisa `/admin/users`
3. aprueba, rechaza o deshabilita usuarios

## 6. Estructura

```text
mgcomputacion_platform/
├── app/
│   ├── blueprints/
│   ├── services/
│   ├── static/
│   ├── templates/
│   ├── __init__.py
│   ├── cli.py
│   ├── decorators.py
│   ├── extensions.py
│   ├── models.py
│   └── utils.py
├── config.py
├── instance/
├── requirements.txt
├── run.py
└── .env.example
```

## 7. API para agentes IA

Autenticación por header:

```http
X-API-Key: TU_API_KEY
```

Endpoints base:

- `GET /api/v1/health`
- `GET /api/v1/company`
- `PUT /api/v1/company`
- `GET /api/v1/agent-settings`
- `PUT /api/v1/agent-settings`
- `GET /api/v1/categories`
- `POST /api/v1/categories`
- `GET /api/v1/products`
- `GET /api/v1/products/<id>`
- `POST /api/v1/products`
- `PUT /api/v1/products/<id>`
- `DELETE /api/v1/products/<id>`
- `POST /api/v1/pdf/upload`

## 8. Generar API key

Desde una shell de Flask:

```bash
flask --app run.py generate-api-key --company-id 1 --label openclaw
```

Ese comando devuelve la clave **una sola vez**. Guarda la salida.

## 9. Qué queda listo y qué debes ajustar

### Ya listo
- estructura base
- auth
- roles
- paneles
- CRUD básico
- API protegida
- subida de archivos
- separación por empresa

### Ajustes recomendados
- endurecer validaciones de negocio
- cambiar SQLite a PostgreSQL en producción
- agregar CSRF real con Flask-WTF
- agregar procesamiento PDF más avanzado
- conectar almacenamiento externo si crecerá mucho
- poner Gunicorn + Nginx en el VPS

## 10. Producción en VPS Ubuntu

Recomendado:

- Gunicorn
- Nginx
- variables `.env`
- `DEBUG=False`
- PostgreSQL en lugar de SQLite si el sistema crece
- HTTPS con Let's Encrypt

## 11. Notas

- El logo original está integrado en `app/static/img/logo-mg.png`
- Las imágenes de productos se suben a `app/static/uploads/products/`
- Los PDFs se suben a `app/static/uploads/pdfs/`
- La importación de PDF está en fase base con extracción de texto y preview

## 12. Acceso desde la red local (LAN)

Para entrar desde otro equipo, celular o tablet de la misma red hacia el Ubuntu
donde corre la app.

### 12.1 Levantar el servidor

```bash
./scripts/serve-lan.sh          # gunicorn, recomendado
./scripts/serve-lan.sh --dev    # servidor de desarrollo de Flask
PORT=8080 ./scripts/serve-lan.sh
```

El script activa `venv` si existe, muestra la IP local, avisa si `ufw` bloquea el
puerto y levanta el servidor en `0.0.0.0`.

Tambien sirve `python run.py`, que lee `HOST` y `PORT` del `.env`.

### 12.2 Averiguar la IP del Ubuntu

```bash
hostname -I
# o
ip -4 addr show scope global | grep inet
```

Suele ser algo como `192.168.1.45`. Desde otro equipo de la red:

```text
http://192.168.1.45:5555
```

### 12.3 Abrir el puerto en el firewall

Si `ufw` esta activo:

```bash
sudo ufw status
sudo ufw allow 5555/tcp
```

Para permitir solo tu subred en lugar de todo:

```bash
sudo ufw allow from 192.168.1.0/24 to any port 5555 proto tcp
```

### 12.4 Si no conecta

1. Confirma que el servidor dice `0.0.0.0` y no `127.0.0.1`.
2. Comprueba que el puerto escucha: `ss -lntp | grep 5555`.
3. Prueba desde el propio Ubuntu con su IP de red: `curl http://192.168.1.45:5555`.
   - Si responde ahi pero no desde otro equipo, es firewall o aislamiento del router.
4. Verifica que ambos equipos esten en la misma red y que el router no tenga
   activado el aislamiento de clientes (AP isolation / red de invitados).
5. Si el Ubuntu esta en WSL o en una VM con NAT, necesitas reenvio de puertos o
   red en modo puente.

### 12.5 Seguridad

- La app quedara accesible para cualquier equipo de la red. Usa contrasenas
  reales, no las de ejemplo, y cambia `SECRET_KEY`.
- No pongas `FLASK_DEBUG=1` con `HOST=0.0.0.0`: el depurador de Werkzeug permite
  ejecutar codigo desde el navegador. Por eso `run.py` activa debug por defecto
  solo cuando `HOST` es `127.0.0.1`.
- Para acceso permanente, usa gunicorn detras de nginx y un servicio de systemd
  en vez de dejar una terminal abierta.
- Esto es solo red local. Para acceso desde internet necesitas dominio, HTTPS y
  reenvio de puertos en el router, no expongas esto tal cual.

### 12.6 Servicio systemd (opcional)

```ini
# /etc/systemd/system/mgcomputacion.service
[Unit]
Description=MGComputacion Platform
After=network.target

[Service]
User=TU_USUARIO
WorkingDirectory=/ruta/a/Mgcomputacion
Environment="PATH=/ruta/a/Mgcomputacion/venv/bin"
ExecStart=/ruta/a/Mgcomputacion/venv/bin/gunicorn --bind 0.0.0.0:5555 --workers 3 run:app
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now mgcomputacion
sudo systemctl status mgcomputacion
```
