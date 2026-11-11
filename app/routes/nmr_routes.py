from flask import Blueprint, render_template, request, redirect, url_for, flash, send_from_directory, current_app
from flask_babel import gettext as _, ngettext
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from sqlalchemy import desc
import os
import re
from datetime import datetime

from ..models import db, NMRSample, STATUS_NAMES
from .main_routes import allowed_file

nmr_bp = Blueprint('nmr', __name__, url_prefix='/nmr')

REFERENCE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\- ]{0,99}$")

def is_valid_reference(reference):
    return bool(reference) and bool(REFERENCE_RE.fullmatch(reference))

@nmr_bp.route('/sample/submit', methods=['GET', 'POST'])
@login_required
def submit_sample():
    """Formulaire de soumission d'échantillon"""
    
    nmr_config = current_app.config['SERVICES']['nmr']
    structures_folder = os.path.join(current_app.config['UPLOAD_FOLDER'], 'nmr', 'structures')
    os.makedirs(structures_folder, exist_ok=True)
    
    if request.method == 'POST':
        team = request.form.get('team')  # Équipe sélectionnée pour cette analyse
        reference = request.form.get('reference')
        quantity = request.form.get('quantity')
        notes = request.form.get('notes')
        formula = request.form.get('formula')
        stability = request.form.get('stability')
        solvent = request.form.get('solvent')
        frequency = request.form.get('frequency')
        experiments = request.form.getlist('experiments')
        other_experiment = request.form.get('other_experiment')
        other_experiment_name = request.form.get('other_experiment_name')

        # Validation : vérifier que toutes les expériences sont valides pour cette fréquence
        valid_experiments = nmr_config['experiments_by_frequency'].get(frequency, [])
        for exp in experiments:
            if exp not in valid_experiments:
                flash(_('The experiment "%(exp)s" is not available at %(freq)s MHz', exp=exp, freq=frequency), 'error')
                return redirect(url_for('nmr.submit_sample'))

        if not experiments and ((other_experiment and not other_experiment_name) or not other_experiment):
            flash(_('Please select at least one experiment'), 'error')
            return redirect(url_for('nmr.submit_sample'))

        if not is_valid_reference(reference):
            flash(_('Invalid reference: only letters, digits, spaces, ".", "-" or "_" (max 100 characters)'), 'error')
            return redirect(url_for('nmr.submit_sample'))

        if not reference or not quantity:
            flash(_('Please fill in all required fields'), 'error')
            return redirect(url_for('nmr.submit_sample'))

        if 'structure_file' not in request.files:
            flash(_('No structure file provided'), 'error')
            return redirect(url_for('nmr.submit_sample'))

        unique_filename = None
        if 'structure_file' in request.files:
            file = request.files['structure_file']
            if file.filename != '':
                if file and allowed_file(file.filename):
                    filename = secure_filename(file.filename)
                    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
                    unique_filename = f"{secure_filename(current_user.username)}_{timestamp}_{filename}"
                    filepath = os.path.join(structures_folder, unique_filename)
                    file.save(filepath)
                else:
                    flash(_('File type not allowed. Accepted formats:') + ' .cdx, .cdxml, .mol, .sdf', 'error')
                    return redirect(url_for('nmr.submit_sample'))

        try:
            sample = NMRSample(
                team=team,
                reference=reference,
                quantity=float(quantity),
                structure_file=unique_filename,
                formula=formula,
                stability=stability,
                solvent=solvent,
                frequency=frequency,
                experiments=', '.join(experiments),
                other_experiment=other_experiment_name if other_experiment and other_experiment_name else None,
                notes=notes,
                user_id=current_user.id
            )
            db.session.add(sample)
            current_user.last_team_used = team
            db.session.commit()
            flash(_('Sample submitted successfully!'), 'success')
            return redirect(url_for('nmr.success', sample_id=sample.id))
        except Exception as e:
            db.session.rollback()
            flash(_('Error during submission: %(err)s', err=str(e)), 'error')
            return redirect(url_for('nmr.submit_sample'))

    return render_template('nmr/sample_submit.html',
                           user=current_user,
                           solvents=nmr_config['solvents'],
                           stabilities=nmr_config['stabilities'],
                           experiments_by_frequency=nmr_config['experiments_by_frequency'])

@nmr_bp.route('/success/<int:sample_id>')
@login_required
def success(sample_id):
    """Page de confirmation de soumission"""
    
    sample = db.get_or_404(NMRSample, sample_id)
    if sample.user_id != current_user.id:
        flash(_('Access denied'), 'error')
        return redirect(url_for('main.index'))
    return render_template('success.html', sample=sample, user=current_user)
    
@nmr_bp.route('/sample/<int:sample_id>')
@login_required
def sample_detail(sample_id):
    """Détails d'un échantillon"""
    
    nmr_config = current_app.config['SERVICES']['nmr']
    sample = db.get_or_404(NMRSample, sample_id)
    solvent = nmr_config['solvents'].get(sample.solvent, None)
    stability = nmr_config['stabilities'].get(str(sample.stability), None)
    
    if sample.user_id != current_user.id and not current_user.is_admin:
        flash(_('Access denied'), 'error')
        return redirect(url_for('main.index'))
    return render_template('sample_detail.html',
                           sample=sample,
                           user=current_user,
                           status_names=STATUS_NAMES,
                           solvent=solvent,
                           stability=stability)
                           
@nmr_bp.route('/samples')
@login_required
def user_samples():
    """Liste des échantillons RMN de l'utilisateur"""
    
    from ..routes.main_routes import samples
    return samples(template='samples.html', show_users='current', sample_type=NMRSample)
    
@nmr_bp.route('/sample/<int:sample_id>/edit', methods=['GET', 'POST'])
@login_required
def sample_edit(sample_id):
    """Éditer un échantillon existant"""
    
    nmr_config = current_app.config['SERVICES']['nmr']
    structures_folder = os.path.join(current_app.config['UPLOAD_FOLDER'], 'nmr', 'structures')
    
    sample = db.get_or_404(NMRSample, sample_id)
    
    # Vérifier que l'utilisateur est le propriétaire ou admin
    if sample.user_id != current_user.id and not current_user.is_admin:
        flash(_('Access denied'), 'error')
        return redirect(url_for('main.index'))
    
    if request.method == 'POST':
        # Récupérer les nouvelles valeurs
        team = request.form.get('team')
        reference = request.form.get('reference')
        quantity = request.form.get('quantity')
        notes = request.form.get('notes')
        formula = request.form.get('formula')
        solvent = request.form.get('solvent')
        frequency = request.form.get('frequency')
        experiments = request.form.getlist('experiments')
        other_experiment = request.form.get('other_experiment')
        other_experiment_name = request.form.get('other_experiment_name')
        
        # Validation : vérifier que toutes les expériences sont valides pour cette fréquence
        valid_experiments = EXPERIMENTS_BY_FREQUENCY.get(frequency, [])
        for exp in experiments:
            if exp not in valid_experiments:
                flash(_('The experiment "%(exp)s" is not available at %(freq)s MHz', exp=exp, freq=frequency), 'error')
                return redirect(url_for('nmr.sample_edit', sample_id=sample_id))

        if not experiments and ((other_experiment and not other_experiment_name) or not other_experiment):
            flash(_('Please select at least one experiment'), 'error')
            return redirect(url_for('nmr.sample_edit', sample_id=sample_id))
            
        if not is_valid_reference(reference):
            flash(_('Invalid reference: only letters, digits, spaces, ".", "-" or "_" (max 100 characters)'), 'error')
            return redirect(url_for('nmr.sample_edit', sample_id=sample_id))
        
        if not reference or not quantity:
            flash(_('Please fill in all required fields'), 'error')
            return redirect(url_for('nmr.sample_edit', sample_id=sample_id))
        
        # Gestion du fichier (optionnel)
        if 'structure_file' in request.files:
            file = request.files['structure_file']
            if file.filename != '':
                if file and allowed_file(file.filename):
                    # Supprimer l'ancien fichier si nécessaire
                    old_filepath = os.path.join(structures_folder, sample.structure_file)
                    if os.path.exists(old_filepath):
                        os.remove(old_filepath)
                    
                    # Sauvegarder le nouveau fichier
                    filename = secure_filename(file.filename)
                    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
                    unique_filename = f"{current_user.username}_{timestamp}_{filename}"
                    filepath = os.path.join(structures_folder, unique_filename)
                    file.save(filepath)
                    sample.structure_file = unique_filename
        
        # Mettre à jour les champs
        sample.team = team
        sample.reference = reference
        sample.quantity = float(quantity)
        sample.notes = notes
        sample.formula = formula
        sample.solvent=solvent
        sample.frequency=frequency
        sample.experiments=', '.join(experiments)
        sample.other_experiment=other_experiment_name if other_experiment and other_experiment_name else None
        
        try:
            db.session.commit()
            flash(_('Sample submitted successfully!'), 'success')
            return redirect(url_for('nmr.sample_detail', sample_id=sample_id))
        except Exception as e:
            db.session.rollback()
            flash(_('Error during update: %(err)s', err=str(e)), 'error')
            return redirect(url_for('nmr.sample_edit', sample_id=sample_id))
    
    # GET: Afficher le formulaire pré-rempli
    return render_template('nmr/sample_submit.html',
                           sample=sample,
                           user=current_user,
                           solvents=nmr_config['solvents'],
                           stabilities=nmr_config['stabilities'],
                           experiments_by_frequency=nmr_config['experiments_by_frequency'])