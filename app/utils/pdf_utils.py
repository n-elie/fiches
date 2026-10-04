"""
Utilitaire pour générer des fiches d'analyse au format PDF
"""
import os
import tempfile
import io
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm, inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
from reportlab.platypus.flowables import Image
from reportlab.lib.utils import ImageReader
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

from rdkit import Chem as rdChem
from rdkit.Chem import Draw as rdDraw

# Enregistrer les polices si nécessaire
try:
    pdfmetrics.registerFont(TTFont('DejaVuSans', 'DejaVuSans.ttf'))
    pdfmetrics.registerFont(TTFont('DejaVuSans-Bold', 'DejaVuSans-Bold.ttf'))
except:
    pass

def create_analysis_sheet_pdf(sample, upload_folder):
    """
    Créer une fiche d'analyse PDF pour un échantillon
    
    Args:
        sample: Objet Sample, MSSample ou NMRSample
        upload_folder: Dossier où sont stockés les fichiers uploadés
    
    Returns:
        BytesIO: Contenu du PDF
    """
    # Créer un buffer pour le PDF
    buffer = io.BytesIO()
    
    # Configuration du document
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=20*mm,
        leftMargin=20*mm,
        topMargin=20*mm,
        bottomMargin=20*mm,
        title=f"Fiche d'analyse - {sample.reference}"
    )
    
    # Styles
    styles = getSampleStyleSheet()
    
    # Style personnalisé pour les titres
    title_style = ParagraphStyle(
        name='CustomTitle',
        parent=styles['Heading1'],
        fontSize=18,
        leading=22,
        alignment=TA_CENTER,
        spaceAfter=10,
        textColor=colors.HexColor('#2c3e50')
    )
    
    # Style pour les sous-titres
    subtitle_style = ParagraphStyle(
        name='CustomSubtitle',
        parent=styles['Heading2'],
        fontSize=14,
        leading=18,
        spaceBefore=10,
        spaceAfter=8,
        textColor=colors.HexColor('#34495e')
    )
    
    # Style pour les labels
    label_style = ParagraphStyle(
        name='LabelStyle',
        fontSize=10,
        leading=14,
        textColor=colors.HexColor('#7f8c8d'),
        spaceAfter=2
    )
    
    # Style pour les valeurs
    value_style = ParagraphStyle(
        name='ValueStyle',
        fontSize=11,
        leading=16,
        textColor=colors.black,
        spaceAfter=6
    )
    
    # Style pour le tableau
    table_header_style = ParagraphStyle(
        name='TableHeader',
        fontSize=10,
        leading=14,
        textColor=colors.white,
        alignment=TA_CENTER,
        fontName='DejaVuSans-Bold'
    )
    
    table_cell_style = ParagraphStyle(
        name='TableCell',
        fontSize=9,
        leading=12,
        textColor=colors.black,
        alignment=TA_LEFT
    )
    
    # Liste des éléments du PDF
    elements = []
    
    # ===== EN-TÊTE =====
    # Logo ou titre principal
    elements.append(Spacer(1, 5*mm))
    elements.append(Paragraph(f"FICHE D'ANALYSE", title_style))
    
    # Type d'analyse
    analysis_type_text = sample.get_type() if hasattr(sample, 'get_type') else sample.analysis_type.upper()
    elements.append(Paragraph(f"Type: {analysis_type_text}", subtitle_style))
    
    elements.append(Spacer(1, 5*mm))
    
    # ===== INFORMATIONS PRINCIPALES =====
    elements.append(Paragraph("INFORMATIONS PRINCIPALES", subtitle_style))
    elements.append(Spacer(1, 3*mm))
    
    # Tableau pour les informations de base
    data = []
    
    # Champs communs à tous les échantillons
    common_fields = [
        ("Équipe", sample.team or "Non précisé"),
        ("Référence", sample.reference or "N/A"),
        ("Quantité", f"{sample.quantity} mg" if sample.quantity else "N/A"),
        ("Formule", sample.formula or "Non précisée"),
        ("Notes", sample.notes or "Aucune"),
        ("Date de création", sample.created_at.strftime('%d/%m/%Y à %H:%M') if sample.created_at else "N/A"),
    ]
    
    for label, value in common_fields:
        data.append([
            Paragraph(label, label_style),
            Paragraph(str(value), value_style)
        ])
    
    # Créer le tableau
    table = Table(data, colWidths=[80*mm, 100*mm])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#ecf0f1')),
        ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#bdc3c7')),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('ALIGN', (0, 0), (0, -1), 'RIGHT'),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
    ]))
    
    elements.append(table)
    elements.append(Spacer(1, 8*mm))
    
    # ===== CHAMPS SPÉCIFIQUES PAR TYPE =====
    
    # Pour les échantillons RMN
    if hasattr(sample, 'solvent') and sample.analysis_type == 'nmr':
        elements.append(Paragraph("INFORMATIONS RMN", subtitle_style))
        elements.append(Spacer(1, 3*mm))
        
        nmr_data = []
        
        # Stabilité
        stability_map = {0: "Inconnue", 1: "Stable", 2: "Instable", 3: "Très stable"}
        stability_text = stability_map.get(sample.stability, "Non précisée")
        nmr_data.append([Paragraph("Stabilité", label_style), Paragraph(stability_text, value_style)])
        
        # Solvant
        nmr_data.append([Paragraph("Solvant", label_style), Paragraph(sample.solvent or "Non précisé", value_style)])
        
        # Fréquence
        nmr_data.append([Paragraph("Fréquence", label_style), Paragraph(f"{sample.frequency} MHz", value_style)])
        
        # Expériences
        experiments = sample.experiments or ""
        other_experiment = sample.other_experiment or ""
        all_experiments = []
        if experiments:
            all_experiments.extend(experiments.split(', '))
        if other_experiment:
            all_experiments.append(other_experiment)
        experiments_text = ", ".join(all_experiments) if all_experiments else "Aucune"
        nmr_data.append([Paragraph("Expériences", label_style), Paragraph(experiments_text, value_style)])
        
        nmr_table = Table(nmr_data, colWidths=[80*mm, 100*mm])
        nmr_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#ecf0f1')),
            ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#bdc3c7')),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('ALIGN', (0, 0), (0, -1), 'RIGHT'),
            ('LEFTPADDING', (0, 0), (-1, -1), 6),
            ('RIGHTPADDING', (0, 0), (-1, -1), 6),
            ('TOPPADDING', (0, 0), (-1, -1), 3),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ]))
        elements.append(nmr_table)
        elements.append(Spacer(1, 8*mm))
    
    # Pour les échantillons MS
    elif hasattr(sample, 'solvents') and sample.analysis_type == 'ms':
        elements.append(Paragraph("INFORMATIONS MS", subtitle_style))
        elements.append(Spacer(1, 3*mm))
        
        ms_data = []
        
        # Solvants
        solvents = sample.solvents or ""
        other_solvent = sample.other_solvent or ""
        all_solvents = []
        if solvents:
            all_solvents.extend(solvents.split(', '))
        if other_solvent:
            all_solvents.append(other_solvent)
        solvents_text = ", ".join(all_solvents) if all_solvents else "Aucun"
        ms_data.append([Paragraph("Solvants", label_style), Paragraph(solvents_text, value_style)])
        
        ms_table = Table(ms_data, colWidths=[80*mm, 100*mm])
        ms_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#ecf0f1')),
            ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#bdc3c7')),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('ALIGN', (0, 0), (0, -1), 'RIGHT'),
            ('LEFTPADDING', (0, 0), (-1, -1), 6),
            ('RIGHTPADDING', (0, 0), (-1, -1), 6),
            ('TOPPADDING', (0, 0), (-1, -1), 3),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ]))
        elements.append(ms_table)
        elements.append(Spacer(1, 8*mm))
    
    # ===== STRUCTURE CHIMIQUE =====
    if sample.structure_file:
        elements.append(Paragraph("STRUCTURE CHIMIQUE", subtitle_style))
        elements.append(Spacer(1, 3*mm))
        
        # Chemin complet du fichier
        file_path = os.path.join(upload_folder, sample.structure_file)
        
        # Générer l'image de la structure
        mol = rdChem.MolFromSmiles(sample.smiles)
        
        if mol:
            img = rdDraw.MolToImage(mol, size=(200, 200))
            buf = io.BytesIO()
            img.save(buf, format='PNG')
            buf.seek(0)
            elements.append(Image(buf))
            elements.append(Spacer(1, 5*mm))
        else:
            print(f"Erreur lors de l'ajout de la structure.")
            elements.append(Paragraph("Structure: Impossible de charger la structure", value_style))
        
        elements.append(Spacer(1, 8*mm))
    
    # ===== PIED DE PAGE =====
    elements.append(Spacer(1, 5*mm))
    elements.append(Paragraph("Généré le " + datetime.now().strftime('%d/%m/%Y à %H:%M'), 
                             ParagraphStyle(name='Footer', fontSize=8, textColor=colors.grey)))
    
    # Construire le PDF
    doc.build(elements)
    
    # Remonter au début du buffer
    buffer.seek(0)
    
    return buffer