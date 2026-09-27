# Application de Spectrométrie de Masse

Application web pour la gestion des analyses chimiques par spectrométrie de masse.

## Structure du projet

spectrometrie_app/
├── backend/
│   ├── app.py              # Point d'entrée Flask
│   ├── config.py           # Configuration
│   ├── models.py           # Modèles de base de données
│   ├── auth.py             # Authentification LDAP
│   ├── routes/
│   │   ├── main_routes.py  # Routes principales
│   │   └── admin_routes.py # Routes d'administration
│   └── requirements.txt    # Dépendances Python
├── frontend/
│   ├── static/
│   │   ├── css/
│   │   │   └── style.css   # Styles CSS
│   │   └── js/
│   │       └── script.js   # Scripts JavaScript
│   └── templates/
│       ├── index.html      # Page d'accueil
│       ├── login.html      # Page de connexion
│       ├── form.html       # Formulaire de soumission
│       ├── success.html    # Page de confirmation
│       └── admin/
│           ├── dashboard.html
│           └── export.html
├── database/
│   └── schema.sql          # Schéma de la base de données
└── README.md

## Prérequis

- Python 3.8+
- MySQL 8.0+
- Serveur LDAP
- Node.js (optionnel, pour le développement frontend)

## Installation

1. Cloner le dépôt
2. Créer un environnement virtuel : `python -m venv venv`
3. Activer l'environnement : `source venv/bin/activate` (Linux/Mac) ou `venv\Scripts\activate` (Windows)
4. Installer les dépendances : `pip install -r backend/requirements.txt`
5. Configurer les variables d'environnement dans `.env`
6. Créer la base de données MySQL et importer le schéma
7. Démarrer l'application : `python backend/app.py`

## Configuration

Copier `.env.example` en `.env` et adapter les valeurs selon votre environnement.

## Fonctionnalités

- Authentification via LDAP
- Soumission de formulaires d'analyse
- Gestion des échantillons
- Interface d'administration
- Export des données (CSV, Excel)