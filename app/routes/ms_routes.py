from flask import Blueprint, render_template, request, redirect, url_for, flash, send_from_directory, current_app
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from sqlalchemy import desc
import os
from datetime import datetime
import pandas as pd

from ..models import db, MSSample, STATUS_NAMES
from .main_routes import allowed_file
from ..utils.mol import read_mol, mol_from_smiles, mol_to_smiles, mol_to_formula, formula_to_mass

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
        mass = None
        smiles = None
        if 'structure_file' in request.files:
            file = request.files['structure_file']
            if file.filename != '':
                if file and allowed_file(file.filename):
                    filename = secure_filename(file.filename)
                    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
                    unique_filename = f"{current_user.username}_{timestamp}_{filename}"
                    filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], unique_filename)
                    file.save(filepath)
                    
                    try:
                        mol = read_mol(filepath)
                        smiles = mol_to_smiles(mol)
                        formula = mol_to_formula(mol)
                    except (OSError, RuntimeError) as e:
                        flash(str(e), 'error')
                        return redirect(url_for('ms.submit_sample'))
                else:
                    flash('Type de fichier non autorisé. Formats acceptés: .cdx, .cdxml, .mol, .sdf', 'error')
                    return redirect(url_for('ms.submit_sample'))
                    
        if formula is not None:
            mass = formula_to_mass(formula)
        else:
            flash('Veuillez sélectionner un fichier de structure ou entrer une formule brute')
            return redirect(url_for('ms.submit_sample'))

        try:
            sample = MSSample(
                team=team,
                reference=reference,
                quantity=float(quantity),
                structure_file=unique_filename,
                formula=formula,
                mass=mass,
                smiles=smiles,
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

@ms_bp.route('/success/<int:sample_id>')
@login_required
def success(sample_id):
    """Page de confirmation de soumission"""
    sample = MSSample.query.get_or_404(sample_id)
    if sample.user_id != current_user.id:
        flash('Accès non autorisé', 'error')
        return redirect(url_for('main.index'))
    return render_template('ms/success.html', sample=sample, user=current_user)
    
@ms_bp.route('/sample/<int:sample_id>')
@login_required
def sample_detail(sample_id):
    """Détails d'un échantillon"""
    sample = MSSample.query.get_or_404(sample_id)
    if sample.user_id != current_user.id and not current_user.is_admin:
        flash('Accès non autorisé', 'error')
        return redirect(url_for('main.index'))
    return render_template('sample_detail.html',
                           sample=sample,
                           user=current_user,
                           status_names=STATUS_NAMES)
                           
@ms_bp.route('/samples')
@login_required
def user_samples():
    """Liste des échantillons MS de l'utilisateur"""
    
    from ..routes.main_routes import samples
    return samples(template='samples.html', users='current', sample_type=MSSample)
    
@ms_bp.route('/sample/<int:sample_id>/edit', methods=['GET', 'POST'])
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
                           
@ms_bp.route('/samples/import', methods=['GET', 'POST'])
@login_required
def import_samples():
    """Importer plusieurs échantillons depuis un fichier Excel ou CSV"""

    if request.method == 'POST':
        # Verifier qu'un fichier est fourni
        if 'excel_file' not in request.files:
            flash('Aucun fichier Excel fourni', 'error')
            return redirect(url_for('ms.import_samples'))

        file = request.files['excel_file']
        if file.filename == '':
            flash('Veuillez selectionner un fichier Excel', 'error')
            return redirect(url_for('ms.import_samples'))

        match file.mimetype:
            case 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet':
                filetype = 'excel'
            case 'text/csv' | 'application/csv' | 'application/vnd.ms-excel':
                filetype = 'csv'
            case 'application/vnd.oasis.opendocument.spreadsheet':
                filetype = 'ods'
            case _:
                flash('Type de fichier non autorisé. Formats acceptés: .xlsx, .xls, .ods, .csv', 'error')
                return redirect(url_for('ms.import_samples'))

        # Lire le fichier Excel avec pandas
        try:
            match filetype:
                case 'excel' | 'ods':
                    df = pd.read_excel(file)
                case 'csv':
                    df = pd.read_csv(file, sep=';')
            
            df.columns = df.columns.str.lower()  # Normaliser les noms de colonnes
            df = df.replace(float('nan'), None)

            # Vérifier que les colonnes requises sont présentes
            required_columns = ['reference', 'quantity']
            missing_columns = [col for col in required_columns if col not in df.columns]
            if missing_columns:
                flash(f'Colonnes manquantes dans le fichier: {", ".join(missing_columns)}', 'error')
                return redirect(url_for('ms.import_samples'))

            # Convertir en liste de dictionnaires
            samples_data = df.to_dict('records')

            # Créer les échantillons
            created_count = 0
            errors = []
            team = request.form.get('team')

            if not team:
                flash('Veuillez selectionner une équipe', 'error')
                return redirect(url_for('ms.import_samples'))

            os.makedirs(current_app.config['UPLOAD_FOLDER'], exist_ok=True)

            for sample_data in samples_data:
                try:
                    reference = sample_data.get('reference')
                    quantity = sample_data.get('quantity')
                    solvent = sample_data.get('solvent')
                    formula = sample_data.get('formula')
                    smiles = sample_data.get('smiles')
                    notes = sample_data.get('notes')

                    # Validation
                    if not reference or not quantity:
                        errors.append(f"Ligne {samples_data.index(sample_data) + 2}: Référence et quantité sont obligatoires")
                        continue

                    # Calculer la formule si le SMILES est fourni
                    if smiles:
                        mol = mol_from_smiles(smiles)
                        formula = mol_to_formula(mol)

                    # Calculer la masse si formule est fournie
                    mass = None
                    if formula:
                        try:
                            mass = formula_to_mass(formula)
                        except Exception as e:
                            errors.append(f"Ligne {samples_data.index(sample_data) + 2}: Erreur calcul masse - {str(e)}")
                            continue

                    # Créer l'échantillon
                    sample = MSSample(
                        team=team,
                        reference=str(reference),
                        quantity=float(quantity),
                        formula=str(formula) if formula else None,
                        mass=mass,
                        smiles=str(smiles) if smiles else None,
                        solvents=str(solvent) if solvent else None,
                        notes=str(notes) if notes else None,
                        user_id=current_user.id
                    )
                    db.session.add(sample)
                    created_count += 1

                except Exception as e:
                    errors.append(f"Ligne {samples_data.index(sample_data) + 2}: {str(e)}")
                    db.session.rollback()
                    continue

            if created_count > 0:
                db.session.commit()
                flash(f'{created_count} échantillon{"s" if created_count > 1 else ""} importé{"s" if created_count > 1 else ""} avec succès!', 'success')

            for error in errors:
                flash(error, 'error')

            return redirect(url_for('ms.user_samples'))

        except Exception as e:
            flash(f'Erreur lors de la lecture du fichier Excel: {str(e)}', 'error')
            return redirect(url_for('ms.import_samples'))

    # GET: Afficher le formulaire d'import
    return render_template('ms/import_samples.html',
                           user=current_user)