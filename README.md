# EGX News Bot

Telegram bot that watches Egyptian business news and uses AI to estimate the likely impact on EGX sectors and listed stocks.

> This project is for market research and education. It is not personal investment advice and it does not place trades.

## عربي

### البوت ده بيعمل ايه؟

`EGX News Bot` بيتابع أخبار الاقتصاد والبورصة من مصادر مصرية، وبعدها يستخدم AI علشان يفهم الخبر ويبعته على تيليجرام في تقرير بسيط.

التقرير بيقولك:

- الخبر جاي منين
- نوع الخبر: نتائج أعمال، استحواذ، تنظيم، أسعار طاقة، عقود، إلخ
- القطاع اللي ممكن يستفيد أو يتضرر
- السهم اللي ممكن يتأثر
- قوة تأثير الخبر من `0` لـ `100`
- هل الخبر جيد ولا سيئ للسهم
- إشارة عامة: أقرب للشراء/المتابعة، أقرب للبيع/تخفيف المخاطر، أو انتظار

### إزاي يساعد المتداول؟

- يلم الأخبار المهمة بسرعة بدل ما تتابع مواقع كتير يدوي
- يربط الخبر بالقطاع والسهم المحتمل تأثره
- يديك درجة قوة وتأثير علشان تعرف هل الخبر يستاهل متابعة ولا لا
- يحفظ رأيك من أزرار تيليجرام علشان تحسن جودة التحليل مع الوقت

### شكل التنبيه

```text
تقرير تأثير الخبر على البورصة المصرية

الخبر: طلعت مصطفى توقع عقد تطوير مشروع جديد بقيمة 20 مليار جنيه
المصدر: Al Borsa News
نوع الحدث: contract

الحكم والتصرف
التقييم: إيجابي للسهم
هل الخبر جيد ولا سيئ؟ جيد للسهم
إشارة عامة: أقرب للشراء/المتابعة، مش توصية شراء
ملاحظة: ده تحليل آلي عام، مش توصية استثمارية شخصية.

تأثير القطاعات
Real Estate: مستفيد | درجة 76/100 | ثقة 85%

تأثير الأسهم
TMGH: مستفيد | درجة 80/100 | ثقة 87%
```

### التثبيت السريع

المتطلبات:

- Python 3.11+
- Telegram bot token من BotFather
- Telegram chat id أو channel id
- OpenAI API key
- جهاز Linux/macOS عليه cron

```bash
git clone https://github.com/TZacksEG/egx-news-bot.git
cd egx-news-bot
cp config.example.env .env
```

افتح `.env` وحط القيم دي:

```bash
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_or_channel_id
OPENAI_API_KEY=your_openai_api_key
```

بعد كده شغل التثبيت:

```bash
bash scripts/install_cron.sh
```

البوت هيشتغل تلقائيا كل 5 دقايق.

لو عايزه كل دقيقتين:

```bash
bash scripts/install_cron.sh --interval-minutes 2
```

تشغيل مرة واحدة للتجربة:

```bash
bash scripts/run_telegram_once.sh
```

إلغاء التشغيل التلقائي:

```bash
bash scripts/uninstall_cron.sh
```

### مصادر الأخبار الحالية

البوت يستخدم RSS feeds من مصادر مثل:

- Arab Finance
- Al Borsa News
- Daily News Egypt
- Enterprise AM
- Economy Plus
- Hapi Journal
- Mubasher EGX
- Youm7 Economy and Bourse
- Masrawy Economy and Banking
- Amwal Al Ghad
- Egyptian Streets Business
- Invest-Gate
- Egypt Oil & Gas
- Property Plus

### مهم

البوت مش بيقول لك اشتري أو بيع كأمر مباشر. هو يعطي إشارة بحث عامة بناء على الخبر. قرار التداول مسؤوليتك، ولازم تراجع السعر، السيولة، التحليل الفني، المخاطر، وإدارة رأس المال.

## English

### What does it do?

`EGX News Bot` monitors Egyptian business and market news, sends each relevant article to an AI analyzer, then posts a Telegram report in Arabic/RTL.

Each report shows:

- news source and link
- event type: earnings, acquisition, policy, energy prices, contracts, etc.
- affected sector
- affected EGX stock when detected
- impact strength from `0` to `100`
- whether the news looks good or bad for the stock
- a general signal: closer to buy/watch, closer to sell/reduce risk, or wait

### How can it help a trader?

- saves time by scanning many Egyptian business sources automatically
- connects news to possible EGX sectors and stocks
- ranks news by impact strength
- keeps a feedback loop through Telegram buttons so bad calls can be reviewed and improved

### Quick Install

Requirements:

- Python 3.11+
- Telegram bot token from BotFather
- Telegram chat id or channel id
- OpenAI API key
- Linux/macOS machine with cron

```bash
git clone <your-repo-url>
cd egx-news-bot
cp config.example.env .env
```

Edit `.env`:

```bash
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_or_channel_id
OPENAI_API_KEY=your_openai_api_key
```

Install and schedule the bot:

```bash
bash scripts/install_cron.sh
```

Default schedule: every 5 minutes.

Run every 2 minutes instead:

```bash
bash scripts/install_cron.sh --interval-minutes 2
```

Run once for testing:

```bash
bash scripts/run_telegram_once.sh
```

Remove the cron job:

```bash
bash scripts/uninstall_cron.sh
```

### Telegram Feedback Buttons

Every alert includes buttons:

```text
تمام | غلط
مبالغ فيه | أضعف من اللازم
مش متعلق بالبورصة
```

The feedback is stored locally in SQLite under `data/feedback.sqlite3`. It is not sent anywhere else by default.

### Configuration

Main `.env` options:

```bash
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
OPENAI_API_KEY=
OPENAI_MODEL=gpt-5.4-mini
OPENAI_REASONING_EFFORT=low
EGX_NEWS_BOT_ANALYSIS_MODE=ai
EGX_NEWS_BOT_LIMIT=20
EGX_NEWS_BOT_MIN_STRENGTH=65
EGX_NEWS_BOT_MAX_AGE_HOURS=72
EGX_NEWS_BOT_INCLUDE_REVIEW=false
EGX_NEWS_BOT_CRON_INTERVAL=5
```

Use a dedicated Telegram bot token. Telegram `getUpdates` works reliably only when one process owns that bot token.

### Development

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
PYTHONPATH=src pytest -q
```

### Disclaimer

This bot is an AI research assistant for news monitoring. It can be wrong, late, incomplete, or overconfident. It is not financial advice, not a licensed analyst, and not a trading system.

### License

MIT License.
