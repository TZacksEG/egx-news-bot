#!/usr/bin/env bash
set -euo pipefail

DRY_RUN=0
if [[ "${1:-}" == "--dry-run" ]]; then
  DRY_RUN=1
  shift
fi

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
ROOT_DIR="$(cd -- "${APP_DIR}/.." && pwd)"

if [[ -n "${EGX_NEWS_BOT_CONFIG:-}" ]]; then
  CONFIG_FILE="${EGX_NEWS_BOT_CONFIG}"
else
  CONFIG_FILE="${APP_DIR}/.env"
  if [[ ! -f "${CONFIG_FILE}" && -f "${ROOT_DIR}/ProjectSecrets.env" ]]; then
    CONFIG_FILE="${ROOT_DIR}/ProjectSecrets.env"
  fi
fi

if [[ ! -f "${CONFIG_FILE}" ]]; then
  {
    echo "Config file not found: ${CONFIG_FILE}"
    echo "Create one with: cp ${APP_DIR}/config.example.env ${APP_DIR}/.env"
  } >&2
  exit 2
fi

set -a
# shellcheck disable=SC1090
source "${CONFIG_FILE}"
set +a

PYTHON_BIN="${EGX_NEWS_BOT_PYTHON:-${APP_DIR}/.venv/bin/python}"
if [[ ! -x "${PYTHON_BIN}" ]]; then
  PYTHON_BIN="$(command -v python3)"
fi

TIMEOUT_SECONDS="${EGX_NEWS_BOT_FEEDBACK_LONG_POLL_TIMEOUT:-25}"
if ! [[ "${TIMEOUT_SECONDS}" =~ ^[0-9]+$ ]] || [[ "${TIMEOUT_SECONDS}" -lt 1 ]] || [[ "${TIMEOUT_SECONDS}" -gt 50 ]]; then
  echo "EGX_NEWS_BOT_FEEDBACK_LONG_POLL_TIMEOUT must be a number between 1 and 50" >&2
  exit 2
fi

if [[ "${DRY_RUN}" == "1" ]]; then
  printf 'EGX_NEWS_BOT_CONFIG=%q PYTHONPATH=%q %q' "${CONFIG_FILE}" "${APP_DIR}/src" "${PYTHON_BIN}"
  printf ' -m egx_news_bot.cli collect-feedback --timeout %q\n' "${TIMEOUT_SECONDS}"
  exit 0
fi

cd "${APP_DIR}"
export PYTHONPATH="${APP_DIR}/src${PYTHONPATH:+:${PYTHONPATH}}"
while true; do
  if ! "${PYTHON_BIN}" -m egx_news_bot.cli collect-feedback --timeout "${TIMEOUT_SECONDS}"; then
    echo "[$(date -Is)] Telegram feedback listener failed; retrying in 5s" >&2
    sleep 5
  fi
done
