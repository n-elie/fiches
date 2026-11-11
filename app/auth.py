from ldap3 import Server, Connection, SUBTREE
from ldap3.utils.conv import escape_filter_chars
from ldap3.core.exceptions import LDAPException
from flask import current_app
from .models import User, db
import logging

# Configuration du logger
logger = logging.getLogger(__name__)

# Attributs LDAP à récupérer pour les utilisateurs
DEFAULT_LDAP_USER_ATTRIBUTES = ['cn', 'mail', 'uid', 'ou']

class LDAPAuth:
    """Classe pour gérer l'authentification LDAP avec ldap3"""

    def __init__(self, app=None):
        if app is not None:
            self.init_app(app)

    def init_app(self, app):
        self.app = app
        self.config = app.config

        # Initialiser la configuration LDAP
        try:
            self.ldap_server_url = self.config['LDAP_SERVER']
            self.ldap_base_dn = self.config['LDAP_BASE_DN']
            self.ldap_bind_dn = self.config['LDAP_BIND_DN']
            self.ldap_bind_password = self.config['LDAP_BIND_PASSWORD']
            self.ldap_user_search_base = self.config['LDAP_USER_SEARCH_BASE']

            # Attributs LDAP à récupérer
            user_attrs_config = self.config.get('LDAP_USER_ATTRIBUTES')
            self.user_attributes = user_attrs_config if user_attrs_config else DEFAULT_LDAP_USER_ATTRIBUTES
            
            # Attribut pour l'équipe
            self.team_attribute = self.config.get('LDAP_TEAM_ATTRIBUTE', 'ou')


            # Tester la connexion LDAP
            self.test_connection()
        except Exception as e:
            logger.error(f"Erreur d'initialisation LDAP: {e}")
            raise

    def _create_server(self):
        """Créer un objet Server ldap3"""
        return Server(self.ldap_server_url)

    def _create_bind_connection(self):
        """Créer une connexion avec les identifiants de bind"""
        server = self._create_server()
        try:
            conn = Connection(server, user=self.ldap_bind_dn, password=self.ldap_bind_password, auto_bind=True)
            return conn
        except LDAPException as e:
            logger.error(f"Erreur de connexion LDAP: {e}")
            return None

    def test_connection(self):
        """Tester la connexion au serveur LDAP"""
        try:
            conn = self._create_bind_connection()
            if conn and conn.bound:
                logger.info("Connexion LDAP réussie")
                conn.unbind()
                return True
            return False
        except Exception as e:
            logger.error(f"Erreur de connexion LDAP: {e}")
            return False

    def authenticate(self, username, password):
        """Authentifier un utilisateur : compte local d'abord, sinon LDAP"""
        
        # Refuser les identifiants vides (évite un bind "anonyme" LDAP qui réussirait)
        if not username or not password:
            return None
        
        # 1. Compte local (créé par un administrateur) : vérification directe du hash
        user = self.get_user_by_username(username)
        if user and user.is_local_user():
            if user.check_password(password):
                logger.info(f"Local authentication successful for {username}")
                user.last_login = db.func.now()
                db.session.commit()
                return user
            logger.warning(f"Local authentication failed for {username}")
            return None
        
        # 2. Compte LDAP
        try:
            # Créer une connexion avec les identifiants de bind pour rechercher l'utilisateur
            conn = self._create_bind_connection()
            if not conn or not conn.bound:
                logger.error("Unable to connect to the LDAP server")
                return None

            # Rechercher l'utilisateur par uid
            search_filter = f"(uid={escape_filter_chars(username)})"
            conn.search(self.ldap_user_search_base, search_filter, SUBTREE,
                    attributes=self.user_attributes)

            if not conn.entries:
                logger.warning(f"User {username} not found in LDAP")
                conn.unbind()
                return None

            # Récupérer le premier résultat (il devrait y en avoir un seul)
            user_entry = conn.entries[0]
            user_dn = user_entry.entry_dn

            # Tester l'authentification avec le mot de passe de l'utilisateur
            try:
                server = self._create_server()
                user_conn = Connection(server, user=user_dn, password=password, auto_bind=True)

                if user_conn.bound:
                    logger.info(f"Authentification sucessfill for {username}")

                    # Récupérer les informations de l'utilisateur
                    user_info = self._parse_user_data(user_entry)

                    # Synchroniser ou créer l'utilisateur dans la base de données
                    user = self._sync_user_to_db(username, user_info, user_dn)

                    user_conn.unbind()
                    conn.unbind()
                    return user
                else:
                    logger.error(f"Authentication failed for {username}: invalid credentials")
                    conn.unbind()
                    return None

            except LDAPException as e:
                logger.error(f"Authentication failed for {username}: {e}")
                conn.unbind()
                return None

        except Exception as e:
            logger.error(f"LDAP error during authentication: {e}")
            return None

    def _parse_user_data(self, user_entry):
        """Parser les données LDAP de l'utilisateur (ldap3)"""
        user_info = {}

        # Extraire les attributs configurés
        for attr in self.user_attributes:
            if attr in user_entry:
                value = user_entry[attr].value
                if value:
                    # Mapper les attributs LDAP aux champs du modèle User
                    if attr == 'cn':
                        user_info['full_name'] = value
                    elif attr == 'mail':
                        user_info['email'] = value
                    elif attr == 'uid':
                        user_info['username'] = value
                    # Ajouter l'attribut directement si pas de mapping spécifique
                    else:
                        user_info[attr] = value
                        
        # Gérer l'attribut d'équipe (peut être une liste de valeurs)
        if self.team_attribute in user_entry:
            team_values = user_entry[self.team_attribute].value
            if team_values:
                # Si c'est une liste, la stocker directement
                if isinstance(team_values, list):
                    user_info['teams'] = team_values
                else:
                    # Si c'est une seule valeur, créer une liste
                    user_info['teams'] = [team_values]

        return user_info

    def _sync_user_to_db(self, username, user_info, user_dn):
        """Synchroniser les informations de l'utilisateur avec la base de données"""
        # Vérifier si l'utilisateur existe déjà
        user = self.get_user_by_username(username)

        if user:
            # Mettre à jour les informations
            user.email = user_info.get('email', user.email)
            user.full_name = user_info.get('full_name', user.full_name)
            user.teams = ', '.join(user_info['teams']) if isinstance(user_info['teams'], list) else user.teams
            user.ldap_dn = user_dn
            user.is_admin = username in self.config.get('ADMIN_USERS', [])
            user.last_login = db.func.now()
        else:
            # Créer un nouvel utilisateur
            user = User(
                username=username,
                email=user_info.get('email', f'{username}@example.com'),
                full_name=user_info.get('full_name', username),
                teams=', '.join(user_info.get('teams', [])) if isinstance(user_info.get('teams'), list) else user_info.get('teams', ''),
                ldap_dn=user_dn,
                is_admin=username in self.config.get('ADMIN_USERS', []),
                last_login=db.func.now()
            )
            db.session.add(user)

        db.session.commit()
        return user

    def get_user_by_id(self, user_id):
        """Récupérer un utilisateur par son ID"""
        return db.session.get(User, user_id)

    def get_user_by_username(self, username):
        """Récupérer un utilisateur par son nom d'utilisateur"""
        return db.session.scalars(
            db.select(User).where(User.username == username).limit(1)
        ).first()

# Instance de LDAPAuth
dap_auth = LDAPAuth()