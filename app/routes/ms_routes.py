from flask import Blueprint, render_template, request, redirect, url_for, flash, send_from_directory, current_app, jsonify, session
from flask_babel import gettext as _, ngettext
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from sqlalchemy import desc
import os
import io
import zipfile
from datetime import datetime
import pandas as pd

from ..models import db, MSSample, STATUS_NAMES
from .main_routes import allowed_file
from ..utils.mol import read_mol, mol_from_smiles, mol_to_smiles, mol_to_formula, formula_to_mass
from ..utils.check_data import is_valid_reference, is_valid_formula
from ..utils.errors import log_error, report_error

ms_bp = Blueprint('ms', __name__, url_prefix='/ms')

IMPORT_EXTENSIONS = {'.xlsx', '.ods', '.csv'}
ZIP_MAGIC = b'PK\x03\x04'  # .xlsx et .ods sont des conteneurs ZIP

def _detect_import_filetype(filename: str, data: bytes) -> str:
    """Détecte le vrai format à partir de l'extension (whitelist) et des magic bytes.
    Le Content-Type envoyé par le client n'est jamais utilisé."""
    ext = os.path.splitext(filename or '')[1].lower()
    if ext not in IMPORT_EXTENSIONS:
        raise ValueError(
            _('File type not allowed. Accepted formats:') + ' .xlsx, .ods, .csv'
        )
    if ext == '.csv':
        return 'csv'
    if not data.startswith(ZIP_MAGIC):
        raise ValueError(_('The file is not a valid .xlsx/.ods archive'))
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            names = set(z.namelist())
    except zipfile.BadZipFile:
        raise ValueError(_('The file is not a valid .xlsx/.ods archive'))
    if ext == '.xlsx' and 'xl/workbook.xml' not in names:
        raise ValueError(_('The file is not a valid .xlsx workbook'))
    if ext == '.ods' and 'mimetype' not in names:
        raise ValueError(_('The file is not a valid .ods document'))
    return 'excel' if ext == '.xlsx' else 'ods'

@ms_bp.route('/sample/submit', methods=['GET', 'POST'])
@login_required
def submit_sample():
    """Formulaire de soumission d'échantillon"""
    
    ms_config = current_app.config['SERVICES']['ms']
    structures_folder = os.path.join(current_app.config['UPLOAD_FOLDER'], 'ms', 'structures')
    
    os.makedirs(structures_folder, exist_ok=True)
    
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
        valid_solvents = ms_config['solvents'].keys()
        for solvent in solvents:
            if solvent not in valid_solvents:
                flash(_('The solvent is not available.'), 'error')
                return redirect(url_for('ms.submit_sample'))

        if not solvents and ((other_solvent and not other_solvent_name) or not other_solvent):
            flash(_('Please select at least one solvent'), 'error')
            return redirect(url_for('ms.submit_sample'))
            
        if not is_valid_reference(reference):
            flash(_('Invalid reference: only letters, digits, spaces, ".", "-" or "_" (max 100 characters)'), 'error')
            return redirect(url_for('ms.submit_sample'))
        
        if not is_valid_formula(formula):
            flash(_('Invalid formula: only letters, numbers, parentheses, brackets, charges (+, -), dots/asterisks for hydrates, and spaces (max 256 characters)'), 'error')
            return redirect(url_for('ms.submit_sample'))

        if not reference or not quantity:
            flash(_('Please fill in all required fields'), 'error')
            return redirect(url_for('ms.submit_sample'))

        if 'structure_file' not in request.files:
            flash(_('No structure file provided'), 'error')
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
                    unique_filename = f"{secure_filename(current_user.username)}_{timestamp}_{filename}"
                    filepath = os.path.join(structures_folder, unique_filename)
                    file.save(filepath)
                    
                    try:
                        mol = read_mol(filepath)
                        smiles = mol_to_smiles(mol)
                        formula = mol_to_formula(mol)
                    except (OSError, RuntimeError) as e:
                        log_error(e, f"Parsing Structuture file {unique_filename}")
                        # Supprimer le fichier de structure en cas d'erreur de lecture pour ne pas laisser de fichier orphelin
                        if os.path.exists(filepath):
                            os.path.unlink(filepath)
                        flash(_('The structure file could not be parsed.'), 'error')
                        return redirect(url_for('ms.submit_sample'))
                else:
                    flash(_('File type not allowed. Accepted formats:') + ' .cdx, .cdxml, .mol, .sdf', 'error')
                    return redirect(url_for('ms.submit_sample'))
                    
        if formula is not None:
            mass = formula_to_mass(formula)
        else:
            flash(_('Please select a structure file or enter a molecular formula'))
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
            flash(_('Sample submitted successfully!'), 'success')
            return redirect(url_for('ms.success', sample_id=sample.id))
        except Exception as e:
            db.session.rollback()
            report_error(e, _('Error during submission: the sample was not saved.'))
            return redirect(url_for('ms.submit_sample'))

    return render_template('ms/sample_submit.html',
                           user=current_user,
                           solvents=ms_config['solvents'])

@ms_bp.route('/success/<int:sample_id>')
@login_required
def success(sample_id):
    """Page de confirmation de soumission"""
    
    sample = db.get_or_404(MSSample, sample_id)
    if sample.user_id != current_user.id:
        flash(_('Access denied'), 'error')
        return redirect(url_for('main.index'))
    return render_template('success.html', sample=sample, user=current_user)
    
@ms_bp.route('/sample/<int:sample_id>')
@login_required
def sample_detail(sample_id):
    """Détails d'un échantillon"""
    
    ms_config = current_app.config['SERVICES']['ms']
    sample = db.get_or_404(MSSample, sample_id)
    
    if sample.user_id != current_user.id and not current_user.is_admin:
        flash(_('Access denied'), 'error')
        return redirect(url_for('main.index'))
    return render_template('sample_detail.html',
                           sample=sample,
                           user=current_user,
                           status_names=STATUS_NAMES,
                           solvents=ms_config['solvents'])
                           
@ms_bp.route('/samples')
@login_required
def user_samples():
    """Liste des échantillons MS de l'utilisateur"""
    
    from ..routes.main_routes import samples
    return samples(template='samples.html', show_users='current', sample_type=MSSample)
    
@ms_bp.route('/sample/<int:sample_id>/spectrum')
@login_required
def sample_spectrum(sample_id):
    """Visualiser le spectre d'un échantillon existant"""
    
    sample = db.get_or_404(MSSample, sample_id)
    
    # Vérifier que l'utilisateur est le propriétaire ou admin
    if sample.user_id != current_user.id and not current_user.is_admin:
        flash(_('Access denied'), 'error')
        return redirect(url_for('main.index'))
    
    return render_template('ms/sample_spectrum.html',
                           sample=sample)
    
    
@ms_bp.route('/sample/<int:sample_id>/edit', methods=['GET', 'POST'])
@login_required
def sample_edit(sample_id):
    """Éditer un échantillon existant"""
    
    ms_config = current_app.config['SERVICES']['ms']
    structures_folder = os.path.join(current_app.config['UPLOAD_FOLDER'], 'ms', 'structures')
    
    sample = db.get_or_404(MSSample, sample_id)
    
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
        solvents = request.form.getlist('solvents')
        other_solvent = request.form.get('other_solvent')
        other_solvent_name = request.form.get('other_solvent_name')
        
        # Validation : vérifier que tous les solvants sont valides
        valid_solvents = ms_config['solvents'].keys()
        for solvent in solvents:
            if solvent not in valid_solvents:
                flash(_('The solvent is not available.'), 'error')
                return redirect(url_for('ms.sample_edit', sample_id=sample_id))

        if not solvents and ((other_solvent and not other_solvent_name) or not other_solvent):
            flash(_('Please select at least one solvent'), 'error')
            return redirect(url_for('ms.sample_edit', sample_id=sample_id))
            
        if not is_valid_reference(reference):
            flash(_('Invalid reference: only letters, digits, spaces, ".", "-" or "_" (max 100 characters)'), 'error')
            return redirect(url_for('ms.sample_edit', sample_id=sample_id))
            
        if not is_valid_formula(formula):
            flash(_('Invalid formula: only letters, numbers, parentheses, brackets, charges (+, -), dots/asterisks for hydrates, and spaces (max 256 characters)'), 'error')
            return redirect(url_for('ms.sample_edit', sample_id=sample_id))
        
        if not reference or not quantity:
            flash(_('Please fill in all required fields'), 'error')
            return redirect(url_for('ms.sample_edit', sample_id=sample_id))
        
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
        sample.solvents=', '.join(solvents)
        sample.other_solvent=other_solvent_name if other_solvent and other_solvent_name else None
        
        try:
            db.session.commit()
            flash(_('Sample updated successfully!'), 'success')
            return redirect(url_for('ms.sample_detail', sample_id=sample_id))
        except Exception as e:
            db.session.rollback()
            report_error(e, _('Error during update: the sample was not saved.'))
            return redirect(url_for('ms.sample_edit', sample_id=sample_id))
    
    # GET: Afficher le formulaire pré-rempli
    return render_template('ms/sample_submit.html',
                           sample=sample,
                           user=current_user,
                           solvents=ms_config['solvents'])
                      
def _parse_import_file(file) -> tuple[list[dict], list[str]]:
    """Lit et valide un fichier d'import (xlsx, xls, ods, csv), partagé entre
    l'import réel (import_samples) et l'aperçu AJAX (import_samples_preview).

    Retourne (rows, errors) :
      - rows : dictionnaires prêts à être créés (line, reference, quantity, solvent,
               formula, mass, smiles, notes), avec formula/mass calculées si possible ;
      - errors : messages d'erreur par ligne.
    Lève ValueError en cas de problème sur le fichier (type non autorisé, lecture,
    colonnes manquantes).
    """
    
    data = file.read()
    if not data:
        raise ValueError(_('Empty file'))

    filetype = _detect_import_filetype(file.filename, data)
    stream = io.BytesIO(data)

    # Lire le fichier avec pandas
    try:
        match filetype:
            case 'excel':
                df = pd.read_excel(stream, engine='openpyxl')
            case 'ods':
                df = pd.read_excel(stream, engine='odf')
            case 'csv':
                df = pd.read_csv(stream, sep=';')

        df.columns = df.columns.str.lower()  # Normaliser les noms de colonnes
        df = df.replace(float('nan'), None)
    except ValueError:
        raise
    except Exception as e:
        log_error(e, "Import file reading")
        raise ValueError(_('Error while reading the file: it is corrupted or not a supported spreadsheet.'))

    # Vérifier que les colonnes requises sont présentes
    required_columns = ['reference', 'quantity']
    missing_columns = [col for col in required_columns if col not in df.columns]
    if missing_columns:
        log_error(e, "Missing columns in import file")
        raise ValueError(_('Missing columns in the file: %(cols)s', cols=", ".join(missing_columns)))

    rows = []
    errors = []
    for line, sample_data in enumerate(df.to_dict('records'), start=2):
        try:
            reference = sample_data.get('reference')
            quantity = sample_data.get('quantity')
            solvent = sample_data.get('solvent')
            formula = sample_data.get('formula')
            smiles = sample_data.get('smiles')
            notes = sample_data.get('notes')

            # Validation
            if not is_valid_reference(str(reference) if reference else ''):
                errors.append(_('Line %(line)s: invalid reference', line=line))
                continue
                
            if formula and not is_valid_formula(str(formula)):
                errors.append(_('Line %(line)s: invalid formula', line=line))
                continue
            
            if not reference or not quantity:
                errors.append(_('Line %(line)s: reference and quantity are required', line=line))
                continue

            # Calculer la formule si le SMILES est fourni
            if smiles:
                mol = mol_from_smiles(str(smiles))
                formula = mol_to_formula(mol)

            # Calculer la masse si la formule est fournie
            mass = None
            if formula:
                mass = formula_to_mass(str(formula))

            rows.append({
                'line': line,
                'reference': str(reference),
                'quantity': float(quantity),
                'solvent': str(solvent) if solvent else '',
                'formula': str(formula) if formula else '',
                'mass': mass,
                'smiles': str(smiles) if smiles else '',
                'notes': str(notes) if notes else '',
            })
        except Exception as e:
            log_error(e, f"Import, ligne {line}")
            errors.append(_('Line %(line)s: invalid data', line=line))

    return rows, errors
    
@ms_bp.route('/samples/import', methods=['GET', 'POST'])
@login_required
def import_samples():
    """Importer plusieurs échantillons depuis un fichier Excel ou CSV"""

    structures_folder = os.path.join(current_app.config['UPLOAD_FOLDER'], 'ms', 'structures')

    os.makedirs(structures_folder, exist_ok=True)

    if request.method == 'POST':
        # Verifier qu'un fichier est fourni
        if 'excel_file' not in request.files:
            flash(_('No Excel file provided'), 'error')
            return redirect(url_for('ms.import_samples'))

        file = request.files['excel_file']
        if file.filename == '':
            flash(_('Please select an Excel file'), 'error')
            return redirect(url_for('ms.import_samples'))

        # Lecture et validation du fichier (commun avec l'aperçu AJAX)
        try:
            samples_data, errors = _parse_import_file(file)
        except ValueError as e:
            report_error(e, "Import file reading")
            return redirect(url_for('ms.import_samples'))

        team = request.form.get('team')
        if not team:
            flash(_('Please select a team'), 'error')
            return redirect(url_for('ms.import_samples'))

        # Créer les échantillons
        created_samples = []
        for sample_data in samples_data:
            try:
                sample = MSSample(
                    team=team,
                    reference=sample_data['reference'],
                    quantity=sample_data['quantity'],
                    formula=sample_data['formula'] or None,
                    mass=sample_data['mass'],
                    smiles=sample_data['smiles'] or None,
                    solvents=sample_data['solvent'] or None,
                    notes=sample_data['notes'] or None,
                    user_id=current_user.id
                )
                db.session.add(sample)
                db.session.flush()  # pour récupérer l'ID
                created_samples.append(sample)
            except Exception as e:
                log_error(e, f"Import, ligne {line}")
                errors.append(_('Line %(line)s: invalid data', line=line))
                db.session.rollback()
                continue

        created_count = len(created_samples)
        if created_count > 0:
            db.session.commit()
            # Mémoriser les échantillons créés pour la page de confirmation
            session['imported_sample_ids'] = [s.id for s in created_samples]
            flash(ngettext('%(num)s sample imported successfully!', '%(num)s samples imported successfully!', num=created_count), 'success')

        for error in errors:
            flash(error, 'error')

        if created_count > 0:
            return redirect(url_for('ms.import_success'))

        return redirect(url_for('ms.user_samples'))

    # GET: Afficher le formulaire d'import
    return render_template('ms/import_samples.html',
                           user=current_user)
                           
@ms_bp.route('/samples/import/preview', methods=['POST'])
@login_required
def import_samples_preview():
    """Aperçu AJAX de l'import : parse le fichier et renvoie les lignes à valider,
    sans rien créer en base"""

    if 'excel_file' not in request.files:
        return jsonify({'error': _('No file provided')}), 400

    file = request.files['excel_file']
    if file.filename == '':
        return jsonify({'error': _('Please select a file')}), 400

        # Lecture et validation du fichier (commun avec l'import réel)
    try:
        rows, errors = _parse_import_file(file)
    except ValueError as e:
        return jsonify({'error': _('Error while reading the import file')}), 400

    return jsonify({
        'samples': rows,
        'errors': errors,
        'team': request.form.get('team', '')
    })
    
@ms_bp.route('/samples/import/success')
@login_required
def import_success():
    """Page de confirmation après un import réussi (modèle de la page 'success')"""

    sample_ids = session.get('imported_sample_ids', [])
    session.pop('imported_sample_ids', None)  # affichée une seule fois

    samples = db.session.scalars(
        db.select(MSSample).where(MSSample.id.in_(sample_ids))
    ).all() if sample_ids else []

    return render_template('ms/import_success.html',
                           samples=samples,
                           user=current_user)