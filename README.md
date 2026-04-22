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

- http://127.0.0.1:5555

## 3. Instalación local (Ubuntu)

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
flask --app run.py init-db
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
