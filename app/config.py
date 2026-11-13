import os
import sys
from pathlib import Path
from typing import Dict, Tuple, List
from urllib.parse import quote

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
        
DEFAULT_MS_SOLVENTS = {
    'CH2Cl2': "CH<sub>2</sub>Cl<sub>2</sub>",
    'MeOH': "Methanol",
    'ACN': "Acetonitrile",
    'H2O': "H<sub>2</sub>O"
}

DEFAULT_NMR_SOLVENTS = {
    "": "Not specified",
    "AcOHd4": "Acetic acid-d4",
    "ACEd6": "Acetone-d6",
    "ACNd3": "Acetonitrile-d3",
    "PhHd6": "Benzene-d6",
    "CDCl3": "CDCl3",
    "CD2Cl2": "CD2Cl2",
    "Cyd12": "Cyclohexane-d12",
    "D2O": "D2O",
    "DMFd7": "DMF-d7",
    "DMSOd6": "DMSO-d6",
    "pDd8": "p-Dioxane-d8",
    "EtOHd6": "Ethanol-d6",
    "MeOHd4": "Methanol-d4",
    "pyd5": "Pyridine-d5",
    "THDd8": "THF-d8",
    "PhMed8": "Toluene-d8",
    "TFAd": "TFA-d",
    "TFEd3": "Trifluoroethanol-d3"
}
             
DEFAULT_NMR_STABILITIES = {
    0: "Unknown",
    1: "Stable",
    2: "Unstable",
    3: "Very stable"
}

DEFAULT_NMR_EXPERIMENTS_BY_FREQUENCY = {
    "500": ("1H", "COSY", "HSQC", "HMQC", "HMBC", "NOESY", "ROESY", "HMQC-ND", "13C", "DEPT135", "DEPT90", "DEPT45", "P31", "P31-CPD"),
    "700": ("1H", "COSY", "HSQC", "HMBC", "NOESY", "ROESY", "13C", "DEPT135", "TOCSY", "HSQC 15N", "HMBC 15N")
}

class Config:
    """Configuration de l'application chargée depuis config.toml"""

    def __init__(self):
        # Chemin vers le fichier de configuration
        config_path = Path(__file__).parent.parent / 'config.toml'

        # Charger la configuration TOML
        self._load_config(config_path)
        
        # Prevent click-jacking
        self.SESSION_COOKIE_SECURE = True
        self.SESSION_COOKIE_SAMESITE = 'Lax'

        # Initialiser les propriétés
        self._init_db_config()
        self._init_ldap_config()
        self._init_app_config()
        self._init_samples_config()
        self._init_users_config()
        self._init_services_config()
        self._init_unifi_config()
        self._init_celery_config()

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
        key = app_config.get('secret_key')
        if not key or key == 'your-secret-key-here':
            raise RuntimeError("Set a strong, random secret_key in config.toml")
        self.SECRET_KEY = key
        
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
        self.DEBUG = app_config.get('debug', False)
        self.ADMIN_USERS = app_config.get('admin_users', ['admin'])
        self.LOGO = app_config.get('logo', 'logo.png')
        
        self.LOGIN_RATE_LIMIT = app_config.get('login_rate_limit', '5 per minute')
        self.RATELIMIT_STORAGE_URI = app_config.get('ratelimit_storage') or None  # URL complète explicite, résolue plus bas
        self.RATELIMIT_ENABLED = app_config.get('ratelimit_enabled', not self.DEBUG)
        self.BEHIND_PROXY = app_config.get('behind_proxy', False)
        
    def _init_samples_config(self):
        """Initialise la configuration pour la liste d'échantillons"""
        
        samples_config = self._config.get('samples', {})
        self.SAMPLES_PER_PAGE = samples_config.get('per_page', 10)
    
    def _init_users_config(self):
        """Initialise la configuration pour la liste d'utilisateurs"""
        
        users_config = self._config.get('users', {})
        self.USERS_PER_PAGE = users_config.get('per_page', 10)

    def _init_services_config(self):
        """Initialise la configuration des services"""
        
        services_config = self._config.get('services', {})
        self.SERVICES = {}
        for service_key, service_data in services_config.items():
            self.SERVICES[service_key] = {
                'name': service_data.get('name', 'Not specified'),
                'responsible': service_data.get('responsible', 'Responsible'),
                'phone': service_data.get('phone', '0000')
            }
            if service_key == 'ms':
                self.SERVICES['ms']['solvents'] = service_data.get('solvents', DEFAULT_MS_SOLVENTS)
            elif service_key == 'nmr':
                self.SERVICES['nmr']['solvents'] = service_data.get('solvents', DEFAULT_NMR_SOLVENTS)
                self.SERVICES['nmr']['stabilities'] = service_data.get('stabilities', DEFAULT_NMR_STABILITIES)
                self.SERVICES['nmr']['experiments_by_frequency'] = service_data.get('experiments_by_frequency', DEFAULT_NMR_EXPERIMENTS_BY_FREQUENCY)

    def _init_unifi_config(self):
        """Initialise la configuration unifi"""
        
        unifi_config = self._config.get('unifi', {})
        self.UNIFI = {
            'server': unifi_config.get('server', 'localhost'),
            'username': unifi_config.get('username', 'username'),
            'password': unifi_config.get('password', 'password'),
            'data_folder': unifi_config.get('data_folder', 'root')
        }
        
        certificate = unifi_config.get('certificate')
        if certificate:
            self.UNIFI['certificate'] = os.path.join(
                os.path.dirname(__file__),
                certificate,
            )
            
    def _init_celery_config(self):
        """Initialise la configuration celery"""
        
        celery_config = self._config.get('celery', {})
        
        password = celery_config.get('password', '')
        if not password:
            raise RuntimeError("Define [celery] password in config.toml (Redis requirepass)")
        scheme = 'rediss' if celery_config.get('ssl', False) else 'redis'
        host = celery_config.get('host', 'localhost')
        port = celery_config.get('port', 6379)
        db = celery_config.get('db', 0)
        auth = f":{quote(password, safe='')}@"
        
        def url(db: int) -> str:
            return f"{scheme}://{auth}{host}:{port}/{db}"

        self.CELERY_BROKER_URL = celery_config.get('broker_url') or url(int(celery_config.get('broker_db', 0)))
        self.CELERY_RESULT_BACKEND = celery_config.get('result_backend') or url(int(celery_config.get('backend_db', 1)))
        
        # Flask-Limiter : même instance Redis, DB dédiée.
        # Priorité à une URL complète fournie dans [app] ratelimit_storage,
        # sinon construite depuis host/port/password de [celery] + ratelimit_db.
        if self.RATELIMIT_STORAGE_URI:
            pass  # URL complète fournie telle quelle (doit contenir le password)
        else:
            db = int(self._config.get('app', {}).get('ratelimit_db', 2))
            self.RATELIMIT_STORAGE_URI = url(db)

# Instanciation de la configuration (sera utilisée par Flask)
config = Config()