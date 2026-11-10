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

```bash
# 1. Redis (broker) — locally
redis-server
# or via Docker
docker run -d --name fiches-redis -p 6379:6379 redis:7

# 2. Worker Celery (performs the following tasks: processing test results)
celery -A run_celery worker --loglevel=info

# 3. Beat (schedules the download of UNIFI spectra every hour)
celery -A run_celery beat --loglevel=info
```

Configurable Redis URLs in `config.toml` (`[celery] broker_url`, `result_backend`, by default `redis://localhost:6379/0`).

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