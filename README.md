# InsightPulse AI

AI-powered business analytics for small businesses. Upload sales / orders / customer
data and get automatic insights (pandas), phone-ready charts (Matplotlib + Seaborn),
ML forecasts and an AI assistant that explains the numbers in plain language.

```
mobile/   Flutter thin client: shows numbers, chart images and text from the API
backend/  Python 3.12 + FastAPI: all analysis, charting, ML and AI
```

## Run it

The server runs in Docker (PostgreSQL + the API), so nothing else needs installing on
Windows and it is not affected by Smart App Control.

1. Install Docker Desktop and open it.
2. Double-click `Start InsightPulse Server.bat`. The first start builds the image (10+
   minutes); after that the server starts with Docker Desktop. The window shows the address
   for a phone on the same Wi-Fi. `Stop InsightPulse Server.bat` stops it; data is kept.
3. Optional: double-click `Set Claude API Key.bat` to turn on the AI agents. The key is
   checked, then stored only in the gitignored `.env`.
4. Install `InsightPulse.apk` on the phone (build it with the commands below; it isn't kept
   in git). If the address differs from the one built in, tap **Server address** on the
   sign-in screen and enter the one from the window.

## Status

| Phase | Scope | State |
|---|---|---|
| 1 | Scaffold, docker-compose, sample data, pipeline, insights, viz, dashboard/insights/chart API, tests | **done** |
| 2 | Forecasting (Prophet / SARIMA / XGBoost), churn, segments, what-if, job system | **done** |
| 3 | LLM layer: column mapping, narratives, Ask-AI query planner, recommendations | **done** |
| 4 | Flutter app, 5 screens, auth, dark mode | **done** |
| 5 | Polish, PDF report, push-alert design | next |

## Quick start (local, no Docker)

Requires [uv](https://docs.astral.sh/uv/) (it installs Python 3.12 for you).

```bash
cp .env.example .env            # then set JWT_SECRET; for no-Postgres dev use:
                                # DATABASE_URL=sqlite:///./storage/dev.db
cd backend
uv sync                         # creates .venv with all dependencies
uv run python -m sample_data.generate_sample   # (re)creates sample_data/sales_sample.csv
uv run uvicorn app.main:app --reload
```

Open http://localhost:8000/docs for interactive API docs. With SQLite the tables are
created automatically; with Postgres run `uv run alembic upgrade head` first.

## Run with Docker

```bash
cp .env.example .env            # set POSTGRES_PASSWORD and JWT_SECRET
docker compose up --build
```

The backend container runs `alembic upgrade head` and then serves on port 8000.
Uploaded files, Parquet copies and cached chart PNGs live in `backend/storage/`
(mounted as a volume).

## Mobile app (mobile/)

Flutter 3.47+ (Dart 3.13), Riverpod 3, go_router, dio. The app is a thin client: every number,
chart (server-rendered PNG, light or dark) and sentence comes from the API.

```bash
cd mobile
flutter pub get
flutter test                      # Widget tests: models, every screen, UX flows, welcome tour, sharing, large text (1.3x)
flutter analyze
# Run against your backend:
flutter run -d chrome --dart-define=API_BASE_URL=http://localhost:8000
flutter run -d emulator-5554 --dart-define=API_BASE_URL=http://10.0.2.2:8000   # Android emulator
flutter run --dart-define=API_BASE_URL=http://<your-PC-LAN-IP>:8000            # real phone
```

Screens: **Home** (greeting, dataset chip, 7D/30D/90D/1Y, AI summary with "See why", 2x2 KPIs,
revenue trend with forecast, "What to do next"), **Insights** (filter chips, insight cards,
orange anomaly cards), **Forecast** (metric, 30 days/90 days/1 year, predicted total with likely
range and % change, chart with "Today", accuracy note, price what-if slider), **Ask AI** (chat
bubbles with chart and "How I got this", follow-up chips, mic and send), **Data** (file upload,
"connect a source" placeholders, AI-mapped columns with editable role chips, data-quality card,
"Build my dashboard"). Plus login/register, loading skeletons, empty and error states, and a
dark mode toggle. Background jobs (forecast, AI text) show as "pending" and the screen refreshes
itself until they finish.

- `lib/core/`: theme (brand tokens, light/dark), API client (bearer token, readable errors),
  formatting. Tokens are kept in secure storage.
- `lib/data/`: models parsed from JSON (no code generation) and `InsightPulseApi`, the one class
  that talks to the backend (mocked in tests).
- `lib/state/providers.dart`: Riverpod providers (auth, datasets, dashboard, insights, forecast
  polling, what-if, chart bytes, chat).
- `lib/features/`: the screens; `lib/widgets/`: shared cards, shimmer skeletons, brand visuals, chart image and full-screen
  viewer, dataset gate, fade-in motion.

UX details: theme, period and last dataset are remembered (`shared_preferences`); KPI tiles open a
detail sheet (definition, previous value, both date ranges); every chart opens full screen with
pinch-to-zoom; insights hand a pre-filled question to Ask AI; answers can be copied; what-if has
one-tap presets and shows monthly revenue in money; haptic feedback on toggles and sends; motion
is skipped when the OS asks to reduce it. When the data does not cover the whole previous period,
the API returns no % change (`window.previous_complete = false`) instead of a misleading one.

Visual layer (`lib/core/brand.dart`, `lib/widgets/visuals.dart`): an indigo-to-violet brand gradient
on the Home summary, the Forecast hero, the login header, the welcome tour and the AI avatar; each
metric has its own tint (revenue indigo, orders cyan, order value violet, customers pink) on icon
badges and native sparklines. The dashboard API returns a small `spark` series per KPI (daily for
7D/30D, weekly for 90D, fortnightly for 1Y). KPI and forecast numbers count up once, then show the
exact server value. Other parts: a low-expected-high range bar, an animated data-quality ring,
category stripes on insights, typing dots in Ask AI, shimmer loading placeholders, a floating tab
bar, a three-slide welcome tour on first launch, and Share buttons (`share_plus`) on the summary,
insights and AI answers.

App icon, Android/iOS launch screens and web icons come from `tool/generate_icons.py` (run with any
Python that has Pillow, from `mobile/`).

Android and iOS folders are generated; the Android manifest already requests internet access.
For release builds serve the API over HTTPS (Android and iOS block plain HTTP by default).

**Windows setup notes** (what this machine uses):

- The Flutter SDK lives in `C:\src\flutter` with `C:\src\flutter\bin` on PATH. A Flutter SDK path
  containing a space makes native-asset builds fail (`'C:\Users\Your' is not recognized`); a link
  to such a folder is not enough, because Flutter resolves links when it rebuilds those hooks.
- Android: Android Studio (bundled JDK, `JAVA_HOME`), SDK in `C:\Android\Sdk` (`ANDROID_HOME`; no
  spaces), platform 36, build-tools 37, NDK 28.2.13676358, emulator `InsightPulse_Pixel`.
  `flutter emulators --launch InsightPulse_Pixel`, then
  `flutter run --dart-define=API_BASE_URL=http://10.0.2.2:8000`.
- `android/gradle.properties` sets `kotlin.incremental=false`: Kotlin's incremental compiler fails
  when the project and the pub cache are on different drives (e.g. a `subst` drive).
- Very long project paths can exceed Windows' 260-character limit: keep the repo in a short folder
  (e.g. `C:\dev\insightpulse`), `subst` a drive letter, or enable long paths.

## Tests and lint

```bash
cd backend
uv run pytest                   # All tests: pipeline, insights, viz, ML, AI (mocked LLM), API (~60 s)
uv run ruff check . && uv run black --check .
```

Tests use SQLite and a temp storage folder, so no Docker or Postgres is needed.

On Windows with Smart App Control on, Python and Flutter's test runner are blocked; run
them in Docker instead:

```bash
docker run --rm -v "$PWD/backend:/src" -w /src -e PYTHONPATH=/src insightpulse-backend sh -c "uv sync --frozen --no-install-project -q && pytest -q"
docker build -t insightpulse-flutter:3.47.9 mobile/tool/docker
docker run --rm -v "$PWD/mobile:/src:ro" insightpulse-flutter:3.47.9 sh /src/tool/docker/test.sh
```

## Sign-in

- Email and password: at least 8 characters with a letter and a number (checked in the
  app and on the server). 10 wrong passwords for an account, or 30 failed sign-ins from
  one address, lock sign-in for 15 minutes.
- **Continue with Google** (Firebase): the app signs in with Google through Firebase and
  sends the Firebase ID token to `POST /api/v1/auth/firebase`; the server checks it with
  Google's public keys, requires a verified email, and signs the user in to the account
  with that email (creating it if new). No service-account key is needed.

To turn Google sign-in on:

1. In the [Firebase console](https://console.firebase.google.com), create a project, open
   **Authentication > Sign-in method** and enable **Google**.
2. Add an **Android app** with package `com.insightpulse.insightpulse` and the SHA-1 of
   the key that signs your APK (`keytool -list -v -keystore ~/.android/debug.keystore
   -alias androiddebugkey -storepass android`).
3. Copy `mobile/firebase.example.json` to `mobile/firebase.json` and fill it in from the
   project settings (API key, app id, project id, sender id) and the **Web client ID**
   shown under Authentication > Sign-in method > Google > Web SDK configuration.
4. Add `FIREBASE_PROJECT_ID=<project id>` to `.env` and restart the server.
5. Build the app with `--dart-define-from-file=firebase.json`.

Without these settings the Google button is hidden and the endpoint answers 503.

## Try the API

```bash
# 1. Register (returns a JWT)
curl -s -X POST localhost:8000/api/v1/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"email":"me@example.com","password":"change-me-123"}'

TOKEN=...   # paste access_token

# 2. Upload the sample file -> profile, auto column mapping, quality score
curl -s -X POST localhost:8000/api/v1/datasets -H "Authorization: Bearer $TOKEN" \
  -F file=@backend/sample_data/sales_sample.csv

DS=...      # paste dataset.id

# 3. Home dashboard, insight feed, a chart
curl -s "localhost:8000/api/v1/datasets/$DS/dashboard?period=30d" -H "Authorization: Bearer $TOKEN"
curl -s "localhost:8000/api/v1/datasets/$DS/insights?category=customers" -H "Authorization: Bearer $TOKEN"
curl -s "localhost:8000/api/v1/charts/<chart_id>.png?theme=dark" -H "Authorization: Bearer $TOKEN" -o chart.png
```

### Phase 1 endpoints (prefix `/api/v1`, JWT on every route except auth)

| Method | Path | Purpose |
|---|---|---|
| POST | `/auth/register`, `/auth/login` | email + password → bearer token |
| POST | `/datasets` | multipart upload (CSV/XLSX, ≤ `MAX_UPLOAD_MB`) |
| GET | `/datasets` | the user's datasets |
| GET | `/datasets/{id}/profile` | columns, proposed mapping, cleaning report, quality |
| PUT | `/datasets/{id}/mapping` | user-edited roles → re-clean, version + 1 |
| GET | `/datasets/{id}/dashboard?period=7d\|30d\|90d\|1y` | KPI cards vs previous period, summary, top 3 insights, trend chart URL |
| GET | `/datasets/{id}/insights?category=` | top insights by score (5–10) |
| GET | `/charts/{chart_id}.png?theme=light\|dark` | rendered PNG (cached, ETag) |

### Phase 2 endpoints

| Method | Path | Purpose |
|---|---|---|
| POST | `/datasets/{id}/forecast` `{target: revenue\|orders\|quantity, horizon_days: 7-365}` | queues a forecast → `202` with a job |
| GET | `/jobs/{job_id}` | `queued` / `running` / `succeeded` (with `result`) / `failed` (with `error`) |
| POST | `/datasets/{id}/predict/churn` `{churn_days?}` | churn probabilities, at-risk customers, ROC AUC, feature importance |
| POST | `/datasets/{id}/whatif` `{lever: price\|discount, change_pct}` | effect on units and revenue, SHAP drivers |
| GET | `/datasets/{id}/segments` | K-Means customer segments with business names |

The dashboard now also returns `forecast: {status, job_id, model, accuracy_note}`. The first
dashboard call for a data version starts a 90-day revenue forecast in the background; once
it finishes (about 10 s on the sample), the trend chart includes the forecast line, its range
and a "Today" marker. The Forecast screen's default request reuses that same job.

### Phase 3 endpoints (AI)

| Method | Path | Purpose |
|---|---|---|
| POST | `/datasets/{id}/chat` `{message, history?}` | `{answer, chart_url, data, follow_ups, how, plan, answerable, source}` |
| GET | `/datasets/{id}/recommendations` | top 3 actions; `source` is `llm`, or `rules` without AI |

Also: uploads are mapped by the LLM (`mapping.source = "llm"`), `GET /insights` fills each
`narrative` once its background job finishes (`narratives: off|pending|ready|failed`), and the
dashboard's `ai_summary` switches from template text to verified AI text (`status`, `source`).

Every dataset/chart/job query is scoped to the logged-in user. Another user's ids return 404.

## AI layer (backend/app/ai)

Set `ANTHROPIC_API_KEY` (and optionally `LLM_MODEL`, default `claude-haiku-5-5`) to turn it on.
Without a key everything else works: mapping uses heuristics, summaries and narratives use
template text, recommendations are rule-based, and `/chat` returns 503.

- **client.py**: `LLMClient` interface; `AnthropicLLM` uses the official SDK with structured JSON
  output (`output_config.format`) and server-side refusal fallback (`fallbacks: "default"`).
  Swap providers by adding another class with `complete_json`.
- **Privacy** (`privacy.py`): emails, phone numbers and CNICs are masked everywhere; personal
  columns are redacted in the 5 sample rows; customer ids are replaced by "Customer 1, 2, ..."
  in prompts and restored locally in answers. The clean dataset never contains name, email or
  phone columns in the first place.
- **Column mapping** (`mapping.py`): only column names + 5 masked rows are sent; the schema only
  allows real column names; invalid answers fall back to heuristics.
- **Narratives and summary** (`narratives.py`): written only from insight / KPI JSON, run as
  background jobs and cached per data version.
- **Ask AI** (`chat.py`, `query.py`): the LLM fills a JSON plan
  `{metric, group_by, filter, period, compare, sort, limit, chart}` whose allowed values come from
  the dataset; Python validates it (unknown products or months get a helpful message) and runs
  fixed pandas operations. **LLM-generated code is never executed.** A second call writes the
  answer from the computed numbers; the "how I got this" line is generated by code. If the data
  can't answer (profit, costs, ...), the reply says so.
- **Guardrail** (`grounding.py`): every number in AI text must match a number in the JSON it was
  given (allowing for rounding, K/M and ratios written as %); otherwise the text is discarded
  and the template version is used.
- **Recommendations** (`recommendations.py`): top 3 actions from insights (+ the forecast when
  ready), with the same guardrail and a rule-based fallback.

## Agentic RAG (backend/app/ai/agents)

Ask AI is answered by a team of Claude agents; the fixed query-plan pipeline above is the fallback.

| Agent or tool | What it can use | Safeguard |
|---|---|---|
| **Orchestrator** (`orchestrator.py`) | Decides what each question needs and writes the answer | Every figure must appear in a tool result; one chance to correct, then fallback |
| **Retrieval** (`knowledge.py`) | TF-IDF search over insights, finished forecasts, data quality, column mapping, metric definitions | Personal data masked before indexing |
| **SQL agent** (`specialists.py`) | `SELECT` on a `sales` table in a private in-memory SQLite copy of the clean data | SQLite authorizer allows reads only, one statement, 3 s and 200 rows per query; the app database is unreachable |
| **CSV agent** (`specialists.py`) | The file as uploaded, including columns the dashboards ignore | Fixed filter, group, describe and correlate operations; the model never writes Python |

Customers become aliases and personal columns are removed before either data copy is made, and
real names are restored only in the final answer. Text from uploaded files is treated as data.
A question has an 85 s limit (`AGENT_DEADLINE_SECONDS`). Set `AGENTIC_CHAT=false` to use only
query plans. Dashboards, insights and forecasts stay deterministic and feed the knowledge search.

## Without an AI key

Ask AI still answers common questions: `app/ai/offline.py` reads the metric, breakdown, period,
comparison and any product or city name with rules, then runs the same query plans as the LLM
route. Answers are labelled "Quick answer" in the app. The same mode covers AI service failures.

## How it works (backend/app)

- **pipeline/**: `loader` (CSV with encoding/delimiter sniffing, Excel), `profiler`
  (column kinds, missing %, samples), `mapping` (`ColumnMapper` protocol;
  `HeuristicMapper` now, LLM mapper in Phase 3, which will only ever see column names and 5
  sample rows), `cleaner` (dates, currency stripping, dedupe, drops rows with no
  date/revenue, adds `month`/`weekday`/`hour`, **never copies name/email/phone
  columns**), `quality` (score out of 100 + plain-language issues).
- **insights/**: KPI summary (MoM), monthly trend, top/bottom products + concentration,
  weekday × time-of-day, RFM segments, anomalies (trailing 28-day mean ± 3 std, with
  past anomalies excluded from the band), correlations (skips mechanical pairs like
  revenue~quantity), cohort retention. Each returns structured JSON + a 0–1 score;
  the engine isolates failures and returns the best 10. `dashboard.py` does the
  period KPIs, anchored on the **last date in the data**, not today.
- **viz/**: chart builders (line + band + Today marker, ranked bars, heatmap,
  histogram/boxplot, correlation heatmap, scatter + regression, donut, SHAP importance),
  6×3.4 in at 200 dpi (1200×680 px), light/dark themes, Agg backend, a render lock, `plt.close`
  in `finally`, PNG cache keyed by a hash of spec + theme + renderer version.
- **ml/**: `forecast` runs Prophet (weekly + yearly seasonality, Pakistan holidays with Eid
  build-up windows, 80% interval), SARIMA(1,1,1)(1,0,1,7) on log values, and XGBoost with lag
  and calendar features around a trend. It holds out the last 20% of days (never shuffled),
  picks the model with the lowest MAPE on 7-day totals, and refits it on everything. With
  under 60 days of history it returns a simple trend and says more data is needed. The total's
  "likely range" is the wider of the model's band and the measured holdout error.
  `churn`: RandomForest (`class_weight="balanced"`) labelled without look-ahead (features before
  a cutoff, "churned" = no order after it), scored by ROC AUC. `segments`: K-Means on log RFM
  (k = 3–6 by silhouette). `whatif`: HistGradientBoosting with monotonic constraints on units
  per order line, plus SHAP. `store` saves every model with joblib next to its metrics
  (`storage/models/{dataset}/v{version}/`); churn, what-if and segments train once per data
  version and are then served from cache (the what-if slider answers in about 25 ms).
- **core/jobs.py**: job rows plus a `JobRunner` interface. `BackgroundTasksRunner` runs after the
  response; a Celery runner only needs to send `execute_job(job_id)` to a worker. Identical
  requests on the same data version reuse one job.
- **core/**: `Storage` protocol (`LocalStorage`; S3 can be swapped in), `AuthProvider`
  protocol (`LocalJWTAuth`; Firebase later), dataset service, small LRU caches.

Charts are stored as **specs** (kind + JSON payload) in the `charts` table and rendered
on request, so the same chart can be served in either theme and re-styled later
by bumping `RENDER_VERSION` (it is part of every chart URL, and PNGs are served with
`Cache-Control: no-cache` + ETag, so clients pick up a restyle immediately). Chart text is sized
for a phone: the 1200 px image is shown about 340 px wide.

### Fonts

Charts use **Plus Jakarta Sans** if its TTF files are in `backend/app/viz/fonts/`
(download from Google Fonts, OFL licence). Otherwise they fall back to DejaVu Sans.

## Notes

- Dark theme chart colours are lighter steps of the brand palette
  (indigo `#8B85F5`, forecast `#F0A14A`) so marks keep ≥ 3:1 contrast on the dark surface.
- Windows: if imports fail with "numpy C-extensions failed", the project path is too
  long for Windows' 260-character limit. Move the repo to a shorter path, or set
  `UV_PROJECT_ENVIRONMENT` to a short folder for the venv.
- What-if assumes the same number of orders: it models how many units each order contains at a
  new price, not whether some customers stop ordering. The response says so in `notes`.
- The sample data has a built-in price elasticity (about -1.6 on units) and a discount lift, so
  the what-if model has a real effect to find.
- Never commit `.env`; `.gitignore` excludes it and `backend/storage/`.
