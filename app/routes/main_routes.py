from flask import Blueprint, render_template, request, redirect, url_for, flash, send_from_directory, current_app
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
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
        return redirect(url_for('main.form'))
    return render_template('index.html')

@main_bp.route('/form', methods=['GET', 'POST'])
@login_required
def form():
    """Formulaire de soumission d'échantillon"""
    
    os.makedirs(current_app.config['UPLOAD_FOLDER'], exist_ok=True)
    
    if request.method == 'POST':
        team = request.form.get('team')  # Équipe sélectionnée pour cette analyse
        reference = request.form.get('reference')
        quantity = request.form.get('quantity')
        notes = request.form.get('notes')

        if not reference or not quantity:
            flash('Veuillez remplir tous les champs obligatoires', 'error')
            return redirect(url_for('main.form'))

        if 'structure_file' not in request.files:
            flash('Aucun fichier de structure fourni', 'error')
            return redirect(url_for('main.form'))

        file = request.files['structure_file']
        if file.filename == '':
            flash('Aucun fichier sélectionné', 'error')
            return redirect(url_for('main.form'))

        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
            unique_filename = f"{current_user.username}_{timestamp}_{filename}"
            filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], unique_filename)
            file.save(filepath)
        else:
            flash('Type de fichier non autorisé. Formats acceptés: .cdx, .cdxml, .mol, .sdf', 'error')
            return redirect(url_for('main.form'))

        try:
            sample = Sample(
                team=team,
                reference=reference,
                quantity=float(quantity),
                structure_file=unique_filename,
                notes=notes,
                user_id=current_user.id
            )
            db.session.add(sample)
            current_user.last_team_used = team
            db.session.commit()
            flash('Échantillon soumis avec succès!', 'success')
            return redirect(url_for('main.success', sample_id=sample.id))
        except Exception as e:
            db.session.rollback()
            flash(f'Erreur lors de la soumission: {str(e)}', 'error')
            return redirect(url_for('main.form'))

    return render_template('form.html', user=current_user)

@main_bp.route('/success/<uuid:sample_id>')
@login_required
def success(sample_id):
    """Page de confirmation de soumission"""
    sample = Sample.query.get_or_404(sample_id)
    if sample.user_id != current_user.id:
        flash('Accès non autorisé', 'error')
        return redirect(url_for('main.index'))
    return render_template('success.html', sample=sample, user=current_user)

@main_bp.route('/samples')
@login_required
def user_samples():
    """Liste des échantillons de l'utilisateur"""
    samples = Sample.query.filter_by(user_id=current_user.id).order_by(Sample.created_at.desc()).all()
    return render_template('samples.html', samples=samples, user=current_user)

@main_bp.route('/sample/<uuid:sample_id>')
@login_required
def sample_detail(sample_id):
    """Détails d'un échantillon"""
    sample = Sample.query.get_or_404(sample_id)
    if sample.user_id != current_user.id and not current_user.is_admin:
        flash('Accès non autorisé', 'error')
        return redirect(url_for('main.index'))
    return render_template('sample_detail.html', sample=sample, user=current_user)

@main_bp.route('/download/<filename>')
@login_required
def download_file(filename):
    """Télécharger un fichier ChemDraw"""
    sample = Sample.query.filter_by(structure_file=filename).first()
    if not sample or sample.user_id != current_user.id:
        flash('Accès non autorisé', 'error')
        return redirect(url_for('main.index'))
    return send_from_directory(UPLOAD_FOLDER, filename, as_attachment=True)