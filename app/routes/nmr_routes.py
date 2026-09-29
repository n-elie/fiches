from flask import Blueprint, render_template, request, redirect, url_for, flash, send_from_directory, current_app
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from sqlalchemy import desc
import os
from datetime import datetime

from ..models import db, NMRSample

nmr_bp = Blueprint('nmr', __name__, url_prefix='/nmr')

SOLVENTS = {"": "Non précisé",
            "AcOHd4": "Acide Acétique-d4",
            "ACEd6": "Acétone-d6",
            "ACNd3": "Acétonitrile-d3",
            "PhHd6": "Benzène-d6",
            "CDCl3": "CDCl3",
            "CD2Cl2": "CD2Cl2",
            "Cyd12": "Cyclohexane-d12",
            "D2O": "D2O",
            "DMFd7": "DMF-d7",
            "DMSOd6": "DMSO-d6",
            "pDd8": "p-Dioxane-d8",
            "EtOHd6": "Ethanol-d6",
            "MeOHd4": "Methanol-d4",
            "pyd5": "Pyridine-d5",
            "THDd8": "THF-d8",
            "PhMed8": "Toluène-d8",
            "TFAd": "TFA-d",
            "TFEd3": "Trifluoroéthanol-d3"}
             
STABILITIES = {0: "Inconnue",
               1: "Stable",
               2: "Instable",
               3: "Très stable"}

EXPERIMENTS_BY_FREQUENCY = {
    "500": ("1H", "COSY", "HSQC", "HMQC", "HMBC", "NOESY", "ROESY", "HMQC-ND", "13C", "DEPT135", "DEPT90", "DEPT45", "P31", "P31-CPD"),
    "700": ("1H", "COSY", "HSQC", "HMBC", "NOESY", "ROESY", "13C", "DEPT135", "TOCSY", "HSQC 15N", "HMBC 15N")
}

@nmr_bp.route('/sample/submit', methods=['GET', 'POST'])
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
        stability = request.form.get('stability')
        solvent = request.form.get('solvent')
        frequency = request.form.get('frequency')
        experiments = request.form.getlist('experiments')
        other_experiment = request.form.get('other_experiment')
        other_experiment_name = request.form.get('other_experiment_name')

        # Validation : vérifier que toutes les expériences sont valides pour cette fréquence
        valid_experiments = EXPERIMENTS_BY_FREQUENCY.get(frequency, [])
        for exp in experiments:
            if exp not in valid_experiments:
                flash(f'L\'expérience "{exp}" n\'est pas disponible à {frequency} MHz', 'error')
                return redirect(url_for('nmr.submit_sample'))

        if not experiments and ((other_experiment and not other_experiment_name) or not other_experiment):
            flash('Veuillez sélectionner au moins une expérience', 'error')
            return redirect(url_for('nmr.submit_sample'))

        if not reference or not quantity:
            flash('Veuillez remplir tous les champs obligatoires', 'error')
            return redirect(url_for('nmr.submit_sample'))

        if 'structure_file' not in request.files:
            flash('Aucun fichier de structure fourni', 'error')
            return redirect(url_for('nmr.submit_sample'))

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
            flash('Échantillon soumis avec succès!', 'success')
            return redirect(url_for('nmr.success', sample_id=sample.id))
        except Exception as e:
            db.session.rollback()
            flash(f'Erreur lors de la soumission: {str(e)}', 'error')
            return redirect(url_for('nmr.submit_sample'))

    return render_template('nmr/sample_submit.html',
                           user=current_user,
                           solvents=SOLVENTS,
                           stabilities=STABILITIES,
                           experiments_by_frequency=EXPERIMENTS_BY_FREQUENCY)

@nmr_bp.route('/success/<uuid:sample_id>')
@login_required
def success(sample_id):
    """Page de confirmation de soumission"""
    sample = NMRSample.query.get_or_404(sample_id)
    if sample.user_id != current_user.id:
        flash('Accès non autorisé', 'error')
        return redirect(url_for('main.index'))
    return render_template('nmr/success.html', sample=sample, user=current_user)
    
@nmr_bp.route('/sample/<uuid:sample_id>')
@login_required
def sample_detail(sample_id):
    """Détails d'un échantillon"""
    sample = NMRSample.query.get_or_404(sample_id)
    if sample.user_id != current_user.id and not current_user.is_admin:
        flash('Accès non autorisé', 'error')
        return redirect(url_for('main.index'))
    return render_template('sample_detail.html', sample=sample, user=current_user)
    
@nmr_bp.route('/sample/<uuid:sample_id>/edit', methods=['GET', 'POST'])
@login_required
def sample_edit(sample_id):
    """Éditer un échantillon existant"""
    
    sample = NMRSample.query.get_or_404(sample_id)
    
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
        solvent = request.form.get('solvent')
        frequency = request.form.get('frequency')
        experiments = request.form.getlist('experiments')
        other_experiment = request.form.get('other_experiment')
        other_experiment_name = request.form.get('other_experiment_name')
        
        # Validation : vérifier que toutes les expériences sont valides pour cette fréquence
        valid_experiments = EXPERIMENTS_BY_FREQUENCY.get(frequency, [])
        print(experiments, valid_experiments, frequency, type(frequency))
        for exp in experiments:
            if exp not in valid_experiments:
                flash(f'L\'expérience "{exp}" n\'est pas disponible à {frequency} MHz', 'error')
                return redirect(url_for('nmr.sample_edit', sample_id=sample_id))

        if not experiments and ((other_experiment and not other_experiment_name) or not other_experiment):
            flash('Veuillez sélectionner au moins une expérience', 'error')
            return redirect(url_for('nmr.sample_edit', sample_id=sample_id))
        
        if not reference or not quantity:
            flash('Veuillez remplir tous les champs obligatoires', 'error')
            return redirect(url_for('nmr.sample_edit', sample_id=sample_id))
        
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
        sample.solvent=solvent
        sample.frequency=frequency
        sample.experiments=', '.join(experiments)
        sample.other_experiment=other_experiment_name if other_experiment and other_experiment_name else None,
        
        try:
            db.session.commit()
            flash('Échantillon mis à jour avec succès!', 'success')
            return redirect(url_for('nmr.sample_detail', sample_id=sample_id))
        except Exception as e:
            db.session.rollback()
            flash(f'Erreur lors de la mise à jour: {str(e)}', 'error')
            return redirect(url_for('nmr.sample_edit', sample_id=sample_id))
    
    # GET: Afficher le formulaire pré-rempli
    return render_template('nmr/sample_edit.html',
                           sample=sample,
                           user=current_user,
                           solvents=SOLVENTS,
                           stabilities=STABILITIES,
                           experiments_by_frequency=EXPERIMENTS_BY_FREQUENCY)
                           
@nmr_bp.route('/sample/<uuid:sample_id>/delete', methods=['POST'])
@login_required
def delete_sample(sample_id):
    """Rediriger vers la route principale de suppression"""
    from ..routes.main_routes import main_bp
    return main_bp.delete_sample(sample_id)