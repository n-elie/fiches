from flask import (Blueprint, render_template, request, redirect,
                   url_for, flash, send_from_directory, current_app,
                   make_response)
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from sqlalchemy import desc
import os
from datetime import datetime

from ..models import db, Sample, User, STATUS_NAMES, MSSample, NMRSample
from ..utils.pdf_utils import create_analysis_sheet_pdf

main_bp = Blueprint('main', __name__)

SERVICES = {
    'ms': ('Service HRMS', 'Nicolas Elie', '3016'),
    'nmr': ('Service RMN', 'Jean-François Gallard', '3125')
}

def allowed_file(filename):
    """Vérifier si le fichier a une extension autorisée"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in current_app.config['ALLOWED_EXTENSIONS']
    
def samples(template='samples.html', users='current', sample_type=Sample):
    status_filter = request.args.get('status', '')
    type_filter = request.args.get('type', '')
    user_filter = request.args.get('user', '')
    search_filter = request.args.get('search', '')
    show_type = (sample_type==Sample)
    
    # Paramètres de pagination
    page = request.args.get('page', 1, type=int)
    per_page = 10  # Nombre d'échantillons par page (ajustable)
    
    query = sample_type.query
    if status_filter:
        query = query.filter_by(status=status_filter)
    if type_filter:
        query = query.filter_by(analysis_type=type_filter)
    if users == 'current':
        query = query.filter_by(user_id=current_user.id)
    elif current_user.is_admin and user_filter:
        query = query.filter_by(user_id=user_filter)
        
    if search_filter:
        query = query.filter(
            sample_type.reference.ilike(f'%{search_filter}%')
        )

    # Tri
    sort_by = request.args.get('sort', 'created_at')
    sort_order = request.args.get('order', 'desc')

    if sort_order == 'desc':
        query = query.order_by(desc(getattr(sample_type, sort_by)))
    else:
        query = query.order_by(getattr(sample_type, sort_by))
        
    # Pagination
    paginated_samples = query.paginate(page=page, per_page=per_page, error_out=False)
    
    users = User.query.order_by(User.username).all() if current_user.is_admin else None

    return render_template(template,
                         samples=paginated_samples.items,  # Liste des échantillons pour la page courante
                         pagination=paginated_samples,     # Objet de pagination
                         user=current_user,
                         users=users,
                         show_type=show_type,
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

@main_bp.route('/samples')
@login_required
def user_samples():
    """Liste des échantillons de l'utilisateur"""
    
    return samples(users='current')

def _delete_samples(samples):
    # Vérifier les permissions et le statut
    deleted_count = 0
    errors = []

    for sample in samples:
        # Vérifier que l'utilisateur est le propriétaire ou admin
        if sample.user_id != current_user.id and not current_user.is_admin:
            errors.append(f"{sample.reference} : Accès non autorisé")
            continue
        
        # Vérifier que le statut est "pending"
        if sample.status != 'pending':
            errors.append(f"{sample.reference} : Seuls les échantillons en attente peuvent être supprimés")
            continue

        # Supprimer le fichier de structure si il existe
        if sample.structure_file:
            filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], sample.structure_file)
            if os.path.exists(filepath):
                try:
                    os.remove(filepath)
                except Exception as e:
                    errors.append(f"{sample.reference} : Erreur suppression fichier - {str(e)}")
                    continue

        # Supprimer l'échantillon de la base
        try:
            db.session.delete(sample)
            deleted_count += 1
        except Exception as e:
            db.session.rollback()
            errors.append(f"{sample.reference} : Erreur suppression BD - {str(e)}")
            continue

    db.session.commit()

    if deleted_count > 0:
        flash(f'{deleted_count} échantillon{"s" if deleted_count > 1 else ""} supprimé{"s" if deleted_count > 1 else ""} avec succès', 'success')

    for error in errors:
        flash(error, 'error')

@main_bp.route('/sample/<int:sample_id>/delete', methods=['POST'])
@login_required
def delete_sample(sample_id):
    """Supprimer un échantillon (uniquement si statut = pending)"""

    sample = Sample.query.get_or_404(sample_id)

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
        flash('Aucun échantillon sélectionné', 'error')
        return redirect(url_for('main.user_samples'))

    sample_ids = [int(sid.strip()) for sid in sample_ids.split(',') if sid.strip()]
    if not sample_ids:
        flash('Aucun échantillon valide sélectionné', 'error')
        return redirect(url_for('main.user_samples'))

    # Récupérer les échantillons
    samples = Sample.query.filter(
        Sample.id.in_(sample_ids)
    ).all()

    if not samples:
        flash('Aucun échantillon trouvé', 'error')
        return redirect(url_for('main.user_samples'))

    redirection = _delete_samples(samples)
    if redirection is not None:
        return redirection

    return redirect(url_for('main.user_samples'))

@main_bp.route('/download/<filename>')
@login_required
def download_file(filename):
    """Télécharger un fichier de structure"""
    sample = Sample.query.filter_by(structure_file=filename).first()
    if not sample or (sample.user_id != current_user.id and not current_user.is_admin):
        flash('Accès non autorisé', 'error')
        return redirect(url_for('main.index'))
    return send_from_directory(current_app.config['UPLOAD_FOLDER'], filename, as_attachment=True)
    
@main_bp.route('/sample/<int:sample_id>/pdf')
@login_required
def generate_pdf(sample_id):
    """Générer une fiche d'analyse PDF pour un échantillon"""
    # Récupérer l'échantillon (peut être Sample, MSSample ou NMRSample)
    sample = Sample.query.get_or_404(sample_id)
    
    # Vérifier les permissions
    if sample.user_id != current_user.id and not current_user.is_admin:
        flash('Accès non autorisé', 'error')
        return redirect(url_for('main.index'))
    
    try:
        # Générer le PDF
        pdf_buffer = create_analysis_sheet_pdf(
            sample, current_app.config['UPLOAD_FOLDER'],
            *SERVICES.get(sample.analysis_type, [None, None, None]),
            logo_path=os.path.join(current_app.static_folder, 'images', 'logo_icsn_transparent.png'),
            base_url=request.host_url
        )
        
        # Créer la réponse
        response = make_response(pdf_buffer.getvalue())
        response.headers['Content-Type'] = 'application/pdf'
        response.headers['Content-Disposition'] = f'attachment; filename=fiche_analyse_{sample.reference}.pdf'
        
        return response
    except Exception as e:
        flash(f'Erreur lors de la génération du PDF: {str(e)}', 'error')
        return redirect(request.referrer)