# InsightPulse AI

**AI-powered data analytics in your pocket.** Upload a spreadsheet and InsightPulse turns it
into clear insights, phone-ready charts, machine-learning forecasts and plain-language
answers, with no data-science skills needed.

It works with two kinds of data:

- **Sales data** (orders, transactions, invoices): a full business dashboard with KPIs,
  trends, forecasts, customer segments and monthly PDF reports.
- **Any other table** (passengers, patients, students, survey answers, HR records): a complete
  exploratory data analysis, automatic findings and a *Predict* model for any column.

---

## Contents

- [Features](#features)
- [How it works](#how-it-works)
- [Tech stack](#tech-stack)
- [Getting started](#getting-started)
- [Configuration](#configuration)
- [Development](#development)
- [Security and privacy](#security-and-privacy)
- [Project structure](#project-structure)

---

## Features

### Business dashboard (sales data)
- **Automatic column mapping**: the AI recognises date, amount, product, customer and region
  columns in any export, and the user can adjust them.
- **Data cleaning and quality score**: dates, currencies and duplicates handled automatically,
  with a quality score out of 100 and plain-language notes.
- **KPIs and trends** for 7 days, 30 days, 90 days or 1 year, each compared with the previous
  period.
- **Insight feed**: top products, peak days and hours, customer segments, anomalies,
  correlations and cohort retention, ranked by importance.
- **Forecasting**: Prophet, SARIMA and XGBoost are tested on recent history and the most
  accurate model is used, with a likely range and an honest accuracy note.
- **Customer intelligence**: churn risk, RFM segments and a price what-if simulator.
- **Monthly PDF report**: KPIs, charts, an EDA summary, findings, recommended actions and the
  forecast, ready to share.

### Data exploration (any dataset)
- **Full EDA**: overview, statistics for every column, missing values, distributions and
  correlations.
- **Automatic findings**: outcome rates, the biggest differences between groups, strong
  relationships, skewed or unbalanced columns and data-quality issues.
- **Predict a column**: a gradient-boosting model trained on demand, validated with 5-fold
  cross-validation against a simple baseline, showing which columns drive the outcome.
  Columns that merely restate the outcome are detected and left out.
- **PDF data report** covering the whole table.

### Ask AI
- A team of AI agents answers questions about the data in plain language, with a chart and a
  short explanation of how the answer was worked out.
- Every number in an AI answer is checked against the computed results before it is shown.

### Mobile experience
- Five screens: Home, Insights, Forecast, Ask AI and Data.
- Light and dark themes, a guided welcome tour, sharing, and support for large text sizes.
- Sign-in with email and password or **Continue with Google**.

---

## How it works

```
┌──────────────────────┐        HTTPS / JSON        ┌───────────────────────────────┐
│  Flutter mobile app  │ ─────────────────────────▶ │  Python backend (FastAPI)     │
│  (thin client)       │ ◀───────────────────────── │  analysis · charts · ML · AI  │
└──────────────────────┘    numbers, text, charts   └───────────────┬───────────────┘
                                                                    │
                                                    ┌───────────────┴───────────────┐
                                                    │  PostgreSQL  ·  file storage  │
                                                    └───────────────────────────────┘
```

- **All analysis happens on the server.** The app only displays the numbers, text and
  chart images the server returns, so results are identical on every device.
- **Analytics are deterministic.** Insights, KPIs and forecasts are calculated with pandas
  and scikit-learn; AI is used to explain the results, never to invent them.
- **Charts are rendered on the server** (Matplotlib and Seaborn) in light and dark themes and
  sized for a phone screen.
- **Long tasks run in the background.** Forecasts and AI explanations are processed as jobs
  while the app shows progress.

---

## Tech stack

| Layer | Technologies |
|---|---|
| Mobile | Flutter, Dart, Riverpod, go_router, dio, Firebase Authentication |
| Backend | Python 3.12, FastAPI, SQLAlchemy, Alembic, Pydantic |
| Data and ML | pandas, NumPy, scikit-learn, Prophet, statsmodels, XGBoost, SHAP |
| Visualisation | Matplotlib, Seaborn, ReportLab (PDF) |
| AI | Anthropic Claude (Claude Haiku 5.5 by default) |
| Infrastructure | Docker, PostgreSQL |

---

## Getting started

### Prerequisites
- [Docker Desktop](https://www.docker.com/products/docker-desktop/)
- An Android phone or emulator for the app
- *(Optional)* an Anthropic API key for the AI features

### 1. Start the server

On Windows, double-click **`Start InsightPulse Server.bat`**. On other systems:

```bash
cp .env.example .env      # then set your own secrets (see Configuration)
docker compose up -d --build
```

The first start builds the image and can take several minutes. Data is kept between
restarts; **`Stop InsightPulse Server.bat`** (or `docker compose down`) stops the server.

### 2. Turn on AI (optional)

Double-click **`Set Claude API Key.bat`**, or add `ANTHROPIC_API_KEY` to `.env` and restart.
Without a key, everything except Ask AI works, and summaries use built-in templates.

### 3. Install the app

Build the APK (see [Development](#development)) and install it on the phone. The phone must
be able to reach the server; if the server's address changes, enter the new one with
**Server address** on the sign-in screen.

---

## Configuration

Settings are read from a `.env` file in the project root (copy `.env.example`). This file is
excluded from version control and must never be committed.

| Variable | Purpose |
|---|---|
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | Database credentials |
| `JWT_SECRET` | Secret used to sign sign-in tokens (use a long random value) |
| `JWT_EXPIRE_MINUTES` | How long a sign-in lasts |
| `MAX_UPLOAD_MB` | Largest file a user can upload |
| `ANTHROPIC_API_KEY` | Enables the AI features |
| `LLM_MODEL` | Claude model to use (default `claude-haiku-5-5`) |
| `FIREBASE_PROJECT_ID` | Enables Continue with Google |

### Google sign-in

1. Create a Firebase project and enable **Google** under *Authentication → Sign-in method*.
2. Register the Android app (`com.insightpulse.insightpulse`) with the SHA-1 of your signing key.
3. Copy `mobile/firebase.example.json` to `mobile/firebase.json` and fill in the values from the
   Firebase project settings, including the Web client ID.
4. Set `FIREBASE_PROJECT_ID` in `.env` and restart the server.
5. Build the app with `--dart-define-from-file=firebase.json`.

`firebase.json` and `google-services.json` are excluded from version control.

---

## Development

### Backend

```bash
cd backend
uv sync                              # install dependencies (uv installs Python 3.12)
uv run uvicorn app.main:app --reload # run locally
uv run pytest                        # run the test suite
uv run ruff check . && uv run black --check .
```

Tests use SQLite and a temporary folder, so they need neither Docker nor PostgreSQL.

### Mobile app

```bash
cd mobile
flutter pub get
flutter analyze
flutter test
flutter build apk --release --dart-define=API_BASE_URL=http://<server-address>:8000 \
  --dart-define-from-file=firebase.json
```

### Running checks in Docker

On machines where local Python or Flutter tooling is restricted (for example Windows Smart
App Control), the test suites and the APK build can run in containers:

```bash
docker build -t insightpulse-flutter:3.47.9 mobile/tool/docker
docker run --rm -v "$PWD/mobile:/src:ro" insightpulse-flutter:3.47.9 sh /src/tool/docker/test.sh
```

---

## Security and privacy

- **Authentication on every request.** All data, charts and jobs require a signed-in user, and
  each user can only access their own datasets.
- **Protected sign-in.** Passwords must meet a minimum strength, are stored as salted hashes,
  and repeated failed attempts are temporarily blocked. Google sign-in tokens are verified
  with Google's public keys.
- **Personal data stays private.** Name, email and phone columns are never copied into the
  analysed data. Emails, phone numbers and ID numbers are masked, and customer names are
  replaced with aliases before anything is sent to the AI service.
- **Safe AI.** AI agents can only run read-only queries on a private, temporary copy of the
  data, with time and row limits. AI-generated code is never executed, and every figure in an
  AI answer must match a computed result.
- **Secrets stay out of the repository.** API keys, database passwords and Firebase
  configuration live only in local, git-ignored files.

> For a public deployment, serve the backend over HTTPS behind a reverse proxy, restrict
> allowed origins, and disable the interactive API documentation.

---

## Project structure

```
InsightPulse/
├── backend/                 Python backend
│   ├── app/
│   │   ├── pipeline/        loading, profiling, column mapping, cleaning, quality
│   │   ├── insights/        KPIs and the insight engine
│   │   ├── eda/             exploration and prediction for any dataset
│   │   ├── ml/              forecasting, churn, segments, what-if
│   │   ├── ai/              Claude client, privacy, guardrails, agent team
│   │   ├── viz/             chart rendering
│   │   ├── reports/         PDF reports
│   │   └── api/             HTTP layer
│   ├── alembic/             database migrations
│   └── tests/
├── mobile/                  Flutter app
│   └── lib/
│       ├── core/            theme, networking, formatting
│       ├── data/            models and the backend client
│       ├── state/           Riverpod providers
│       ├── features/        screens
│       └── widgets/         shared UI components
├── docker-compose.yml
└── *.bat                    one-click Windows scripts
```
