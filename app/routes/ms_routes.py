from flask import Blueprint, render_template, request, redirect, url_for, flash, send_from_directory, current_app, jsonify, session
from flask_babel import gettext as _, ngettext
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from sqlalchemy import desc
from celery.result import AsyncResult

import os
import io
import zipfile
from datetime import datetime
import pandas as pd
import pyopenms as oms
import logging

from ..models import db, MSSample, STATUS_NAMES, PeakAnnotation, PeakFormula
from .main_routes import allowed_file
from ..tasks import compute_spectrum_formulas
from ..utils.mol import read_mol, mol_from_smiles, mol_to_smiles, mol_to_formula, formula_to_mass
from ..utils.check_data import is_valid_reference, is_valid_formula
from ..utils.errors import log_error, report_error
from ..utils.adducts import ADDUCTS, find_adduct, neutral_mass
from ..utils.data_processing import load_mzml_spectra
from ..utils.peak_composition import FORMULA_RULES

ms_bp = Blueprint('ms', __name__, url_prefix='/ms')

logger = logging.getLogger(__name__)

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
        
        if formula and not is_valid_formula(formula):
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
    
    mzml_file = os.path.join(current_app.config['UPLOAD_FOLDER'], 'ms', 'spectra', f'{sample.id}.mzML')
    if os.path.exists(mzml_file):
        try:
            spectra = load_mzml_spectra(mzml_file, return_scan=False, return_data=True)

            for key in spectra:
                for peaks in (spectra[key]['centroid'], spectra[key]['profile']):
                    if peaks:
                        max_inten = max(p['y'] for p in peaks)
                        if max_inten > 0:
                            for p in peaks:
                                p['y'] = p['y'] / max_inten * 100.0
        except Exception as e:
            log_error(e, f"Reading mzML file {mzml_file}")
            flash(_('The spectrum could not be read.'), 'error')
            return redirect(url_for('main.index'))
    else:
        logger.error(f"MzML file {mzml_file} doest not exist.")
        flash(_('The spectrum file doest not exist.'), 'error')
        return redirect(url_for('main.index'))

    return render_template('ms/sample_spectrum.html',
                           sample=sample,
                           user=current_user,
                           spectrum_pos=spectra['+']['centroid'],
                           spectrum_neg=spectra['-']['centroid'],
                           spectrum_pos_raw=spectra['+']['profile'],
                           spectrum_neg_raw=spectra['-']['profile'],
                           tic_pos=spectra['+']['tic'],
                           tic_neg=spectra['-']['tic'],
                           adducts=ADDUCTS)
                           
@ms_bp.route('/sample/<int:sample_id>/spectrum/annotations')
@login_required
def spectrum_annotations(sample_id):
    """Liste des attributions d'adduits d'un spectre (JSON)"""
    sample = db.get_or_404(MSSample, sample_id)
    if sample.user_id != current_user.id and not current_user.is_admin:
        return jsonify({'error': _('Access denied')}), 403
    rows = db.session.scalars(
        db.select(PeakAnnotation)
        .where(PeakAnnotation.sample_id == sample_id)
        .order_by(PeakAnnotation.charge.desc(), PeakAnnotation.mz)
    ).all()
    return jsonify([{
        'id': r.id,
        'polarity': '+' if r.charge > 0 else '-',
        'mz': r.mz,
        'adduct': r.adduct,  # code stable stocké en base (ex. 'M+H')
        'adduct_label': (find_adduct('+' if r.charge > 0 else '-', r.adduct) or {}).get('label', r.adduct),
        'neutral_mass': r.neutral_mass,
        'created_at': r.created_at.isoformat() if r.created_at else None,
    } for r in rows])

@ms_bp.route('/sample/<int:sample_id>/spectrum/annotations', methods=['POST'])
@login_required
def save_annotation(sample_id):
    """Crée ou met à jour l'adduit attribué à un pic (JSON : polarity, mz, adduct)."""
    sample = db.get_or_404(MSSample, sample_id)
    if sample.user_id != current_user.id and not current_user.is_admin:
        return jsonify({'error': _('Access denied')}), 403

    data = request.get_json(force=True, silent=True) or {}
    polarity = data.get('polarity')  # '+' | '-'
    key = data.get('adduct')  # code de l'adduit (ex. 'M+H')
    try:
        mz = float(data.get('mz'))
    except (TypeError, ValueError):
        return jsonify({'error': _('Invalid m/z')}), 400
    adduct = find_adduct(polarity, key)
    if adduct is None:
        return jsonify({'error': _('Unknown adduct')}), 400

    charge = adduct['z']  # charge signée de l'adduit, stockée en SmallInteger (ex. +1 / -1)
    mz_r = round(mz, 4)
    row = db.session.scalars(db.select(PeakAnnotation).where(
        PeakAnnotation.sample_id == sample_id,
        PeakAnnotation.charge == charge,
        PeakAnnotation.mz == mz_r
    )).first()
    code = adduct['code']  # on stocke le code, pas le label affichable
    if row:
        # upsert : le pic était déjà annoté, on réattribue l'adduit
        row.adduct = code
        row.neutral_mass = neutral_mass(mz_r, adduct)
        row.user_id = current_user.id
    else:
        row = PeakAnnotation(
            sample_id=sample_id, charge=charge, mz=mz_r,
            adduct=code, neutral_mass=neutral_mass(mz_r, adduct),
            user_id=current_user.id,
        )
        db.session.add(row)
    db.session.commit()
    return jsonify({'ok': True, 'id': row.id, 'polarity': polarity, 'mz': row.mz,
                    'adduct': row.adduct, 'adduct_label': adduct['label'],
                    'neutral_mass': row.neutral_mass})

@ms_bp.route('/sample/<int:sample_id>/spectrum/annotations/<int:annotation_id>', methods=['DELETE'])
@login_required
def delete_annotation(sample_id, annotation_id):
    """Supprime une attribution d'adduit."""
    sample = db.get_or_404(MSSample, sample_id)
    if sample.user_id != current_user.id and not current_user.is_admin:
        return jsonify({'error': _('Access denied')}), 403
    row = db.get_or_404(PeakAnnotation, annotation_id)
    if row.sample_id != sample_id:
        return jsonify({'error': _('Invalid annotation')}), 400
    db.session.delete(row)
    db.session.commit()
    return jsonify({'ok': True})

def _saved_formulas_results(sample_id):
    """Formules brutes persistées en base pour un échantillon, avec les infos de leur annotation."""
    stmt = (
        db.select(PeakFormula, PeakAnnotation)
        .join(PeakAnnotation, PeakFormula.annotation_id == PeakAnnotation.id)
        .where(PeakAnnotation.sample_id == sample_id)
        .order_by(PeakAnnotation.charge.desc(), PeakAnnotation.mz, PeakFormula.id)
    )
    results = []
    for formula, ann in db.session.execute(stmt):
        polarity = '+' if ann.charge > 0 else '-'
        adduct = find_adduct(polarity, ann.adduct) or {}
        results.append({
            'annotation_id': ann.id,
            'polarity': polarity,
            'adduct': ann.adduct,
            'adduct_label': adduct.get('label', ann.adduct),
            'mz': ann.mz,
            'formula': formula.formula,
            'neutral_mass': formula.neutral_mass,
            'mz_exp': formula.mz_exp,
            'mz_theo': formula.mz_theo,
            'delta_ppm': formula.delta_ppm,
            'delta_mda': formula.delta_mda,
            'hc': formula.hc,
            'rdbe': formula.rdbe,
            'rms': formula.rms,
        })
    return results

def _formula_task_params(payload):
    """Valide le payload JSON du POST /spectrum/formulas et construit les paramètres
    passés à la tâche Celery (compute_formulas). Retourne None si invalide."""
    if not isinstance(payload, dict):
        return None
    try:
        tol = float(payload.get('tolerance_ppm', 5))
    except (TypeError, ValueError):
        return None
    if not (0 < tol <= 1000):
        return None
    rules = payload.get('rules')
    if rules is None:
        rules = list(FORMULA_RULES)
    elif isinstance(rules, (list, tuple)):
        rules = [r for r in rules if r in FORMULA_RULES]
    else:
        return None
    params = {'tolerance_ppm': tol, 'rules': rules, 'min_formula': None, 'max_formula': None}
    for key in ('min_formula', 'max_formula'):
        val = payload.get(key)
        if val is None:
            continue
        if not isinstance(val, str):
            return None
        val = val.strip()
        if not val:
            continue
        if not is_valid_formula(val):
            return None
        params[key] = val
    return params

@ms_bp.route('/sample/<int:sample_id>/spectrum/formulas', methods=['GET', 'POST'])
@login_required
def spectrum_formulas(sample_id):
    """Formules brutes des pics annotés (JSON) : GET = formules persistées en base,
    POST = lance le calcul asynchrone via Celery (task_id)."""
    sample = db.get_or_404(MSSample, sample_id)
    if sample.user_id != current_user.id and not current_user.is_admin:
        return jsonify({'error': _('Access denied')}), 403

    if request.method == 'POST':
        params = _formula_task_params(request.get_json(silent=True))
        if params is None:
            return jsonify({'error': _('Invalid formula parameters')}), 400
        # Le traitement lourd (compute_formulas) est délégué à une tâche Celery
        task = compute_spectrum_formulas.delay(sample_id, params)
        return jsonify({'ok': True, 'task_id': task.id}), 202

    return jsonify({'ok': True, 'results': _saved_formulas_results(sample_id)})

@ms_bp.route('/sample/<int:sample_id>/spectrum/formulas/<task_id>')
@login_required
def spectrum_formulas_status(sample_id, task_id):
    """État et résultat de la tâche Celery de calcul des formules brutes (JSON)."""
    sample = db.get_or_404(MSSample, sample_id)
    if sample.user_id != current_user.id and not current_user.is_admin:
        return jsonify({'error': _('Access denied')}), 403

    result = AsyncResult(task_id)
    if result.state == 'SUCCESS':
        payload = result.result if isinstance(result.result, dict) else {}
        if payload.get('sample_id') != sample_id:
            return jsonify({'error': _('Invalid task result')}), 403
        if not payload.get('ok'):
            return jsonify({'ok': False, 'state': result.state, 'error': payload.get('error', _('Task failed'))})
        # Les formules sont persistées en base par la tâche : lecture depuis la BDD
        return jsonify({'ok': True, 'state': result.state, 'results': _saved_formulas_results(sample_id)})
    if result.state in ('FAILURE', 'REVOKED'):
        return jsonify({'ok': False, 'state': result.state, 'error': _('Task failed')})
    return jsonify({'ok': True, 'state': result.state}), 202
    
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
            
        if formula and not is_valid_formula(formula):
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
                    unique_filename = f"{secure_filename(current_user.username)}_{timestamp}_{filename}"
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
                with db.session.begin_nested():
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
                log_error(e, f"Import, line {sample_data['line']}")
                errors.append(_('Line %(line)s: invalid data', line=line))
                continue
                
        if created_samples:
            db.session.commit()  # un seul commit atomique pour tout le lot valide
            session['imported_sample_ids'] = [s.id for s in created_samples]
            flash(ngettext('%(num)s sample imported successfully!',
                           '%(num)s samples imported successfully!',
                           num=len(created_samples)), 'success')
        else:
            db.session.rollback()

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