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
flask --app run.py db upgrade
flask --app run.py seed-admin --email admin@mg.local --password Admin123! --name "Administrador"
flask --app run.py run
```

> Si ya tenías la base de datos funcionando **antes** de que existieran las migraciones (versiones anteriores usaban `flask init-db`), márcala como baseline una sola vez y luego aplica las nuevas migraciones:
>
> ```powershell
> flask --app run.py db stamp bb0ccbd48cf3
> flask --app run.py db upgrade
> ```

La app quedará en:

- http://127.0.0.1:5555

### 2.1 Autoarranque al iniciar Windows (opcional)

Para que la app levante sola cada vez que inicias sesión en Windows (útil para desarrollo continuo sin tener que tipear `flask run` a mano):

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_autostart.ps1
```

Esto crea un shortcut en la carpeta de inicio (`shell:startup`) que ejecuta `scripts\start_server.vbs`. El wrapper `.vbs` lanza `scripts\start_server.bat` **sin ventana de consola visible**, activa el venv y corre `flask run`.

Logs de la app van a `logs\flask.log`.

Para quitar el autoarranque:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\uninstall_autostart.ps1
```

**Requisitos previos**: `venv\` y `requirements.txt` ya instalados. El script copia `.env.example` a `.env` si no existe.

**Importante**: el autoarranque solo levanta la app cuando la PC está encendida y con sesión iniciada. Si apagas la PC, la app se apaga con ella. Para 24/7 real, desplegar en un VPS (ver sección 10).

## 3. Instalación local (Ubuntu)

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
flask --app run.py db upgrade
flask --app run.py seed-admin --email admin@mg.local --password Admin123! --name "Administrador"
flask --app run.py run --host 0.0.0.0 --port 5555
```

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

### Importación unificada (PDF / CSV / imagen)

Flujo en dos pasos: subir → revisar drafts → commitear.

- `POST /api/v1/imports/upload` — multipart, field `file`. Acepta `.pdf`, `.csv`, `.png/.jpg/.jpeg/.webp/.gif`. Responde `201` con el `import_job` y los `items` generados como `draft`.
- `GET /api/v1/imports/<id>` — devuelve el job y sus items. Bloquea con `403` si el job no pertenece a la empresa de la API key.
- `POST /api/v1/imports/<id>/commit` — convierte los drafts en productos reales. Body opcional `{"item_ids":[1,2,3]}` para commit selectivo. Los duplicados (por SKU, o por nombre+precio) quedan como `skipped`.

CSV reconoce columnas: `nombre/name`, `precio/price`, `descripcion`, `sku`, `stock`, `categoria`, `subcategoria`, `imagen`. Separador auto-detectado (`, ; \t |`).

El endpoint legacy `POST /api/v1/pdf/upload` sigue funcionando igual (crea productos de una pasada, sin staging).

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
