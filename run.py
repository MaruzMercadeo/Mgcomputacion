import os
import socket

from dotenv import load_dotenv
load_dotenv()

from app import create_app

app = create_app()

LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _as_bool(value, default=False):
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on", "si"}


def _lan_ip():
    """IP de esta maquina en la red local (no abre conexion real)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except OSError:
        return None
    finally:
        sock.close()


def _print_urls(host, port, debug):
    print(f"\n  MGComputacion escuchando en {host}:{port}\n")
    print(f"  Local:  http://127.0.0.1:{port}")
    if host in ("0.0.0.0", "::"):
        ip = _lan_ip()
        if ip:
            print(f"  Red:    http://{ip}:{port}")
        else:
            print("  Red:    no se pudo detectar la IP local")
        if debug:
            print("\n  AVISO: debug activo y expuesto a la red local.")
            print("  El depurador de Werkzeug permite ejecutar codigo. Usalo solo en red de confianza.")
    print("")


if __name__ == "__main__":
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "5555"))
    debug = _as_bool(os.getenv("FLASK_DEBUG"), default=host in LOOPBACK_HOSTS)

    if os.getenv("WERKZEUG_RUN_MAIN") != "true":
        _print_urls(host, port, debug)

    app.run(host=host, port=port, debug=debug)
