#!/usr/bin/env bash
set -euo pipefail

existing_cron="$(crontab -l 2>/dev/null || true)"
printf '%s\n' "${existing_cron}" | grep -v 'EGX_NEWS_BOT_CRON' | crontab -
echo "Removed EGX News Bot cron entries."

