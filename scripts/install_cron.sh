#!/usr/bin/env bash
set -euo pipefail

DRY_RUN=0
INTERVAL_MINUTES="${EGX_NEWS_BOT_CRON_INTERVAL:-5}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    --interval-minutes)
      INTERVAL_MINUTES="${2:-}"
      shift 2
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

if ! [[ "${INTERVAL_MINUTES}" =~ ^[0-9]+$ ]] || [[ "${INTERVAL_MINUTES}" -lt 1 ]] || [[ "${INTERVAL_MINUTES}" -gt 59 ]]; then
  echo "--interval-minutes must be a number from 1 to 59" >&2
  exit 2
fi

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
ROOT_DIR="$(cd -- "${APP_DIR}/.." && pwd)"
RUNNER="${SCRIPT_DIR}/run_telegram_once.sh"
LOG_DIR="${APP_DIR}/logs"
if [[ -n "${EGX_NEWS_BOT_CONFIG:-}" ]]; then
  CONFIG_FILE="${EGX_NEWS_BOT_CONFIG}"
else
  CONFIG_FILE="${APP_DIR}/.env"
fi

if [[ -z "${EGX_NEWS_BOT_CONFIG:-}" && ! -f "${CONFIG_FILE}" && -f "${ROOT_DIR}/ProjectSecrets.env" ]]; then
  CONFIG_FILE="${ROOT_DIR}/ProjectSecrets.env"
fi

if [[ ! -f "${CONFIG_FILE}" ]]; then
  {
    echo "Config file not found: ${CONFIG_FILE}"
    echo "Create one with: cp ${APP_DIR}/config.example.env ${APP_DIR}/.env"
    echo "Then fill TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID before rerunning this installer."
  } >&2
  exit 2
fi

set -a
# shellcheck disable=SC1090
source "${CONFIG_FILE}"
set +a

if [[ -z "${TELEGRAM_BOT_TOKEN:-}" ]]; then
  echo "TELEGRAM_BOT_TOKEN is required in ${CONFIG_FILE}" >&2
  exit 2
fi

if [[ -z "${TELEGRAM_CHAT_ID:-}" ]]; then
  echo "TELEGRAM_CHAT_ID is required in ${CONFIG_FILE}" >&2
  exit 2
fi

if [[ "${EGX_NEWS_BOT_ANALYSIS_MODE:-ai}" == "ai" && -z "${OPENAI_API_KEY:-}" ]]; then
  echo "OPENAI_API_KEY is required in ${CONFIG_FILE} when EGX_NEWS_BOT_ANALYSIS_MODE=ai" >&2
  exit 2
fi

cron_line="*/${INTERVAL_MINUTES} * * * * EGX_NEWS_BOT_CONFIG=\"${CONFIG_FILE}\" \"${RUNNER}\" >> \"${LOG_DIR}/egx-news-bot.log\" 2>&1 # EGX_NEWS_BOT_CRON"

if [[ "${DRY_RUN}" == "1" ]]; then
  echo "Dry run. Cron entry would be:"
  echo "${cron_line}"
  exit 0
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required" >&2
  exit 2
fi

python3 -m venv "${APP_DIR}/.venv"
"${APP_DIR}/.venv/bin/python" -m pip install --upgrade pip
"${APP_DIR}/.venv/bin/python" -m pip install -e "${APP_DIR}"

mkdir -p "${LOG_DIR}"
chmod +x "${RUNNER}"

existing_cron="$(crontab -l 2>/dev/null || true)"
{
  printf '%s\n' "${existing_cron}" | grep -v 'EGX_NEWS_BOT_CRON' || true
  printf '%s\n' "${cron_line}"
} | crontab -

echo "Installed EGX News Bot cron job:"
echo "${cron_line}"
echo "Logs: ${LOG_DIR}/egx-news-bot.log"
