from flask import Blueprint, render_template, request, redirect, url_for, flash, send_file
from flask_login import login_required, current_user
import csv
import io
from datetime import datetime
from sqlalchemy import desc
from collections.abc import Callable
    
import pandas as pd

from ..models import db, Sample, User

admin_bp = Blueprint('admin', __name__)

@admin_bp.before_request
def require_admin():
    if not current_user.is_authenticated or not current_user.is_admin:
        flash('Accès réservé aux administrateurs.', 'danger')
        return redirect(url_for('main.index'))

@admin_bp.route('/dashboard')
@login_required
def dashboard():
    """Tableau de bord administrateur"""

    total_samples = Sample.query.count()
    total_users = User.query.count()
    pending_samples = Sample.query.filter_by(status='pending').count()
    completed_samples = Sample.query.filter_by(status='completed').count()
    recent_samples = Sample.query.order_by(desc(Sample.created_at)).limit(10).all()
    users = User.query.order_by(User.username).all()

    return render_template('admin/dashboard.html',
                         total_samples=total_samples,
                         total_users=total_users,
                         pending_samples=pending_samples,
                         completed_samples=completed_samples,
                         recent_samples=recent_samples,
                         users=users,
                         user=current_user)

@admin_bp.route('/samples')
@login_required
def all_samples():
    """Liste de tous les échantillons"""
    
    from ..routes.main_routes import samples
    return samples(template='admin/samples.html', users='all')

@admin_bp.route('/users')
@login_required
def all_users():
    """Liste de tous les utilisateurs"""

    users = User.query.order_by(User.username).all()
    return render_template('admin/users.html', users=users, user=current_user)
    
def _export_data(samples:list[Sample], callback:Callable[Sample | None], data_format:str='csv'):
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

    samples = Sample.query.join(User).all()
    
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
    samples = Sample.query.join(User).all()

    def callback(sample: Sample | None) -> dict:
        return {
            'ID': sample.id,
            'Utilisateur': sample.user.full_name,
            'Email': sample.user.email,
            'Équipe': sample.team,
            'Référence': sample.reference,
            'Quantité (mg)': sample.quantity,
            'Fichier de structure': sample.structure_file,
            'Statut': sample.status,
            'Date': sample.created_at.strftime('%Y-%m-%d %H:%M:%S')
        }

    output = _export_data(samples, callback, 'excel')

    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=f'samples_export_{datetime.now().strftime("%Y%m%d_%H%M%S")}.xlsx'
    )
    
@admin_bp.route('/samples/export-sample-list', methods=['POST'])
@login_required
def export_sample_list():
    """Créer une sample list à partir des échantillons sélectionnés (admin only)"""

    sample_ids = request.form.get('sample_ids', '')
    if not sample_ids:
        flash('Aucun échantillon sélectionné', 'error')
        return redirect(url_for('admin.all_samples'))

    try:
        sample_ids = [int(sid.strip()) for sid in sample_ids.split(',') if sid.strip()]
    except ValueError:
        flash('ID d\'échantillon invalide', 'error')
        return redirect(url_for('admin.all_samples'))

    if not sample_ids:
        flash('Aucun échantillon valide sélectionné', 'error')
        return redirect(url_for('admin.all_samples'))

    # Récupérer les échantillons sélectionnés avec leurs utilisateurs
    samples = Sample.query.filter(Sample.id.in_(sample_ids)).join(User).all()

    if not samples:
        flash('Aucun échantillon trouvé', 'error')
        return redirect(url_for('admin.all_samples'))

    def callback(sample: Sample | None) -> list:
        if sample is None:
            return
        return [sample.reference, sample.uuid]
                
    output = _export_data(samples, callback, 'csv')

    return send_file(
        output,
        mimetype='text/csv',
        as_attachment=True,
        download_name=f'sample_list_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
    )

@admin_bp.route('/sample/<int:sample_id>/update', methods=['POST'])
@login_required
def update_sample_status(sample_id):
    """Mettre à jour le statut d'un échantillon"""

    sample = Sample.query.get_or_404(sample_id)
    new_status = request.form.get('status')

    if new_status in ['pending', 'processing', 'completed', 'cancelled']:
        sample.status = new_status
        db.session.commit()
        flash('Statut mis à jour avec succès', 'success')
    else:
        flash('Statut invalide', 'error')

    return redirect(url_for('admin.admin_sample_detail', sample_id=sample_id))