from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
import uuid
from datetime import datetime

db = SQLAlchemy()

class User(db.Model, UserMixin):
    """Modèle utilisateur pour stocker les informations des utilisateurs LDAP"""
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
    id = db.Column(
        db.Uuid, 
        primary_key=True, 
        default=uuid.uuid4
    )
    team = db.Column(db.String(100), nullable=True)  # Équipe associée à cette analyse
    reference = db.Column(db.String(100), nullable=False)
    quantity = db.Column(db.Float, nullable=False)
    structure_file = db.Column(db.String(500), nullable=False)
    status = db.Column(db.String(50), default='pending')
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Clé étrangère vers l'utilisateur
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

    def __repr__(self):
        return f'<Sample {self.reference}>'

class Analysis(db.Model):
    """Modèle analyse pour stocker les résultats d'analyse"""
    id = db.Column(db.Integer, primary_key=True)
    sample_id = db.Column(db.Integer, db.ForeignKey('sample.id'), nullable=False)
    mass_spectrum = db.Column(db.String(500), nullable=True)
    molecular_weight = db.Column(db.Float, nullable=True)
    formula = db.Column(db.String(100), nullable=True)
    analysis_date = db.Column(db.DateTime, nullable=True)
    results = db.Column(db.Text, nullable=True)

    # Relation avec l'échantillon
    sample = db.relationship('Sample', backref='analyses')

    def __repr__(self):
        return f'<Analysis {self.id}>'

# Fonction pour initialiser la base de données
def init_db(app):
    db.init_app(app)
    with app.app_context():
        db.create_all()