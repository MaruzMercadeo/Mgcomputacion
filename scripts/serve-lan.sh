#!/usr/bin/env bash
# Levanta MGComputacion accesible desde la red local (Ubuntu).
#
#   ./scripts/serve-lan.sh            -> gunicorn (recomendado)
#   ./scripts/serve-lan.sh --dev      -> servidor de desarrollo de Flask
#   PORT=8080 ./scripts/serve-lan.sh  -> otro puerto
set -euo pipefail

cd "$(dirname "$0")/.."

PORT="${PORT:-5555}"
MODE="${1:-}"

if [ -d venv ]; then
  # shellcheck disable=SC1091
  source venv/bin/activate
fi

LAN_IP="$(ip route get 1.1.1.1 2>/dev/null | awk '{print $7; exit}')"
[ -z "${LAN_IP}" ] && LAN_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"

echo ""
echo "  IP local : ${LAN_IP:-no detectada}"
echo "  Puerto   : ${PORT}"
echo "  URL red  : http://${LAN_IP:-<ip>}:${PORT}"
echo ""

if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -q "^Status: active"; then
  if ! ufw status | grep -q "${PORT}/tcp"; then
    echo "  ufw esta activo y el puerto ${PORT} no esta permitido. Abrelo con:"
    echo "    sudo ufw allow ${PORT}/tcp"
    echo ""
  fi
fi

if [ "${MODE}" = "--dev" ]; then
  exec flask --app run.py run --host 0.0.0.0 --port "${PORT}"
fi

exec gunicorn --bind "0.0.0.0:${PORT}" --workers 3 "run:app"
