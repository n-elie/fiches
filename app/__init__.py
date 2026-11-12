import os
import html
import logging
from logging.handlers import RotatingFileHandler
import secrets

from flask import Flask, render_template, request, session, flash, redirect, url_for, g
from flask_babel import Babel, lazy_gettext as _l
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from werkzeug.middleware.proxy_fix import ProxyFix

from .tasks import init_celery
from .config import config
from .models import db
from .auth import dap_auth
from .utils.errors import sanitize_log

# Initialiser Flask-Login au niveau du module
login_manager = LoginManager()
migrate = Migrate()
csrf = CSRFProtect()
babel = Babel()
limiter = Limiter(key_func=get_remote_address)

SUPPORTED_LOCALES = ['fr', 'en']
DEFAULT_LOCALE = 'fr'

def get_locale():
    # 1. Choix explicite de l'utilisateur (stocké en session)
    lang = session.get('lang')
    if lang in SUPPORTED_LOCALES:
        return lang
    # 2. Sinon, négociation via l'en-tête Accept-Language du navigateur
    return request.accept_languages.best_match(SUPPORTED_LOCALES) or DEFAULT_LOCALE
    
class SanitizingFormatter(logging.Formatter):
    """Anti-injection log : supprime les caractères de contrôle (CRLF) puis
    échappe le HTML, au cas où les logs seraient rendus dans une interface web."""
    
    def format(self, record):
        record.msg = sanitize_log(record.msg)
        if record.args:
            record.args = tuple(sanitize_log(a) for a in record.args)
        return html.escape(super().format(record))

def create_app():
    """Créer et configurer l'application Flask"""

    # Configuration du dossier des templates (relatif au dossier parent)
    template_folder = os.path.join(os.path.dirname(__file__), 'templates')
    static_folder = os.path.join(os.path.dirname(__file__), 'static')

    app = Flask(__name__,
               template_folder=template_folder,
               static_folder=static_folder)

    app.config.from_object(config)
    app.config['BABEL_DEFAULT_LOCALE'] = DEFAULT_LOCALE
    app.config['BABEL_SUPPORTED_LOCALES'] = SUPPORTED_LOCALES

    # Initialiser les extensions
    db.init_app(app)
    login_manager.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)
    babel.init_app(app, locale_selector=get_locale)
    app.jinja_env.globals['get_locale'] = get_locale
    if not app.config.get('RATELIMIT_STORAGE_URI'):
        app.config['RATELIMIT_STORAGE_URI'] = app.config['CELERY_BROKER_URL']
    limiter.init_app(app)
    
    if app.config.get('BEHIND_PROXY', False):
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
    
    # Journaliser les erreurs complètes dans un fichier en production
    if not app.debug:
        os.makedirs('logs', exist_ok=True)
        handler = RotatingFileHandler('logs/fiches.log', maxBytes=1_000_000, backupCount=5)
        handler.setLevel(logging.ERROR)
        handler.setFormatter(SanitizingFormatter('%(asctime)s %(levelname)s %(name)s: %(message)s'))
        app.logger.addHandler(handler)
    
    # Configuration de Flask-Login
    login_manager.login_view = 'auth.login'
    login_manager.login_message = _l('Please log in to access this page')
    login_manager.login_message_category = 'info'

    # Initialiser l'authentification LDAP
    dap_auth.init_app(app)
    
    # Initialiser Celery
    init_celery(app)

    # Enregistrer les blueprints
    from .routes.main_routes import main_bp
    from .routes.ms_routes import ms_bp
    from .routes.nmr_routes import nmr_bp
    from .routes.auth_routes import auth_bp
    from .routes.admin_routes import admin_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(ms_bp)
    app.register_blueprint(nmr_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp, url_prefix='/admin')

    # Configuration des uploads
    app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(__file__), 'uploads')
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    
    # Gestionnaire d'erreur 404
    @app.errorhandler(404)
    def page_not_found(e):
        return render_template('404.html'), 404
        
    # Gestionnaire erreur 429 (Too Many Requests)
    @app.errorhandler(429)
    def rate_limit_exceeded(e):
        flash(_l('Too many login attempts. Please wait a minute and try again.'), 'error')
        return redirect(url_for('auth.login')), 429
        
    @app.errorhandler(500)
    def internal_server_error(e):
        app.logger.exception("Erreur 500 non gérée")
        return render_template('500.html'), 500
        
    # Prevent click-jacking
    @app.before_request
    def generate_csp_nonce():
        g.csp_nonce = secrets.token_hex(16)

    @app.context_processor
    def inject_csp_nonce():
        return {'csp_nonce': g.get('csp_nonce', '')}
        
    @app.after_request
    def set_security_headers(resp):
        resp.headers['X-Content-Type-Options'] = 'nosniff'
        resp.headers['X-Frame-Options'] = 'DENY'
        resp.headers['Content-Security-Policy'] = (
            "default-src 'self'; "
            f"script-src 'self' 'nonce-{g.get('csp_nonce', '')}'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:"
        )
        resp.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
        return resp

    return app