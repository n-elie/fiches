from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
import uuid
from datetime import datetime

db = SQLAlchemy()

STATUS_NAMES = {
    'pending': 'En attente',
    'processing': 'En cours',
    'completed': 'Terminé',
    'cancelled': 'Annulé'
}

class User(db.Model, UserMixin):
    """Modèle utilisateur pour stocker les informations des utilisateurs LDAP"""
    
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    full_name = db.Column(db.String(200), nullable=True)
    teams = db.Column(db.String(100), nullable=True)
    last_team_used = db.Column(db.String(5), nullable=True)
    is_admin = db.Column(db.Boolean, default=False)
    ldap_dn = db.Column(db.String(500), nullable=True)
    last_login = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relation avec les échantillons
    samples = db.relationship('Sample', backref='user', lazy=True)

    def __repr__(self):
        return f'<User {self.username}>'
        
    def get_teams(self):
        if not self.teams:
            return []
        return self.teams.split(',') if ',' in self.teams else [self.teams]

class Sample(db.Model):
    """Modèle échantillon pour stocker les informations des analyses"""
    
    __tablename__ = 'samples'
    
    id = db.Column(db.Integer, primary_key=True)
    uuid = db.Column(db.Uuid, nullable=False, default=uuid.uuid4)
    analysis_type = db.Column(db.String(10), nullable=False)  # Type d'analyse pour différencier MS/NMR
    team = db.Column(db.String(100), nullable=True)  # Équipe associée à cette analyse
    reference = db.Column(db.String(100), nullable=False)
    quantity = db.Column(db.Float, nullable=False)
    structure_file = db.Column(db.String(500), nullable=True)
    formula = db.Column(db.String(100), nullable=True)
    smiles = db.Column(db.Text, nullable=True)
    mass = db.Column(db.Float, nullable=True)
    status = db.Column(db.String(50), default='pending')
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Clé étrangère vers l'utilisateur
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    
    __mapper_args__ = {
        'polymorphic_on': analysis_type,
        'polymorphic_identity': 'base'  # Identifiant pour la classe parente
    }

    def __repr__(self):
        return f'<Sample {self.reference}>'
        
    def get_type(self):
        return 'Unknown'
        
    def get_status(self):
        return STATUS_NAMES.get(self.status, self.status)
        
class MSSample(Sample):
    """Héritage pour les échantillons MS"""
    
    __tablename__ = 'ms_samples'
    
    id = db.Column(db.Integer, db.ForeignKey('samples.id'), primary_key=True)
    
    solvents = db.Column(db.String(100), nullable=True)  # Solvants utilisés
    other_solvent = db.Column(db.String(50), nullable=True)  # Solvant personnalisé
    
    __mapper_args__ = {
        'polymorphic_identity': 'ms'  # Identifiant pour MS
    }
    
    def get_type(self):
        return 'MS'
    
class NMRSample(Sample):
    """Héritage pour les échantillons RMN"""
    
    __tablename__ = 'nmr_samples'
    
    id = db.Column(db.Integer, db.ForeignKey('samples.id'), primary_key=True)
    
    stability = db.Column(db.Integer, nullable=True) # Stabilité de l'échantillon
    solvent = db.Column(db.String(10), nullable=True)  # Solvant utilisé
    frequency = db.Column(db.Integer, nullable=False)  # Fréquence en MHz
    experiments = db.Column(db.String(200), nullable=True)  # Expériences demandées (1H, 13C, etc.)
    other_experiment = db.Column(db.String(50), nullable=True) # Expérience personnalisée
    
    __mapper_args__ = {
        'polymorphic_identity': 'nmr'  # Identifiant pour RMN
    }
    
    def get_type(self):
        return 'RMN'

class Analysis(db.Model):
    """Modèle analyse pour stocker les résultats d'analyse"""
    
    __tablename__ = 'analyses'
    
    id = db.Column(db.Integer, primary_key=True)
    sample_id = db.Column(db.Integer, db.ForeignKey('samples.id'), nullable=False)
    mass_spectrum = db.Column(db.String(500), nullable=True)
    molecular_weight = db.Column(db.Float, nullable=True)
    formula = db.Column(db.String(100), nullable=True)
    analysis_date = db.Column(db.DateTime, nullable=True)
    results = db.Column(db.Text, nullable=True)

    # Relation avec l'échantillon
    sample = db.relationship('Sample', backref='analyses')

    def __repr__(self):
        return f'<Analysis {self.id}>'