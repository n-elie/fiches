import csv
import io
from collections.abc import Callable
from datetime import datetime

from werkzeug.security import generate_password_hash
from flask import Blueprint, render_template, request, redirect, url_for, flash, send_file, current_app, jsonify
from flask_babel import gettext as _
from flask_login import login_required, current_user
from celery.result import AsyncResult
from sqlalchemy import desc

import pandas as pd

from ..models import db, Sample, SampleStatus, User, Analysis
from ..tasks import process_sample_analysis

admin_bp = Blueprint('admin', __name__)

@admin_bp.before_request
def require_admin():
    if not current_user.is_authenticated or not current_user.is_admin:
        flash(_('Access restricted to administrators.'), 'danger')
        return redirect(url_for('main.index'))

@admin_bp.route('/dashboard')
@login_required
def dashboard():
    """Tableau de bord administrateur"""

    total_samples = db.session.scalar(
        db.select(db.func.count()).select_from(Sample)
    )
    total_users = db.session.scalar(
        db.select(db.func.count()).select_from(User)
    )
    pending_samples = db.session.scalar(
        db.select(db.func.count()).select_from(Sample).where(Sample.status == SampleStatus.pending)
    )
    analysing_samples = db.session.scalar(
    db.select(db.func.count()).select_from(Sample).where(Sample.status == SampleStatus.analysing)
    )
    completed_samples = db.session.scalar(
        db.select(db.func.count()).select_from(Sample).where(Sample.status == SampleStatus.completed)
    )
    recent_samples = db.session.scalars(
        db.select(Sample).order_by(desc(Sample.created_at)).limit(10)
    ).all()
    users = db.session.scalars(
        db.select(User).order_by(User.username)
    ).all()

    return render_template('admin/dashboard.html',
                         total_samples=total_samples,
                         total_users=total_users,
                         pending_samples=pending_samples,
                         analysing_samples=analysing_samples,
                         completed_samples=completed_samples,
                         recent_samples=recent_samples,
                         users=users,
                         user=current_user)

@admin_bp.route('/samples')
@login_required
def all_samples():
    """Liste de tous les échantillons"""
    
    from ..routes.main_routes import samples
    return samples(template='admin/samples.html', show_users='all')

@admin_bp.route('/users')
@login_required
def all_users():
    """Liste de tous les utilisateurs"""

    role_filter = request.args.get('role', '')
    type_filter = request.args.get('type', '')

    stmt = db.select(User)
    if role_filter == 'admin':
        stmt = stmt.where(User.is_admin.is_(True))
    elif role_filter == 'user':
        stmt = stmt.where(User.is_admin.is_(False))
    if type_filter == 'ldap':
        stmt = stmt.where(User.is_ldap.is_(True))
    elif type_filter == 'local':
        stmt = stmt.where(User.is_ldap.is_(False))
        
    search_filter = request.args.get('search', '')
    if search_filter:
        stmt = stmt.where(User.username.ilike(f'%{search_filter}%'))

    sort_columns = {
        'username': User.username,
        'full_name': User.full_name,
        'role': User.is_admin,
        'type': User.is_ldap,
        'last_login': User.last_login,
    }
    sort_by = request.args.get('sort', 'username')
    sort_order = request.args.get('order', 'asc')
    if sort_order not in ('asc', 'desc'):
        sort_order = 'asc'

    if sort_by == 'samples':
        stmt = stmt.outerjoin(Sample, Sample.user_id == User.id).group_by(User.id)
        order_column = db.func.count(Sample.id)
    else:
        if sort_by not in sort_columns:
            sort_by = 'username'
        order_column = sort_columns[sort_by]

    if sort_order == 'desc':
        stmt = stmt.order_by(desc(order_column))
    else:
        stmt = stmt.order_by(order_column)
        
    # Paramètres de pagination
    page = request.args.get('page', 1, type=int)
    per_page = current_app.config['USERS_PER_PAGE']  # Nombre d'utilisateurs par page
    
    # Pagination
    paginated_users = db.paginate(stmt, page=page, per_page=per_page, error_out=False)

    users = db.session.scalars(stmt).all()
    return render_template('admin/users.html', 
                           users=paginated_users.items,  # Liste des utilisateurs pour la page courante
                           pagination=paginated_users,   # Objet de pagination
                           search_filter=search_filter,
                           role_filter=role_filter,
                           type_filter=type_filter,
                           sort_by=sort_by,
                           sort_order=sort_order)
    
def _export_data(samples:list[Sample], callback:Callable[[Sample | None], list], data_format:str='csv'):
    """ Exporter les données en CSV ou Excel """
    match data_format:
        case 'csv':
            output = io.StringIO()
            writer = csv.writer(output, delimiter=';')
            line = callback(None)  # Header
            if line is not None:
                writer.writerow(line)
            for sample in samples:
                writer.writerow(callback(sample))
            output.seek(0)
            output = io.BytesIO(output.getvalue().encode('utf-8-sig'))
        case 'excel':
            for sample in samples:
                data.append(callback(sample))
            df = pd.DataFrame(data)
            output = io.BytesIO()
            df.to_excel(output, index=False, engine='openpyxl')
            output.seek(0)
        case _:
            return
    return output
    
@admin_bp.route('/export/csv')
@login_required
def export_csv():
    """Exporter les données en CSV"""

    samples = db.session.scalars(
        db.select(Sample).join(User)
    ).all()
    
    def callback(sample: Sample | None) -> list:
        if sample is None:
            return[
                'ID', 'Date de création', 'Utilisateur', 'Équipe', 'Email',
                'Référence échantillon', 'Quantité (mg)', 'Unité',
                'Fichier structure', 'Statut', 'Notes']
        else:
            return [
                sample.id,
                sample.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                sample.user.full_name,
                sample.team,
                sample.user.email,
                sample.reference,
                sample.quantity,
                sample.structure_file,
                sample.status,
                sample.notes or '']
                
    output = _export_data(samples, callback, 'csv')

    return send_file(
        output,
        mimetype='text/csv',
        as_attachment=True,
        download_name=f'samples_export_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
    )


@admin_bp.route('/export/excel')
@login_required
def export_excel():
    """Exporter les données au format Excel"""

    data = []
    samples = db.session.scalars(
        db.select(Sample).join(User)
    ).all()

    def callback(sample: Sample | None) -> dict:
        return {
            'ID': sample.id,
            'Utilisateur': sample.user.full_name,
            'Email': sample.user.email,
            'Équipe': sample.team,
            'Référence': sample.reference,
            'Quantité (mg)': sample.quantity,
            'Fichier de structure': sample.structure_file,
            'Statut': sample.get_status(),
            'Date': sample.created_at.strftime('%Y-%m-%d %H:%M:%S')
        }

    output = _export_data(samples, callback, 'excel')

    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=f'samples_export_{datetime.now().strftime("%Y%m%d_%H%M%S")}.xlsx'
    )

@admin_bp.route('/sample-list')
@login_required
def sample_list():
    """Rechercher des échantillons MS 'en attente' pour construire une sample list"""

    search_filter = request.args.get('search', '').strip()
    user_filter = request.args.get('user', '')

    users = db.session.scalars(
        db.select(User).order_by(User.username)
    ).all()

    return render_template('admin/sample_list.html',
                           users=users,
                           search_filter=search_filter,
                           user_filter=user_filter,
                           user=current_user)

@admin_bp.route('/sample-list/search')
@login_required
def sample_list_search():
    """Recherche AJAX (JSON) des échantillons MS 'en attente'"""

    search_filter = request.args.get('search', '').strip()
    user_filter = request.args.get('user', '')

    stmt = db.select(Sample).join(User).where(
        Sample.status == SampleStatus.pending,
        Sample.analysis_type == 'ms'
    )
    if search_filter:
        stmt = stmt.where(Sample.reference.ilike(f'%{search_filter}%'))
    if user_filter:
        stmt = stmt.where(Sample.user_id == user_filter)
    stmt = stmt.order_by(desc(Sample.created_at))
    samples = db.session.scalars(stmt).all()
    
    return jsonify([{
        'id': sample.id,
        'reference': sample.reference,
        'team': sample.team,
        'user': sample.user.full_name,
        'formula': sample.get_html_formula(),
        'quantity': sample.quantity,
        'created_at': sample.created_at.strftime('%d/%m/%Y %H:%M')
    } for sample in samples])

@admin_bp.route('/samples/export-sample-list')
@login_required
def export_sample_list():
    """Route AJAX : renvoie en JSON la référence et l'uuid des échantillons
    sélectionnés (paramètre 'ids', séparés par des virgules), dans l'ordre demandé (admin only)"""

    raw_ids = request.args.get('ids', '')
    try:
        sample_ids = [int(sid.strip()) for sid in raw_ids.split(',') if sid.strip()]
    except ValueError:
        return jsonify({'error': _('Invalid sample ID')}), 400

    if not sample_ids:
        return jsonify({'error': _('No sample selected')}), 400

    samples = db.session.scalars(
        db.select(Sample).where(Sample.id.in_(sample_ids))
    ).all()

    if not samples:
        return jsonify({'error': _('No sample found')}), 404

    # Conserver l'ordre de la liste construite côté client
    samples_by_id = {sample.id: sample for sample in samples}
    ordered_samples = [samples_by_id[sid] for sid in sample_ids if sid in samples_by_id]

    return jsonify([{
        'id': sample.id,
        'reference': sample.reference,
        'uuid': str(sample.uuid)
    } for sample in ordered_samples])
    
@admin_bp.route('/sample-list/validate', methods=['POST'])
@login_required
def validate_sample_list():
    """Route AJAX : passe les échantillons sélectionnés ('pending') en statut 'analysing' (admin only)"""

    raw_ids = request.form.get('ids', '')
    try:
        sample_ids = [int(sid.strip()) for sid in raw_ids.split(',') if sid.strip()]
    except ValueError:
        return jsonify({'error': _('Invalid sample ID')}), 400

    if not sample_ids:
        return jsonify({'error': _('No sample selected')}), 400

    samples = db.session.scalars(
        db.select(Sample).where(
            Sample.id.in_(sample_ids),
            Sample.status == SampleStatus.pending
        )
    ).all()

    if not samples:
        return jsonify({'error': _('No pending sample found')}), 404

    for sample in samples:
        sample.status = SampleStatus.analysing
    db.session.commit()

    return jsonify({
        'updated': [{
            'id': sample.id,
            'reference': sample.reference,
            'status': sample.status.name
        } for sample in samples]
    })

@admin_bp.route('/sample/<int:sample_id>/update', methods=['POST'])
@login_required
def update_sample_status(sample_id):
    """Mettre à jour le statut d'un échantillon"""

    sample = db.get_or_404(Sample, sample_id)
    new_status = request.form.get('status')
  
    if new_status in SampleStatus:
        sample.status = new_status
        db.session.commit()
        ash(_('Status updated successfully'), 'success')
    else:
        flash(_('Invalid status'), 'error')

    return redirect(request.referrer)
    
@admin_bp.route('/users/create', methods=['GET', 'POST'])
@login_required
def create_user():
    """Créer un nouvel utilisateur local"""
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip()
        full_name = request.form.get('full_name', '').strip()
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')
        teams = request.form.get('teams', '').strip()
        is_admin = request.form.get('is_admin') == 'on'

        # Validation
        errors = []
        if not username:
            errors.append(_('Username is required'))
        if not email:
            errors.append(_('Email is required'))
        if not password:
            errors.append(_('Password is required'))
        if password and password != confirm_password:
            errors.append(_('Passwords do not match'))
        if db.session.scalar_one_or_none(db.select(User).where(User.username == username)) is not None:
            errors.append(_('This username already exists'))
        if db.session.scalars(db.select(User).where(User.email == email).limit(1)).first():
            errors.append(_('This email is already in use'))

        if errors:
            for error in errors:
                flash(error, 'error')
            return redirect(url_for('admin.create_user'))

        # Créer l'utilisateur local
        user = User(
            username=username,
            email=email,
            full_name=full_name,
            teams=teams,
            is_admin=is_admin,
            is_ldap=False,  # Utilisateur LOCAL
            ldap_dn=None
        )
        user.set_password(password)  # Hash du mot de passe

        db.session.add(user)
        db.session.commit()

        flash(_('User %(username)s created successfully!', username=username), 'success')
        return redirect(url_for('admin.all_users'))

    return render_template('admin/create_user.html')

@admin_bp.route('/users/<int:user_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_user(user_id):
    """Éditer un utilisateur (LDAP ou local)"""
    user = db.get_or_404(User, user_id)

    if request.method == 'POST':
        user.username = request.form.get('username', user.username).strip()
        user.email = request.form.get('email', user.email).strip()
        user.full_name = request.form.get('full_name', user.full_name).strip()
        user.teams = request.form.get('teams', user.teams).strip()
        if user.id != current_user.id:
            new_is_admin = request.form.get('is_admin') == 'on'
            if user.is_admin and not new_is_admin:
                admin_count = db.session.scalar(
                    db.select(db.func.count()).select_from(User).where(User.is_admin.is_(True))
                )
                if admin_count <= 1:
                    flash(_('At least one administrator must remain.'), 'error')
                    return redirect(url_for('admin.edit_user', user_id=user_id))
            user.is_admin = new_is_admin

        # Mise à jour du mot de passe (uniquement pour les utilisateurs locaux)
        password = request.form.get('password', '')
        if password and user.is_local_user():
            confirm_password = request.form.get('confirm_password', '')
            if password == confirm_password:
                user.set_password(password)
            else:
                flash(_('Passwords do not match'), 'error')
                return redirect(url_for('admin.edit_user', user_id=user_id))

        db.session.commit()
        flash(_('User %(username)s updated successfully!', username=user.username), 'success')
        return redirect(url_for('admin.all_users'))

    return render_template('admin/create_user.html', user=user, current_user=current_user)

@admin_bp.route('/users/<int:user_id>/delete', methods=['POST'])
@login_required
def delete_user(user_id):
    """Supprimer un utilisateur (uniquement local)"""
    user = db.get_or_404(User, user_id)

    # Empêcher la suppression des utilisateurs LDAP
    if user.is_ldap:
        flash(_('Cannot delete an LDAP user. Edit it via LDAP.'), 'error')
        return redirect(url_for('admin.all_users'))

    # Réattribuer les échantillons de l'utilisateur
    stmt = (
        db.update(Sample)
        .where(Sample.user_id == user_id)
        .values(user_id=current_user.id)
    )
    db.session.execute(stmt)

    db.session.delete(user)
    db.session.commit()

    flash(_('User %(username)s deleted successfully!', username=user.username), 'success')
    return redirect(url_for('admin.all_users'))
    
@admin_bp.route('/analysis/create', methods=['GET', 'POST'])
@login_required
def create_analysis():
    """Créer une Analysis manuellement (synchronement)"""
    if request.method == 'POST':
        sample_id = request.form.get('sample_id')
        results = request.form.get('results')

        # Validation
        if not sample_id:
            flash(_('Sample ID is required'), 'error')
            return redirect(url_for('admin.create_analysis'))

        sample = db.session.get(Sample, sample_id)
        if not sample:
            flash(_('Sample not found'), 'error')
            return redirect(url_for('admin.create_analysis'))

        # Créer l'Analysis
        analysis = Analysis(
            sample_id=sample_id,
            results_file=results
        )

        db.session.add(analysis)
        db.session.commit()

        flash(_('Analysis created successfully for %(ref)s', ref=sample.reference), 'success')
        return redirect(url_for('admin.create_analysis', sample_id=sample_id))

    # GET: Afficher le formulaire
    samples = db.session.scalars(
        db.select(Sample).order_by(Sample.created_at.desc())
    ).all()
    return render_template('admin/create_analysis.html', samples=samples)

@admin_bp.route('/analysis/<int:sample_id>/process', methods=['POST'])
@login_required
def start_analysis_task(sample_id):
    """
    Lancer une tâche Celery pour traiter un échantillon.
    Cette route déclenche le traitement ASYNCHRONE.
    """
    sample = db.get_or_404(Sample, sample_id)

    # Lancer la tâche Celery
    task = process_sample_analysis.delay(sample_id)
    sample.celery_task_id = task.id
    db.session.commit()

    flash(_('Analysis task started for %(ref)s (ID: %(task_id)s)', ref=sample.reference, task_id=task.id), 'success')
    return redirect(request.referrer)

@admin_bp.route('/analysis/task/<task_id>/status')
@login_required
def check_task_status(task_id):
    """Vérifier l'état d'une tâche Celery"""
    
    task = AsyncResult(task_id)

    if task.state == 'pending':
        response = {'state': task.state, 'status': _('Pending...')}
    elif task.state != 'failure':
        response = {
            'state': task.state,
            'result': task.result
        }
    else:
        response = {
            'state': task.state,
            'status': str(task.info)  # Message d'erreur
        }

    return jsonify(response)