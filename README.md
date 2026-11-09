# Mass Spectrometry Application

Web application for managing chemical analyses using mass spectrometry.

## Project Structure

spectrometrie_app/
├── backend/
│   ├── app.py              # Flask entry point
│   ├── config.py           # Configuration
│   ├── models.py           # Database models
│   ├── auth.py             # LDAP authentication
│   ├── routes/
│   │   ├── main_routes.py  # Main routes
│   │   └── admin_routes.py # Admin routes
│   └── requirements.txt    # Python dependencies
├── frontend/
│   ├── static/
│   │   ├── css/
│   │   │   └── style.css   # CSS styles
│   │   └── js/
│   │       └── script.js   # JavaScript scripts
│   └── templates/
│       ├── index.html      # Home page
│       ├── login.html      # Login page
│       ├── form.html       # Submission form
│       ├── success.html    # Confirmation page
│       └── admin/
│           ├── dashboard.html
│           └── export.html
├── database/
│   └── schema.sql          # Database schema
└── README.md

## Prerequisites

- Python 3.8+
- MySQL 8.0+
- LDAP server
- Node.js (optional, for front-end development)

## Installation

1. Clone the repository
2. Create a virtual environment: `python -m venv venv`
3. Activate the environment: `source venv/bin/activate` (Linux/Mac) or `venv\Scripts\activate` (Windows)
4. Install the dependencies: `pip install -r backend/requirements.txt`
5. Configure the environment variables in `.env`
6. Create the MySQL database and import the schema
7. Start the application: `python backend/app.py`

## Configuration

Copy `.env.example` to `.env` and adjust the values according to your environment.

## Features

- LDAP authentication
- Analysis form submission
- Sample management
- Administration interface
- Data export (CSV, Excel)

## Internationalization (i18n)

The application is bilingual **English (default) / French**, powered by Flask-Babel.

- Default locale: `en` (`BABEL_DEFAULT_LOCALE` in `app/__init__.py`). The user can switch language with the selector in the navbar (`/set-language/<lang>`, stored in the session); without a choice, the `Accept-Language` header is used, falling back to English.
- Source strings are in English (`msgid`). The French catalogue lives in `app/translations/fr/LC_MESSAGES/messages.po` (compiled to `.mo`).
- In templates use `{{ _('...') }}`, `{{ ngettext('singular', 'plural', n) }}`, `{{ value   datetimeformat }}`; in Python use `from flask_babel import gettext as _` (and `lazy_gettext` outside request contexts). Client-side JS strings are exposed through `window.I18N` in `base.html`.
- To update the catalogues after changing strings:

```bash
pybabel extract -F babel.cfg -k _l -o messages.pot .
pybabel update -i messages.pot -d app/translations
# edit app/translations/fr/LC_MESSAGES/messages.po, then:
pybabel compile -d app/translations
```