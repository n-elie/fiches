import os

from flask import Flask, render_template, request, session
from flask_babel import Babel, lazy_gettext as _l
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_wtf.csrf import CSRFProtect

from .tasks import init_celery
from .config import config
from .models import db
from .auth import dap_auth

# Initialiser Flask-Login au niveau du module
login_manager = LoginManager()
migrate = Migrate()
csrf = CSRFProtect()
babel = Babel()

SUPPORTED_LOCALES = ['fr', 'en']
DEFAULT_LOCALE = 'fr'

def get_locale():
    # 1. Choix explicite de l'utilisateur (stocké en session)
    lang = session.get('lang')
    if lang in SUPPORTED_LOCALES:
        return lang
    # 2. Sinon, négociation via l'en-tête Accept-Language du navigateur
    return request.accept_languages.best_match(SUPPORTED_LOCALES) or DEFAULT_LOCALE

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

    return app