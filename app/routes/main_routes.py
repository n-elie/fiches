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
        formula = request.form.get('formula')

        if not reference or not quantity:
            flash('Veuillez remplir tous les champs obligatoires', 'error')
            return redirect(url_for('main.form'))

        if 'structure_file' not in request.files:
            flash('Aucun fichier de structure fourni', 'error')
            return redirect(url_for('main.form'))

        unique_filename = None
        if 'structure_file' in request.files:
            file = request.files['structure_file']
            if file.filename != '':
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
                formula=formula,
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
    
    search_filter = request.args.get('search', '')
    status_filter = request.args.get('status', '')
    
    query = Sample.query
    if status_filter:
        query = query.filter_by(status=status_filter)
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
                         search_filter=search_filter,
                         sort_by=sort_by,
                         sort_order=sort_order)

@main_bp.route('/sample/<uuid:sample_id>')
@login_required
def sample_detail(sample_id):
    """Détails d'un échantillon"""
    sample = Sample.query.get_or_404(sample_id)
    if sample.user_id != current_user.id and not current_user.is_admin:
        flash('Accès non autorisé', 'error')
        return redirect(url_for('main.index'))
    return render_template('sample_detail.html', sample=sample, user=current_user)
    
@main_bp.route('/sample/<uuid:sample_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_sample(sample_id):
    """Éditer un échantillon existant"""
    
    sample = Sample.query.get_or_404(sample_id)
    
    # Vérifier que l'utilisateur est le propriétaire ou admin
    if sample.user_id != current_user.id and not current_user.is_admin:
        flash('Accès non autorisé', 'error')
        return redirect(url_for('main.index'))
    
    if request.method == 'POST':
        # Récupérer les nouvelles valeurs
        team = request.form.get('team')
        reference = request.form.get('reference')
        quantity = request.form.get('quantity')
        notes = request.form.get('notes')
        formula = request.form.get('formula')
        
        if not reference or not quantity:
            flash('Veuillez remplir tous les champs obligatoires', 'error')
            return redirect(url_for('main.edit_sample', sample_id=sample_id))
        
        # Gestion du fichier (optionnel)
        if 'structure_file' in request.files:
            file = request.files['structure_file']
            if file.filename != '':
                if file and allowed_file(file.filename):
                    # Supprimer l'ancien fichier si nécessaire
                    old_filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], sample.structure_file)
                    if os.path.exists(old_filepath):
                        os.remove(old_filepath)
                    
                    # Sauvegarder le nouveau fichier
                    filename = secure_filename(file.filename)
                    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
                    unique_filename = f"{current_user.username}_{timestamp}_{filename}"
                    filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], unique_filename)
                    file.save(filepath)
                    sample.structure_file = unique_filename
        
        # Mettre à jour les champs
        sample.team = team
        sample.reference = reference
        sample.quantity = float(quantity)
        sample.notes = notes
        sample.formula = formula
        
        try:
            db.session.commit()
            flash('Échantillon mis à jour avec succès!', 'success')
            return redirect(url_for('main.sample_detail', sample_id=sample_id))
        except Exception as e:
            db.session.rollback()
            flash(f'Erreur lors de la mise à jour: {str(e)}', 'error')
            return redirect(url_for('main.edit_sample', sample_id=sample_id))
    
    # GET: Afficher le formulaire pré-rempli
    return render_template('sample_edit.html', sample=sample, user=current_user)

@main_bp.route('/download/<filename>')
@login_required
def download_file(filename):
    """Télécharger un fichier de structure"""
    sample = Sample.query.filter_by(structure_file=filename).first()
    if not sample or (sample.user_id != current_user.id and not current_user.is_admin):
        flash('Accès non autorisé', 'error')
        return redirect(url_for('main.index'))
    return send_from_directory(current_app.config['UPLOAD_FOLDER'], filename, as_attachment=True)