#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${1:-/home/rg/htf-scanner}"
SERVICE_USER="${HTF_SCANNER_USER:-rg}"
PYTHON_BIN="${PYTHON_BIN:-python3.12}"
UNIT_DIR="/etc/systemd/system"
ENV_FILE="/etc/htf-scanner.env"

if [[ "${EUID}" -ne 0 ]]; then
  echo "deploy/install.sh must run as root" >&2
  exit 1
fi
if [[ ! -f "${PROJECT_DIR}/pyproject.toml" ]]; then
  echo "Project not found at ${PROJECT_DIR}; clone or copy it there first" >&2
  exit 1
fi
if ! id -u "${SERVICE_USER}" >/dev/null 2>&1; then
  echo "Service user ${SERVICE_USER} does not exist; create it before installation" >&2
  exit 1
fi
SERVICE_GROUP="$(id -gn "${SERVICE_USER}")"
if ! runuser -u "${SERVICE_USER}" -- test -w "${PROJECT_DIR}"; then
  echo "Project directory must be writable by ${SERVICE_USER}: ${PROJECT_DIR}" >&2
  exit 1
fi

install -d -o "${SERVICE_USER}" -g "${SERVICE_GROUP}" \
  "${PROJECT_DIR}/data" "${PROJECT_DIR}/data/candles" "${PROJECT_DIR}/data/state" \
  "${PROJECT_DIR}/reports" "${PROJECT_DIR}/reports/live"

if [[ ! -x "${PROJECT_DIR}/.venv/bin/python" ]]; then
  runuser -u "${SERVICE_USER}" -- "${PYTHON_BIN}" -m venv "${PROJECT_DIR}/.venv"
fi
runuser -u "${SERVICE_USER}" -- "${PROJECT_DIR}/.venv/bin/pip" install --upgrade pip
runuser -u "${SERVICE_USER}" -- "${PROJECT_DIR}/.venv/bin/pip" install -e "${PROJECT_DIR}"

if [[ ! -f "${PROJECT_DIR}/config.production.yaml" ]]; then
  install -m 0644 "${PROJECT_DIR}/config.production.example.yaml" \
    "${PROJECT_DIR}/config.production.yaml"
fi
if [[ ! -f "${ENV_FILE}" ]]; then
  install -m 0640 -o root -g "${SERVICE_GROUP}" \
    "${PROJECT_DIR}/deploy/systemd/htf-scanner.env.example" "${ENV_FILE}"
fi
chown root:"${SERVICE_GROUP}" "${ENV_FILE}"
chmod 0640 "${ENV_FILE}"

sed \
  -e "s|User=rg|User=${SERVICE_USER}|" \
  -e "s|/home/rg/htf-scanner|${PROJECT_DIR}|g" \
  "${PROJECT_DIR}/deploy/systemd/htf-scanner.service" \
  > "${UNIT_DIR}/htf-scanner.service"
install -m 0644 "${PROJECT_DIR}/deploy/systemd/htf-scanner.timer" \
  "${UNIT_DIR}/htf-scanner.timer"
systemctl daemon-reload

echo "Installed HTF scanner. Next:"
echo "1. Edit ${PROJECT_DIR}/config.production.yaml"
echo "2. Set Telegram credentials in ${ENV_FILE}"
echo "3. Run doctor and the first manual bootstrap as documented in DEPLOYMENT.md"
echo "The timer was not enabled automatically."
