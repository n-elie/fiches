from flask import Blueprint, render_template, request, redirect, url_for, flash, send_from_directory, current_app
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from sqlalchemy import desc
import os
from datetime import datetime

from ..models import db, Sample

main_bp = Blueprint('main', __name__)

def allowed_file(filename):
    """Vérifier si le fichier a une extension autorisée"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in current_app.config['ALLOWED_EXTENSIONS']

@main_bp.route('/')
def index():
    """Page d'accueil"""
    if current_user.is_authenticated:
        return redirect(url_for('main.user_samples'))
    return render_template('index.html')

@main_bp.route('/samples')
@login_required
def user_samples():
    """Liste des échantillons de l'utilisateur"""
    
    status_filter = request.args.get('status', '')
    type_filter = request.args.get('type', '')
    search_filter = request.args.get('search', '')
    
    query = Sample.query
    if status_filter:
        query = query.filter_by(status=status_filter)
    if type_filter:
        query = query.filter_by(analysis_type=type_filter)
    if search_filter:
        query = query.filter(
            Sample.reference.ilike(f'%{search_filter}%')
        )

    sort_by = request.args.get('sort', 'created_at')
    sort_order = request.args.get('order', 'desc')

    if sort_order == 'desc':
        query = query.order_by(desc(getattr(Sample, sort_by)))
    else:
        query = query.order_by(getattr(Sample, sort_by))
        
    samples = query.all()

    return render_template('samples.html',
                         samples=samples,
                         user=current_user,
                         status_filter=status_filter,
                         type_filter=type_filter,
                         search_filter=search_filter,
                         sort_by=sort_by,
                         sort_order=sort_order)

@main_bp.route('/download/<filename>')
@login_required
def download_file(filename):
    """Télécharger un fichier de structure"""
    sample = Sample.query.filter_by(structure_file=filename).first()
    if not sample or (sample.user_id != current_user.id and not current_user.is_admin):
        flash('Accès non autorisé', 'error')
        return redirect(url_for('main.index'))
    return send_from_directory(current_app.config['UPLOAD_FOLDER'], filename, as_attachment=True)