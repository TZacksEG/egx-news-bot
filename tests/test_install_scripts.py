from pathlib import Path
import subprocess


APP_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = APP_DIR / "scripts"


def test_install_cron_dry_run_prints_idempotent_cron_entry(tmp_path):
    config = tmp_path / "egx-news-bot.env"
    config.write_text(
        "TELEGRAM_BOT_TOKEN=dummy\nTELEGRAM_CHAT_ID=123\nOPENAI_API_KEY=sk-test\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            "bash",
            str(SCRIPTS_DIR / "install_cron.sh"),
            "--dry-run",
            "--interval-minutes",
            "7",
        ],
        cwd=APP_DIR,
        env={"EGX_NEWS_BOT_CONFIG": str(config), "PATH": "/usr/bin:/bin:/usr/sbin:/sbin"},
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert "EGX_NEWS_BOT_CRON" in result.stdout
    assert "*/7 * * * *" in result.stdout
    assert str(SCRIPTS_DIR / "run_telegram_once.sh") in result.stdout
    assert "egx-news-bot.env" in result.stdout


def test_install_cron_rejects_blank_required_telegram_config(tmp_path):
    config = tmp_path / "egx-news-bot.env"
    config.write_text("TELEGRAM_BOT_TOKEN=\nTELEGRAM_CHAT_ID=\n", encoding="utf-8")

    result = subprocess.run(
        ["bash", str(SCRIPTS_DIR / "install_cron.sh"), "--dry-run"],
        cwd=APP_DIR,
        env={"EGX_NEWS_BOT_CONFIG": str(config), "PATH": "/usr/bin:/bin:/usr/sbin:/sbin"},
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "TELEGRAM_BOT_TOKEN is required" in result.stderr
    assert "dummy" not in result.stderr


def test_install_cron_rejects_blank_openai_key_for_ai_mode(tmp_path):
    config = tmp_path / "egx-news-bot.env"
    config.write_text(
        "\n".join(
            [
                "TELEGRAM_BOT_TOKEN=dummy",
                "TELEGRAM_CHAT_ID=123",
                "EGX_NEWS_BOT_ANALYSIS_MODE=ai",
                "OPENAI_API_KEY=",
            ]
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        ["bash", str(SCRIPTS_DIR / "install_cron.sh"), "--dry-run"],
        cwd=APP_DIR,
        env={"EGX_NEWS_BOT_CONFIG": str(config), "PATH": "/usr/bin:/bin:/usr/sbin:/sbin"},
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "OPENAI_API_KEY is required" in result.stderr
    assert "dummy" not in result.stderr


def test_run_telegram_once_dry_run_uses_configured_alert_options(tmp_path):
    config = tmp_path / "egx-news-bot.env"
    config.write_text(
        "\n".join(
            [
                "TELEGRAM_BOT_TOKEN=dummy",
                "TELEGRAM_CHAT_ID=123",
                "EGX_NEWS_BOT_LIMIT=9",
                "EGX_NEWS_BOT_MIN_STRENGTH=81",
                "EGX_NEWS_BOT_MAX_AGE_HOURS=12",
                "EGX_NEWS_BOT_INCLUDE_REVIEW=true",
                "EGX_NEWS_BOT_ANALYSIS_MODE=ai",
            ]
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        ["bash", str(SCRIPTS_DIR / "run_telegram_once.sh"), "--dry-run"],
        cwd=APP_DIR,
        env={"EGX_NEWS_BOT_CONFIG": str(config), "PATH": "/usr/bin:/bin:/usr/sbin:/sbin"},
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert "python" in result.stdout
    assert "-m egx_news_bot.cli collect-feedback" in result.stdout
    assert "-m egx_news_bot.cli send-telegram" in result.stdout
    assert "--limit 9" in result.stdout
    assert "--min-strength 81" in result.stdout
    assert "--max-age-hours 12" in result.stdout
    assert "--analysis-mode ai" in result.stdout
    assert "--include-review" in result.stdout
    assert "dummy" not in result.stdout


def test_run_telegram_once_requires_config_file(tmp_path):
    missing = tmp_path / "missing.env"

    result = subprocess.run(
        ["bash", str(SCRIPTS_DIR / "run_telegram_once.sh"), "--dry-run"],
        cwd=APP_DIR,
        env={"EGX_NEWS_BOT_CONFIG": str(missing), "PATH": "/usr/bin:/bin:/usr/sbin:/sbin"},
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "Config file not found" in result.stderr


def test_run_telegram_once_continues_when_feedback_collection_fails(tmp_path):
    config = tmp_path / "egx-news-bot.env"
    config.write_text(
        "\n".join(
            [
                "TELEGRAM_BOT_TOKEN=dummy",
                "TELEGRAM_CHAT_ID=123",
                "OPENAI_API_KEY=sk-test",
                "EGX_NEWS_BOT_ANALYSIS_MODE=ai",
            ]
        ),
        encoding="utf-8",
    )
    calls = tmp_path / "calls.log"
    fake_python = tmp_path / "python"
    fake_python.write_text(
        f"""#!/usr/bin/env bash
set -u
printf '%s\\n' "$*" >> "{calls}"
case "$*" in
  *collect-feedback*)
    echo 'feedback failed' >&2
    exit 1
    ;;
  *send-telegram*)
    echo 'sent'
    exit 0
    ;;
esac
exit 2
""",
        encoding="utf-8",
    )
    fake_python.chmod(0o755)

    result = subprocess.run(
        ["bash", str(SCRIPTS_DIR / "run_telegram_once.sh")],
        cwd=APP_DIR,
        env={
            "EGX_NEWS_BOT_CONFIG": str(config),
            "EGX_NEWS_BOT_PYTHON": str(fake_python),
            "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
        },
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert "Telegram feedback collection failed; continuing to send alerts." in result.stderr
    assert "-m egx_news_bot.cli collect-feedback" in calls.read_text(encoding="utf-8")
    assert "-m egx_news_bot.cli send-telegram" in calls.read_text(encoding="utf-8")
