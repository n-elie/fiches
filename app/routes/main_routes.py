from flask import (Blueprint, render_template, request, redirect,
                   url_for, flash, send_from_directory, current_app,
                   make_response, session)
from flask_babel import gettext as _, ngettext
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from sqlalchemy import desc
import os
from datetime import datetime
from urllib.parse import urlparse

from ..models import db, Sample, User, STATUS_NAMES, MSSample, NMRSample
from ..utils.pdf_utils import create_analysis_sheet_pdf

main_bp = Blueprint('main', __name__)

@main_bp.route('/lang/<lang>')
def set_language(lang):
    ref = request.referrer
    if lang in current_app.config['BABEL_SUPPORTED_LOCALES']:
        session['lang'] = lang
        
    ref = request.referrer
    if ref and urlparse(ref).netloc == request.host:
        return redirect(ref)
    return redirect(url_for('main.index'))

def allowed_file(filename):
    """Vérifier si le fichier a une extension autorisée"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in current_app.config['ALLOWED_EXTENSIONS']
    
def samples(template='samples.html', show_users='current', sample_type=Sample):
    status_filter = request.args.get('status', '')
    type_filter = request.args.get('type', '')
    user_filter = request.args.get('user', '')
    search_filter = request.args.get('search', '')
    show_type = (sample_type==Sample)
    
    # Paramètres de pagination
    page = request.args.get('page', 1, type=int)
    per_page = current_app.config['SAMPLES_PER_PAGE']  # Nombre d'échantillons par page
    
    stmt = db.select(sample_type)
    if status_filter:
        stmt = stmt.where(sample_type.status == status_filter)
    if type_filter:
        stmt = stmt.where(sample_type.analysis_type == type_filter)
    if show_users == 'current':
        stmt = stmt.where(sample_type.user_id == current_user.id)
    if current_user.is_admin and user_filter:
        stmt = stmt.where(sample_type.user_id == user_filter)
        
    if search_filter:
        stmt = stmt.where(sample_type.reference.ilike(f'%{search_filter}%'))

    # Tri
    sort_columns = {
        'analysis_type': Sample.analysis_type,
        'reference': Sample.reference,
        'quantity': Sample.quantity,
        'status': Sample.status,
        'created_at': Sample.created_at,
    }
    sort_by = request.args.get('sort', 'created_at')
    sort_order = request.args.get('order', 'desc')

    if sort_by not in sort_columns:
        sort_by = 'created_at'
    order_column = sort_columns[sort_by]

    if sort_order == 'desc':
        stmt = stmt.order_by(desc(order_column))
    else:
        stmt = stmt.order_by(order_column)
        
    # Pagination
    paginated_samples = db.paginate(stmt, page=page, per_page=per_page, error_out=False)
    
    users = db.session.scalars(
        db.select(User).order_by(User.username)
    ).all() if current_user.is_admin else None

    return render_template(template,
                         samples=paginated_samples.items,  # Liste des échantillons pour la page courante
                         pagination=paginated_samples,     # Objet de pagination
                         user=current_user,
                         users=users,
                         sample_type=sample_type.get_type() if sample_type is not Sample else None,
                         status_filter=status_filter,
                         type_filter=type_filter,
                         user_filter=user_filter if current_user.is_admin else '',
                         search_filter=search_filter,
                         sort_by=sort_by,
                         sort_order=sort_order,
                         status_names=STATUS_NAMES)

@main_bp.route('/')
def index():
    """Page d'accueil"""
    if current_user.is_authenticated:
        return redirect(url_for('main.user_samples'))
    return render_template('index.html')

@main_bp.route('/favicon.svg')
def favicon():
    return send_from_directory(os.path.join(current_app.root_path, 'static', 'images'),
                               'favicon.svg', mimetype='image/svg+xml')

@main_bp.route('/samples')
@login_required
def user_samples():
    """Liste des échantillons de l'utilisateur"""
    
    return samples(show_users='current')

def _delete_samples(samples):
    # Vérifier les permissions et le statut
    deleted_count = 0
    errors = []

    for sample in samples:
        # Vérifier que l'utilisateur est le propriétaire ou admin
        if sample.user_id != current_user.id and not current_user.is_admin:
            errors.append(_('%(ref)s: access denied', ref=sample.reference))
            continue
        
        # Vérifier que le statut est "pending"
        if not sample.is_pending():
            errors.append(_('%(ref)s: only pending samples can be deleted', ref=sample.reference))
            continue

        # Supprimer le fichier de structure si il existe
        if sample.structure_file:
            filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], sample.analysis_type, 'structures', sample.structure_file)
            if os.path.exists(filepath):
                try:
                    os.remove(filepath)
                except Exception as e:
                    errors.append(_('%(ref)s: file deletion error - %(err)s', ref=sample.reference, err=str(e)))
                    continue

        # Supprimer l'échantillon de la base
        try:
            db.session.delete(sample)
            deleted_count += 1
        except Exception as e:
            db.session.rollback()
            errors.append(_('%(ref)s: database deletion error - %(err)s', ref=sample.reference, err=str(e)))
            continue

    db.session.commit()

    if deleted_count > 0:
        flash(ngettext('%(num)s sample deleted successfully', '%(num)s samples deleted successfully', num=deleted_count), 'success')

    for error in errors:
        flash(error, 'error')

@main_bp.route('/sample/<int:sample_id>/delete', methods=['POST'])
@login_required
def delete_sample(sample_id):
    """Supprimer un échantillon (uniquement si statut = pending)"""

    sample = db.get_or_404(Sample, sample_id)

    redirection = _delete_samples([sample])
    if redirection is not None:
        return redirection

    return redirect(url_for('main.user_samples'))
    
@main_bp.route('/samples/batch-delete', methods=['POST'])
@login_required
def batch_delete_samples():
    """Supprimer plusieurs échantillons en une seule action (uniquement si statut = pending)"""

    sample_ids = request.form.get('sample_ids', '')
    if not sample_ids:
        flash(_('No sample selected'), 'error')
        return redirect(url_for('main.user_samples'))

    sample_ids = [int(sid.strip()) for sid in sample_ids.split(',') if sid.strip()]
    if not sample_ids:
        flash(_('No valid sample selected'), 'error')
        return redirect(url_for('main.user_samples'))

    # Récupérer les échantillons
    samples = db.session.scalars(
        db.select(Sample).where(Sample.id.in_(sample_ids))
    ).all()

    if not samples:
        flash(_('No sample found'), 'error')
        return redirect(url_for('main.user_samples'))

    redirection = _delete_samples(samples)
    if redirection is not None:
        return redirection

    return redirect(url_for('main.user_samples'))

@main_bp.route('/download/<filename>')
@login_required
def download_file(filename):
    """Télécharger un fichier de structure"""
    
    sample = db.session.scalars(
        db.select(Sample).filter_by(structure_file=filename).limit(1)
    ).first()
    if not sample or (sample.user_id != current_user.id and not current_user.is_admin):
        flash(_('Access denied'), 'error')
        return redirect(url_for('main.index'))
    return send_from_directory(os.path.join(current_app.config['UPLOAD_FOLDER'], sample.analysis_type, 'structures'), filename, as_attachment=True)
    
@main_bp.route('/sample/<int:sample_id>/pdf')
@login_required
def generate_pdf(sample_id):
    """Générer une fiche d'analyse PDF pour un échantillon"""
    
    # Récupérer l'échantillon (peut être Sample, MSSample ou NMRSample)
    sample = db.get_or_404(Sample, sample_id)
    
    # Vérifier les permissions
    if sample.user_id != current_user.id and not current_user.is_admin:
        flash(_('Access denied'), 'error')
        return redirect(url_for('main.index'))
    
    try:
        # Générer le PDF
        service_infos = current_app.config['SERVICES'].get(sample.analysis_type, {})
        service_name = service_infos.get('name', None)
        responsible_name = service_infos.get('responsible', None)
        phone_number = service_infos.get('phone', None)
        logo_path = os.path.join(current_app.static_folder, 'images', current_app.config['LOGO'])
        if not os.path.exists(logo_path):
            logo_path = None
        pdf_buffer = create_analysis_sheet_pdf(
            [sample], os.path.join(current_app.config['UPLOAD_FOLDER'], sample.analysis_type, 'structures'),
            service_name=service_name, responsible_name=responsible_name, phone_number=phone_number,
            logo_path=logo_path,
            base_url=request.host_url
        )
        
        # Créer la réponse
        response = make_response(pdf_buffer.getvalue())
        response.headers['Content-Type'] = 'application/pdf'
        response.headers['Content-Disposition'] = f'attachment; filename=fiche_analyse_{sample.reference}.pdf'
        
        return response
    except Exception as e:
        flash(_('Error while generating the PDF: %(err)s', err=str(e)), 'error')
        return redirect(request.referrer)
        
@main_bp.route('/samples/batch-pdf', methods=['POST'])
@login_required
def batch_generate_pdf():
    """
    Générer un PDF avec une page par échantillon
    pour les échantillons sélectionnés.
    """
    sample_ids = request.form.get('sample_ids', '')

    if not sample_ids:
        flash(_('No sample selected'), 'error')
        return redirect(url_for('main.user_samples'))

    sample_ids = [int(sid.strip()) for sid in sample_ids.split(',') if sid.strip()]
    if not sample_ids:
        flash(_('No valid sample selected'), 'error')
        return redirect(url_for('main.user_samples'))

    # Récupérer les échantillons (filtrer par utilisateur si non-admin)
    stmt = db.select(Sample).where(Sample.id.in_(sample_ids))
    if not current_user.is_admin:
        stmt = stmt.where(Sample.user_id == current_user.id)

    samples = db.session.scalars(stmt).all()
    if not samples:
        flash(_('No sample found'), 'error')
        return redirect(url_for('main.user_samples'))

    # Vérifier que tous les échantillons appartiennent à l'utilisateur ou que l'utilisateur est admin
    for sample in samples:
        if sample.user_id != current_user.id and not current_user.is_admin:
            flash(_('Access denied for sample %(ref)s', ref=sample.reference), 'error')
            return redirect(url_for('main.user_samples'))

    try:
        # Générer le PDF pour tous les échantillons
        service_infos = current_app.config['SERVICES'].get(sample.analysis_type, {})
        service_name = service_infos.get('name', None)
        responsible_name = service_infos.get('responsible', None)
        phone_number = service_infos.get('phone', None)
        logo_path = os.path.join(current_app.static_folder, 'images', current_app.config['LOGO'])
        if not os.path.exists(logo_path):
            logo_path = None
        pdf_buffer = create_analysis_sheet_pdf(
            samples, os.path.join(current_app.config['UPLOAD_FOLDER'], sample.analysis_type, 'structures'),
            service_name=service_name, responsible_name=responsible_name, phone_number=phone_number,
            logo_path=logo_path,
            base_url=request.host_url
        )

        # Créer la réponse
        response = make_response(pdf_buffer.getvalue())
        response.headers['Content-Type'] = 'application/pdf'
        response.headers['Content-Disposition'] = 'attachment; filename=batch_analyses.pdf'

        return response

    except Exception as e:
        flash(_('Error while generating the batch PDF: %(err)s', err=str(e)), 'error')
        return redirect(url_for('main.user_samples'))