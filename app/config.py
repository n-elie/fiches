import os
from dotenv import load_dotenv

# Charger les variables d'environnement
load_dotenv()

class Config:
    # Type de base de données : 'mysql' ou 'sqlite'
    DB_TYPE = os.getenv('DB_TYPE', 'mysql').lower()

    # Configuration MySQL
    DB_HOST = os.getenv('DB_HOST', 'localhost')
    DB_USER = os.getenv('DB_USER', 'root')
    DB_PASSWORD = os.getenv('DB_PASSWORD', '')
    DB_NAME = os.getenv('DB_NAME', 'spectrometrie_db')

    # Configuration SQLite
    DB_SQLITE_PATH = os.getenv('DB_SQLITE_PATH', 'sqlite:///spectrometrie.db')

    # URL de la base de données
    if DB_TYPE == 'sqlite':
        # Utiliser un chemin absolu pour SQLite
        basedir = os.path.abspath(os.path.dirname(__file__))
        db_path = os.path.join(basedir, DB_SQLITE_PATH.replace('sqlite:///', ''))
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{db_path}"
    else:
        # MySQL par défaut
        SQLALCHEMY_DATABASE_URI = f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}/{DB_NAME}"

    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Configuration LDAP
    LDAP_SERVER = os.getenv('LDAP_SERVER', 'ldap://localhost:389')
    LDAP_BASE_DN = os.getenv('LDAP_BASE_DN', 'dc=example,dc=com')
    LDAP_BIND_DN = os.getenv('LDAP_BIND_DN', 'cn=admin,dc=example,dc=com')
    LDAP_BIND_PASSWORD = os.getenv('LDAP_BIND_PASSWORD', '')
    LDAP_USER_SEARCH_BASE = os.getenv('LDAP_USER_SEARCH_BASE', 'ou=users,dc=example,dc=com')
    LDAP_USER_ATTRIBUTES = os.getenv('LDAP_USER_ATTRIBUTES', 'cn,mail,uid,ou')
    LDAP_TEAM_ATTRIBUTE = os.getenv('LDAP_TEAM_ATTRIBUTE', 'icsnEquipeNum')
    
    # Secret key pour Flask
    SECRET_KEY = os.getenv('SECRET_KEY', 'your-secret-key-here')

    # Configuration des uploads
    UPLOAD_FOLDER = os.getenv('UPLOAD_FOLDER', os.path.join(os.path.dirname(__file__), 'uploads'))
    ALLOWED_EXTENSIONS = {'cdx', 'cdxml', 'mol', 'sdf'}
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16 Mo

    # Port de l'application
    PORT = int(os.getenv('PORT', 5000))

    # Mode debug
    DEBUG = os.getenv('DEBUG', 'True').lower() == 'true'
    
    # Administrators
    ADMIN_USERS = os.getenv('ADMIN_USERS', 'admin').split(',')