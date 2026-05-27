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
RUNNER="${SCRIPT_DIR}/run_telegram_once.sh"

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

INTERVAL_SECONDS="${EGX_NEWS_BOT_PM2_INTERVAL_SECONDS:-}"
if [[ -z "${INTERVAL_SECONDS}" ]]; then
  INTERVAL_MINUTES="${EGX_NEWS_BOT_CRON_INTERVAL:-5}"
  if ! [[ "${INTERVAL_MINUTES}" =~ ^[0-9]+$ ]] || [[ "${INTERVAL_MINUTES}" -lt 1 ]]; then
    echo "EGX_NEWS_BOT_CRON_INTERVAL must be a positive number of minutes" >&2
    exit 2
  fi
  INTERVAL_SECONDS="$((INTERVAL_MINUTES * 60))"
fi

if ! [[ "${INTERVAL_SECONDS}" =~ ^[0-9]+$ ]] || [[ "${INTERVAL_SECONDS}" -lt 60 ]]; then
  echo "EGX_NEWS_BOT_PM2_INTERVAL_SECONDS must be a number >= 60" >&2
  exit 2
fi

if [[ "${DRY_RUN}" == "1" ]]; then
  echo "runner=${RUNNER}"
  echo "config=${CONFIG_FILE}"
  echo "interval_seconds=${INTERVAL_SECONDS}"
  exit 0
fi

mkdir -p "${APP_DIR}/logs"
while true; do
  echo "[$(date -Is)] Starting EGX News Bot cycle"
  if ! EGX_NEWS_BOT_CONFIG="${CONFIG_FILE}" "${RUNNER}"; then
    echo "[$(date -Is)] EGX News Bot cycle failed; retrying after ${INTERVAL_SECONDS}s" >&2
  fi
  sleep "${INTERVAL_SECONDS}"
done

