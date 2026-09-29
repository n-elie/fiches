from flask import Blueprint, render_template, request, redirect, url_for, flash, send_from_directory, current_app
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from sqlalchemy import desc
import os
from datetime import datetime

from ..models import db, MSSample

ms_bp = Blueprint('ms', __name__, url_prefix='/ms')

SOLVENTS = {"CH2Cl2": "CH<sub>2</sub>Cl<sub>2</sub>",
            "MeOH": "Methanol",
            "ACN": "Acétonitrile",
            "H2O": "H<sub>2</sub>O"
            }

@ms_bp.route('/sample/submit', methods=['GET', 'POST'])
@login_required
def submit_sample():
    """Formulaire de soumission d'échantillon"""
    
    os.makedirs(current_app.config['UPLOAD_FOLDER'], exist_ok=True)
    
    if request.method == 'POST':
        team = request.form.get('team')  # Équipe sélectionnée pour cette analyse
        reference = request.form.get('reference')
        quantity = request.form.get('quantity')
        notes = request.form.get('notes')
        formula = request.form.get('formula')
        solvents = request.form.getlist('solvents')
        other_solvent = request.form.get('other_solvent')
        other_solvent_name = request.form.get('other_solvent_name')
        
        # Validation : vérifier que tous les solvants sont valides
        valid_solvents = SOLVENTS.keys()
        for solvent in solvents:
            if solvent not in valid_solvents:
                flash(f'Le solvant n\'est pas disponible.', 'error')
                return redirect(url_for('ms.submit_sample'))
                
        print(solvents, other_solvent, other_solvent_name)

        if not solvents and ((other_solvent and not other_solvent_name) or not other_solvent):
            flash('Veuillez sélectionner au moins un solvant', 'error')
            return redirect(url_for('ms.submit_sample'))

        if not reference or not quantity:
            flash('Veuillez remplir tous les champs obligatoires', 'error')
            return redirect(url_for('ms.submit_sample'))

        if 'structure_file' not in request.files:
            flash('Aucun fichier de structure fourni', 'error')
            return redirect(url_for('ms.submit_sample'))

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
                    return redirect(url_for('ms.submit_sample'))

        try:
            sample = MSSample(
                team=team,
                reference=reference,
                quantity=float(quantity),
                structure_file=unique_filename,
                formula=formula,
                solvents=', '.join(solvents),
                other_solvent=other_solvent_name if other_solvent and other_solvent_name else None,
                notes=notes,
                user_id=current_user.id
            )
            db.session.add(sample)
            current_user.last_team_used = team
            db.session.commit()
            flash('Échantillon soumis avec succès!', 'success')
            return redirect(url_for('ms.success', sample_id=sample.id))
        except Exception as e:
            db.session.rollback()
            flash(f'Erreur lors de la soumission: {str(e)}', 'error')
            return redirect(url_for('ms.submit_sample'))

    return render_template('ms/sample_submit.html',
                           user=current_user,
                           solvents=SOLVENTS)

@ms_bp.route('/success/<uuid:sample_id>')
@login_required
def success(sample_id):
    """Page de confirmation de soumission"""
    sample = MSSample.query.get_or_404(sample_id)
    if sample.user_id != current_user.id:
        flash('Accès non autorisé', 'error')
        return redirect(url_for('main.index'))
    return render_template('ms/success.html', sample=sample, user=current_user)
    
@ms_bp.route('/sample/<uuid:sample_id>')
@login_required
def sample_detail(sample_id):
    """Détails d'un échantillon"""
    sample = MSSample.query.get_or_404(sample_id)
    if sample.user_id != current_user.id and not current_user.is_admin:
        flash('Accès non autorisé', 'error')
        return redirect(url_for('main.index'))
    return render_template('sample_detail.html', sample=sample, user=current_user)
    
@ms_bp.route('/sample/<uuid:sample_id>/edit', methods=['GET', 'POST'])
@login_required
def sample_edit(sample_id):
    """Éditer un échantillon existant"""
    
    sample = MSSample.query.get_or_404(sample_id)
    
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
        solvents = request.form.getlist('solvents')
        other_solvent = request.form.get('other_solvent')
        other_solvent_name = request.form.get('other_solvent_name')
        
        # Validation : vérifier que tous les solvants sont valides
        valid_solvents = SOLVENTS.keys()
        for solvent in solvents:
            if solvent not in valid_solvents:
                flash(f'Le solvant n\'est pas disponible.', 'error')
                return redirect(url_for('ms.submit_sample'))

        if not solvents and ((other_solvent and not other_solvent_name) or not other_solvent):
            flash('Veuillez sélectionner au moins un solvant', 'error')
            return redirect(url_for('ms.submit_sample'))
        
        if not reference or not quantity:
            flash('Veuillez remplir tous les champs obligatoires', 'error')
            return redirect(url_for('ms.sample_edit', sample_id=sample_id))
        
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
        sample.solvents=', '.join(solvents)
        sample.other_solvent=other_solvent_name if other_solvent and other_solvent_name else None
        
        try:
            db.session.commit()
            flash('Échantillon mis à jour avec succès!', 'success')
            return redirect(url_for('ms.sample_detail', sample_id=sample_id))
        except Exception as e:
            db.session.rollback()
            flash(f'Erreur lors de la mise à jour: {str(e)}', 'error')
            return redirect(url_for('ms.sample_edit', sample_id=sample_id))
    
    # GET: Afficher le formulaire pré-rempli
    return render_template('ms/sample_edit.html',
                           sample=sample,
                           user=current_user,
                           solvents=SOLVENTS)
                           
@ms_bp.route('/sample/<uuid:sample_id>/delete', methods=['POST'])
@login_required
def delete_sample(sample_id):
    """Rediriger vers la route principale de suppression"""
    from ..routes.main_routes import main_bp
    return main_bp.delete_sample(sample_id)