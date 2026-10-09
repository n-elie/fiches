import os
import sys
from pathlib import Path
from typing import Dict, Tuple, List

# Charger le module TOML approprié (standard pour Python ≥ 3.11)
if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomli as tomllib
    except ImportError:
        raise ImportError(
            "Le module 'tomli' est requis pour Python < 3.11. "
            "Installez-le avec: pip install tomli"
        )

class Config:
    """Configuration de l'application chargée depuis config.toml"""

    def __init__(self):
        # Chemin vers le fichier de configuration
        config_path = Path(__file__).parent.parent / 'config.toml'

        # Charger la configuration TOML
        self._load_config(config_path)

        # Initialiser les propriétés
        self._init_db_config()
        self._init_ldap_config()
        self._init_app_config()
        self._init_services_config()
        self._init_redis_config()

    def _load_config(self, config_path: Path):
        """Charge le fichier TOML"""
        if not config_path.exists():
            raise FileNotFoundError(
                f"Fichier de configuration introuvable: {config_path}\n"
                f"Copiez config.toml.example vers config.toml et adaptez-le."
            )

        with open(config_path, 'rb') as f:
            self._config = tomllib.load(f)

    def _init_db_config(self):
        """Initialise la configuration de la base de données"""
        db_config = self._config.get('database', {})
        self.DB_TYPE = db_config.get('type', 'mysql').lower()
        self.DB_SQLITE_PATH = db_config.get('path', 'analyses.db')
        self.DB_HOST = db_config.get('host', 'localhost')
        self.DB_USER = db_config.get('user', 'root')
        self.DB_PASSWORD = db_config.get('password', '')
        self.DB_NAME = db_config.get('name', 'spectrometrie_db')

        # Construire l'URL de la base de données
        if self.DB_TYPE == 'sqlite':
            basedir = os.path.abspath(os.path.dirname(__file__))
            db_path = os.path.join(basedir, self.DB_SQLITE_PATH)
            self.SQLALCHEMY_DATABASE_URI = f'sqlite:///{db_path}'
        else:
            self.SQLALCHEMY_DATABASE_URI = (
                f'mysql+pymysql://{self.DB_USER}:{self.DB_PASSWORD}@'
                f'{self.DB_HOST}/{self.DB_NAME}'
            )
        self.SQLALCHEMY_TRACK_MODIFICATIONS = False

    def _init_ldap_config(self):
        """Initialise la configuration LDAP"""
        ldap_config = self._config.get('ldap', {})
        self.LDAP_SERVER = ldap_config.get('server', 'ldap://localhost:389')
        self.LDAP_BASE_DN = ldap_config.get('base_dn', 'dc=example,dc=com')
        self.LDAP_BIND_DN = ldap_config.get('bind_dn', 'cn=admin,dc=example,dc=com')
        self.LDAP_BIND_PASSWORD = ldap_config.get('bind_password', '')
        self.LDAP_USER_SEARCH_BASE = ldap_config.get('user_search_base', 'ou=users,dc=example,dc=com')
        self.LDAP_USER_ATTRIBUTES = ldap_config.get('user_attributes', 'cn,mail,uid,ou')
        self.LDAP_TEAM_ATTRIBUTE = ldap_config.get('team_attribute', 'icsnEquipeNum')

    def _init_app_config(self):
        """Initialise la configuration de l'application"""
        app_config = self._config.get('app', {})
        self.SECRET_KEY = app_config.get('secret_key', 'your-secret-key-here')
        self.UPLOAD_FOLDER = os.path.join(
            os.path.dirname(__file__),
            app_config.get('upload_folder', 'uploads')
        )
        self.ALLOWED_EXTENSIONS = set(
            app_config.get('allowed_extensions', ['cdx', 'cdxml', 'mol', 'sdf'])
        )
        self.MAX_CONTENT_LENGTH = int(
            app_config.get('max_content_length', 16777216)
        )
        self.PORT = int(app_config.get('port', 5000))
        self.DEBUG = app_config.get('debug', True)
        self.ADMIN_USERS = app_config.get('admin_users', ['admin'])
        self.LOGO = app_config.get('logo', 'logo.png')

    def _init_services_config(self):
        """Initialise la configuration des services"""
        services_config = self._config.get('services', {})
        self.SERVICES = {}
        for service_key, service_data in services_config.items():
            self.SERVICES[service_key] = {
                'name': service_data.get('name', 'Non précisé'),
                'responsible': service_data.get('responsible', 'Responsable'),
                'phone': service_data.get('phone', '0000')
            }
            
    def _init_redis_config(self):
        """Initialise la configuration redis"""
        redis_config = self._config.get('redis', {})
        
        self.CELERY_BROKER_URL =  redis_config.get('broker_url', 'redis://localhost:6379/0')
        self.CELERY_RESULT_BACKEND = redis_config.get('result_backend', 'redis://localhost:6379/0')

# Instanciation de la configuration (sera utilisée par Flask)
config = Config()