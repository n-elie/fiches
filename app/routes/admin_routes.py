from flask import Blueprint, render_template, request, redirect, url_for, flash, send_file
from flask_login import login_required, current_user
import csv
import io
from datetime import datetime
from sqlalchemy import desc

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

    status_filter = request.args.get('status', '')
    user_filter = request.args.get('user', '')
    type_filter = request.args.get('type', '')
    search_filter = request.args.get('search', '')

    query = Sample.query

    if status_filter:
        query = query.filter_by(status=status_filter)
    if type_filter:
        query = query.filter_by(analysis_type=type_filter)
    if user_filter:
        query = query.filter_by(user_id=user_filter)
    if search_filter:
        query = query.filter(
            Sample.reference.ilike(f'%{search_filter}%')
        )

    sort_by = request.args.get('sort', 'created_at')
    sort_order = request.args.get('order', 'desc')

    if sort_order == 'desc':
        query = query.order_by(desc(getattr(Sample, sort_by)))
    else:
        query = query.order_by(getattr(Sample, sort_by))

    samples = query.all()
    users = User.query.order_by(User.username).all()

    return render_template('admin/samples.html',
                         samples=samples,
                         users=users,
                         user=current_user,
                         status_filter=status_filter,
                         user_filter=user_filter,
                         type_filter=type_filter,
                         search_filter=search_filter,
                         sort_by=sort_by,
                         sort_order=sort_order)

@admin_bp.route('/users')
@login_required
def all_users():
    """Liste de tous les utilisateurs"""

    users = User.query.order_by(User.username).all()
    return render_template('admin/users.html', users=users, user=current_user)

@admin_bp.route('/export/csv')
@login_required
def export_csv():
    """Exporter les données en CSV"""

    samples = Sample.query.join(User).all()
    output = io.StringIO()
    writer = csv.writer(output, delimiter=';')

    writer.writerow([
        'ID', 'Date de création', 'Utilisateur', 'Équipe', 'Email',
        'Référence échantillon', 'Quantité (mg)', 'Unité',
        'Fichier structure', 'Statut', 'Notes'
    ])

    for sample in samples:
        writer.writerow([
            sample.id,
            sample.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            sample.user.full_name,
            sample.team,
            sample.user.email,
            sample.reference,
            sample.quantity,
            sample.structure_file,
            sample.status,
            sample.notes or ''
        ])

    output.seek(0)

    return send_file(
        io.BytesIO(output.getvalue().encode('utf-8-sig')),
        mimetype='text/csv',
        as_attachment=True,
        download_name=f'samples_export_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
    )


@admin_bp.route('/export/excel')
@login_required
def export_excel():
    """Exporter les données au format Excel"""
    
    import pandas as pd

    data = []
    samples = Sample.query.join(User).all()

    for sample in samples:
        data.append({
            'ID': sample.id,
            'Utilisateur': sample.user.full_name,
            'Email': sample.user.email,
            'Équipe': sample.team,
            'Référence': sample.reference,
            'Quantité (mg)': sample.quantity,
            'Fichier de structure': sample.structure_file,
            'Statut': sample.status,
            'Date': sample.created_at.strftime('%Y-%m-%d %H:%M:%S')
        })

    df = pd.DataFrame(data)
    output = io.BytesIO()
    df.to_excel(output, index=False, engine='openpyxl')
    output.seek(0)

    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=f'samples_export_{datetime.now().strftime("%Y%m%d_%H%M%S")}.xlsx'
    )

@admin_bp.route('/sample/<uuid:sample_id>/update', methods=['POST'])
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