from flask import Flask, render_template
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_wtf.csrf import CSRFProtect
from .config import config
from .models import db
from .auth import dap_auth
import os

# Initialiser Flask-Login au niveau du module
login_manager = LoginManager()
migrate = Migrate()
csrf = CSRFProtect()

def create_app():
    """Créer et configurer l'application Flask"""

    # Configuration du dossier des templates (relatif au dossier parent)
    template_folder = os.path.join(os.path.dirname(__file__), 'templates')
    static_folder = os.path.join(os.path.dirname(__file__), 'static')

    app = Flask(__name__,
               template_folder=template_folder,
               static_folder=static_folder)

    app.config.from_object(config)

    # Initialiser les extensions
    db.init_app(app)
    login_manager.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)

    # Configuration de Flask-Login
    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'Veuillez vous connecter pour accéder à cette page'
    login_manager.login_message_category = 'info'

    # Initialiser l'authentification LDAP
    dap_auth.init_app(app)

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