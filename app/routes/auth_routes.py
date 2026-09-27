from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required, current_user

from ..models import User, db
from ..auth import dap_auth
from .. import login_manager  # Import du login_manager depuis __init__.py

@login_manager.user_loader
def load_user(user_id):
    """Charger l'utilisateur pour Flask-Login"""
    return User.query.get(int(user_id))

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    """Page de connexion"""
    if current_user.is_authenticated:
        return redirect(url_for('main.form'))

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        if not username or not password:
            flash('Veuillez fournir un nom d\'utilisateur et un mot de passe', 'error')
            return redirect(url_for('auth.login'))

        user = dap_auth.authenticate(username, password)

        if user:
            user.last_login = db.func.now()
            db.session.commit()
            login_user(user)
            if user.is_admin:
                return redirect(url_for('admin.dashboard'))
            else:
                return redirect(url_for('main.form'))
        else:
            flash('Nom d\'utilisateur ou mot de passe incorrect', 'error')
            return redirect(url_for('auth.login'))

    return render_template('login.html')

@auth_bp.route('/logout')
@login_required
def logout():
    """Déconnexion"""
    logout_user()
    flash('Vous avez été déconnecté avec succès', 'success')
    return redirect(url_for('auth.login'))