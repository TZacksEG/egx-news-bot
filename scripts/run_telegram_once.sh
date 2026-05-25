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

feedback_args=(
  -m egx_news_bot.cli collect-feedback
  --timeout "${EGX_NEWS_BOT_FEEDBACK_TIMEOUT:-0}"
)

send_args=(
  -m egx_news_bot.cli send-telegram
  --limit "${EGX_NEWS_BOT_LIMIT:-20}"
  --min-strength "${EGX_NEWS_BOT_MIN_STRENGTH:-65}"
  --max-age-hours "${EGX_NEWS_BOT_MAX_AGE_HOURS:-72}"
  --analysis-mode "${EGX_NEWS_BOT_ANALYSIS_MODE:-ai}"
)

case "${EGX_NEWS_BOT_INCLUDE_REVIEW:-false}" in
  1|true|TRUE|yes|YES)
    send_args+=(--include-review)
    ;;
esac

if [[ "${DRY_RUN}" == "1" ]]; then
  printf 'EGX_NEWS_BOT_CONFIG=%q PYTHONPATH=%q %q' "${CONFIG_FILE}" "${APP_DIR}/src" "${PYTHON_BIN}"
  printf ' %q' "${feedback_args[@]}"
  printf '\n'
  printf 'EGX_NEWS_BOT_CONFIG=%q PYTHONPATH=%q %q' "${CONFIG_FILE}" "${APP_DIR}/src" "${PYTHON_BIN}"
  printf ' %q' "${send_args[@]}"
  printf '\n'
  exit 0
fi

cd "${APP_DIR}"
export PYTHONPATH="${APP_DIR}/src${PYTHONPATH:+:${PYTHONPATH}}"
if ! "${PYTHON_BIN}" "${feedback_args[@]}"; then
  echo "Telegram feedback collection failed; continuing to send alerts." >&2
fi
exec "${PYTHON_BIN}" "${send_args[@]}"
