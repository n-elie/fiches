# Fiches — Analysis Management (MS & NMR)

Flask web application for managing chemical analysis requests from two departments:
**mass Spectrometry (MS)** and **NMR**. Multilingual interface: **English (default) / French**.

## Organisation du projet

```
fiches/
├── run.py                     # Flask entry point: app = create_app()
├── run_celery.py              # Celery entry point (creates the Flask app and exposes `celery`)
├── babel.cfg                  # Translation extraction (pybabel)
├── config.toml.example        # Configuration template → copy to config.toml (ignored by git)
├── requirements.txt           # Python dependencies
├── package.json               # Bootstrap CSS compilation (SASS)
├── messages.pot               # Source translation catalog (generated, ignored by Git)
├── migrations/                # Alembic migrations (Flask-Migrate): env.py, alembic.ini, versions/
└── app/
    ├── __init__.py            # Factory create_app() + Flask-Babel initialization (default: fr)
    ├── config.py              # Configuration loaded from config.toml
    ├── models.py              # User, Sample / MSSample / NMRSample, Analysis, statuses
    ├── auth.py                # LDAP authentication (local accounts supported)
    ├── routes/                # Blueprints: main, ms, nmr, auth, admin
    ├── templates/             # Jinja: base.html, partials/, admin/, ms/, nmr/
    ├── static/
    │   ├── css/               # style.css + bootstrap.custom.min.css (compiled, ignored by Git)
    │   ├── js/                # script.js + locally hosted libraries (jQuery, Bootstrap, ECharts…)
    │   ├── images/            # logo, favicon, banner
    │   ├── data/              # samples.xlsx: batch import template
    │   └── scss/              # Bootstrap theme SCSS source
    ├── tasks/                 # Celery: celery_app.py (beat: UNIFI spectra every hour),
    │                          # process_samples.py, download_spectra.py
    ├── utils/
    │   ├── mol.py             # chemical formulas, SMILES, mass
    │   ├── pdf_utils.py       # PDF analysis sheets (2 A5 copies on A4, QR code)
    │   └── data_processing/   # UNIFI API + spectrum conversion (OpenMS/mspy)
    └── translations/fr/LC_MESSAGES/messages.po   # French translations (the compiled .mo file is ignored by git)
```

## Features

- **LDAP** authentication, with manageable local accounts (user creation/editing)
- Submission of **MS** samples (solvents, structure file `.cdx/.cdxml/.mol/.sdf`, molecular formula/SMILES, calculated mass) and **NMR** samples (stability, deuterated solvent, instrument frequency, requested experiments)
- **Batch import** of MS samples from XLSX/XLS/ODS/CSV (template: `app/static/data/samples.xlsx`), with AJAX preview and validation
- Sample list: filters (type, status, user, reference), sorting, pagination, statuses `pending → analyzing → analyzed/processing → completed/canceled`
- **PDF reports** of analysis results (individual or batch) with QR code
- **MS spectrum** visualization (ECharts: zoom, peak selection)
- **Sample list** (admin): search for pending MS samples, sortable list, export reference numbers and UUIDs, set status to “analyzing”
- Administration: dashboard, user management, status changes, Celery task tracking, **CSV/Excel exports**
- Automatic retrieval of UNIFI spectra **every hour** (Celery Beat)
- **i18n**: English by default, French via the `app/translations` directory (EN/FR selector in the navigation bar)

## Prerequisites

- Python ≥ 3.11 (or ≥ 3.8 with `pip install tomli`)
- MySQL 8.0+ **or** SQLite (select in `config.toml`)
- LDAP server (optional: local accounts can be created)
- Redis (Celery broker)
- Node.js + npm (only to recompile Bootstrap CSS)

## Installation

```bash
python -m venv venv
source venv/bin/activate            # Windows : venv\Scripts\activate
pip install -r requirements.txt

cp config.toml.example config.toml  # Then edit config.toml: BDD, LDAP, [app], [services], [unifi], [celery]
flask --app run db upgrade          # applies the migrations (creates the schema)

# Translations: Compile the French catalog (the .mo file is ignored by Git)
pybabel compile -d app/translations

# Custom Bootstrap CSS (the compiled file is ignored by Git)
npm install
npm run build:css
```

## Launch the app

```bash
# Development with auto-reload (--debug; otherwise read from [app] debug in config.toml)
flask --app run run --debug

# Direct equivalent
python run.py

# No debugging, explicit host/port (default: 0.0.0.0 and [app] port = 5000)
flask --app run run --host 0.0.0.0 --port 5000
```

Then open http://localhost:5000

## Redis, Celery Worker, and Celery Beat

Redis is used by this app as the **Celery broker**, the **Celery result backend**, and the
**Flask-Limiter rate-limit storage**. ⚠️ Never publish port 6379 and always set
`requirepass`: anyone who can reach an unauthenticated Redis can submit Celery tasks
(= execute code inside the worker) or read task results.

### Option A — docker-compose (recommended)

`docker-compose.yml`:

```yaml
services:
  redis:
    image: redis:7
    command: redis-server --requirepass ${REDIS_PASSWORD} --bind 127.0.0.1 --protected-mode yes
    volumes:
      - redis-data:/data
    # NO "ports:" section: Redis is only reachable inside the compose network
  worker:
    build: .
    command: celery -A run_celery worker --loglevel=info
    env_file: .env
    depends_on: [redis]
  beat:
    build: .
    command: celery -A run_celery beat --loglevel=info
    env_file: .env
    depends_on: [redis]

volumes:
  redis-data:
```

```bash
	echo 'REDIS_PASSWORD=<strong-random-password>' > .env && chmod 600 .env
	docker compose up -d
```

### Option B — local redis-server

```bash
	# never bind 0.0.0.0 without a password
	redis-server --requirepass '<strong-random-password>' --bind 127.0.0.1 --protected-mode yes
```

or

```bash
	redis-server redis.conf
```

`redis.conf`:

```conf
bind 127.0.0.1            # or internal IP, never 0.0.0.0
protected-mode yes
requirepass <strong-random-password>
# désactiver les commandes dangereuses si non utilisées :
rename-command FLUSHALL ""
rename-command CONFIG ""
rename-command SLAVEOF ""
rename-command MODULE ""
```

## Configure the URLs in config.toml

The worker and beat read their Redis URLs from config.toml — the commands
celery -A run_celery worker / celery -A run_celery beat take no URL argument
(app/config.py loads [celery] broker_url / result_backend into
CELERY_BROKER_URL / CELERY_RESULT_BACKEND):

```toml
[celery]
host = "localhost"
port = 6379
password = "<strong-random-password>"
broker_db = 0          # file des tâches (broker)
backend_db = 1         # résultats des tâches (backend)

[app]
login_rate_limit = "5 per minute"                  # Limite de tentatives sur /login
ratelimit_db = 2     # DB 2 dédiée au rate limiting (même Redis, même password)
ratelimit_enabled = true                           # false pour désactiver en d
```

Notes:

    If the password contains @ : / % etc., percent-escape it in the URLs (python -c "from urllib.parse import quote; print(quote('pwd', safe=''))").
    For TLS use rediss:// instead of redis:// (same password, port 6379→6380 or stunnel).
    Use separate DBs (0 = queue, 1 = results, 2 = rate limiting) so that purging results or counters (FLUSHDB on DB 1/2) never destroys pending tasks in DB 0.
    Then start the processes (they pick up config.toml automatically):
	
```bash
celery -A run_celery worker --loglevel=info
celery -A run_celery beat --loglevel=info    # downloads UNIFI spectra every hour
```
	
## Internationalization (i18n)

- Default language: **English** (`BABEL_DEFAULT_LOCALE = ‘en’` in `app/__init__.py`); falls back to the `Accept-Language` header; user can choose EN/FR in the navbar (`/set-language/<lang>`, stored in the session).
- Source strings in English (`msgid`); French translation file: `app/translations/fr/LC_MESSAGES/messages.po`.
- Templates: `{{ _(‘...’) }}`, `{{ ngettext(‘singular’, ‘plural’, n) }}`, `{{ value   datetimeformat }}`; Python: `from flask_babel import gettext as _`; client-side JS: `window.I18N` injected into `base.html`.
- After modifying the strings:

```bash
pybabel extract -F babel.cfg -k _l -o messages.pot .
pybabel update -i messages.pot -d app/translations
# edit app/translations/fr/LC_MESSAGES/messages.po, then :
pybabel compile -d app/translations
```

## Formatting

This project uses `djlint`, `css-beautify`, `js-beautify` to reformat templates:

```bash
djlint --reformat app/templates
css-beautify -r app/static/css/style.css
js-beautify -r app/static/js/script.js
```