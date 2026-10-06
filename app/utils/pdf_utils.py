""""
Utilitaire pour generer des fiches d'analyse au format PDF
"""
import os
import tempfile
import io
from datetime import datetime
from urllib.parse import urljoin

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, A5, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm, inch
from reportlab.platypus import (BaseDocTemplate, Paragraph, Spacer,
                                Table, TableStyle, PageBreak,
                                Frame, PageTemplate, FrameBreak,
                                HRFlowable)
from reportlab.platypus.flowables import Image
from reportlab.lib.utils import ImageReader
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

from .mol import html_formula, mol_to_img, mol_from_smiles

# Enregistrer les polices si nécessaire
try:
    pdfmetrics.registerFont(TTFont('DejaVuSans', 'DejaVuSans.ttf'))
    pdfmetrics.registerFont(TTFont('DejaVuSans-Bold', 'DejaVuSans-Bold.ttf'))
except:
    pass
    
# QR Code
try:
    import qrcode
    QRCODE_AVAILABLE = True
except ImportError:
    QRCODE_AVAILABLE = False

class TwoA5DocTemplate(BaseDocTemplate):
    def __init__(self, filename, frames, qr_image=None, **kwargs):
        BaseDocTemplate.__init__(self, filename, **kwargs)
        self.qr_image = qr_image
        self.addPageTemplates([
            PageTemplate(id='TwoA5', frames=frames, onPage=self.draw_page)
        ])

    def draw_page(self, canvas, doc):
        # 1. Ligne verticale entre les deux frames
        x_position = 2.5*mm + 148*mm
        canvas.setStrokeColor(colors.HexColor('#bdc3c7'))
        canvas.setLineWidth(0.5)
        canvas.line(x_position, 5*mm, x_position, 205*mm)
        
        # 2. Dessiner le QR code dans chaque frame (bas à droite)
        if self.qr_image:
            qr_size = 25*mm
            qr_y = 5*mm + 20*mm  # 20mm au-dessus du bas

            # Frame de gauche
            qr_x_left = 5*mm + 143*mm - qr_size - 3*mm
            canvas.drawImage(
                self.qr_image,
                qr_x_left, qr_y,
                width=qr_size,
                height=qr_size,
                mask='auto'
            )

            # Frame de droite
            qr_x_right = 5*mm + 148*mm + 143*mm - qr_size - 3*mm
            canvas.drawImage(
                self.qr_image,
                qr_x_right, qr_y,
                width=qr_size,
                height=qr_size,
                mask='auto'
            )

def generate_qr_code(url: str, size: int = 100) -> io.BytesIO:
    """
    Génère un QR code comme image PNG dans un BytesIO
    """
    if not QRCODE_AVAILABLE:
        return None

    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=2,
    )
    qr.add_data(url)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")
    img = img.resize((size, size), resample=0)

    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer

def create_analysis_sheet_pdf(sample, upload_folder, service_name=None, responsible_name=None, phone_number=None, logo_path=None, base_url=None):
    """
    Créer une fiche d'analyse PDF pour un echantillon avec deux copies A5 sur une page A4 landscape

    Args:
        sample: Objet Sample, MSSample ou NMRSample
        upload_folder: Dossier ou sont stockes les fichiers uploades
        service_name: Nom du service d'analyse (optionnel)
        responsible_name: Nom du responsable (optionnel)
        phone_number: Numero de telephone du responsable (optionnel)
        base_url: URL de base de l'application (ex: "http://localhost:5000")

    Returns:
        BytesIO: Contenu du PDF
    """

    # Créer un buffer pour le PDF
    buffer = io.BytesIO()

    # Styles
    styles = getSampleStyleSheet()

    # Style personnalise pour les titres
    title_style = ParagraphStyle(
        name='CustomTitle',
        parent=styles['Heading1'],
        fontSize=14,
        leading=16,
        alignment=TA_CENTER,
        spaceAfter=2,
        textColor=colors.HexColor('#2c3e50')
    )

    # Style pour les sous-titres
    subtitle_style = ParagraphStyle(
        name='CustomSubtitle',
        parent=styles['Heading2'],
        fontSize=9,
        leading=12,
        spaceBefore=2,
        spaceAfter=2,
        textColor=colors.HexColor('#34495e')
    )

    # Style pour les labels
    label_style = ParagraphStyle(
        name='LabelStyle',
        fontSize=7,
        leading=9,
        textColor=colors.HexColor('#7f8c8d'),
        spaceAfter=0.5
    )

    # Style pour les valeurs
    value_style = ParagraphStyle(
        name='ValueStyle',
        fontSize=8,
        leading=12,
        textColor=colors.black,
        spaceAfter=1.5
    )
    
    # Style pour le pied de page
    footer_style = ParagraphStyle(
        name='FooterStyle',
        fontSize=8,
        textColor=colors.grey)
    
    # Style pour URL
    url_style = ParagraphStyle(
        name = 'URLStyle',
        fontSize=6,
        textColor=colors.grey,
        alignment=TA_CENTER,
        leading=8,
        spaceAfter=4
    )
    
    # Style pour les tableaux
    table_style = TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#ecf0f1')),
        ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#bdc3c7')),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('ALIGN', (0, 0), (0, -1), 'RIGHT'),
        ('LEFTPADDING', (0, 0), (-1, -1), 2),
        ('RIGHTPADDING', (0, 0), (-1, -1), 2),
        ('TOPPADDING', (0, 0), (-1, -1), 1),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 1),
    ])
    
    hr = HRFlowable(
        width="100%",
        thickness=1,
        color=colors.black,
        spaceBefore=5,
        spaceAfter=5,
    )

    def create_sheet_content():
        """Cree le contenu d'une fiche individuelle"""
        elements = []

        if logo_path and os.path.exists(logo_path):
            try:
                img = ImageReader(logo_path)
                iw, ih = img.getSize()
                aspect = ih / float(iw)
                width = 15*mm
                img = Image(logo_path, width=width, height=(width*aspect))
                img.hAlign = 'CENTER'
                elements.append(img)
                elements.append(Spacer(1, 2*mm))
            except:
                pass

        # Titre avec informations du service
        elements.append(Paragraph(service_name, title_style))
        elements.append(Spacer(1, 1*mm))

        elements.append(Paragraph(f"Poste: {phone_number} - {responsible_name}", title_style))
        elements.append(hr)
        
        elements.append("{{placeholder}}")  # {{placeholder}} sera remplacé par le sous-titre de la fiche
        elements.append(hr)

        # INFORMATIONS PRINCIPALES
        elements.append(Paragraph("INFORMATIONS PRINCIPALES", subtitle_style))
        elements.append(Spacer(1, 0.5*mm))

        # Tableau pour les informations de base
        data = []

        # Champs communs a tous les echantillons
        common_fields = [
            ("Équipe", sample.team or "Non précisé"),
            ("Référence", sample.reference or "N/A"),
            ("Quantité", f"{sample.quantity} mg" if sample.quantity else "N/A"),
            ("Notes", sample.notes or "Aucune"),
            ("Date de creation", sample.created_at.strftime('%d/%m/%Y a %H:%M') if sample.created_at else "N/A"),
        ]

        for label, value in common_fields:
            data.append([
                Paragraph(label, label_style),
                Paragraph(str(value), value_style)
            ])

        # Créer le tableau
        table = Table(data, colWidths=[40*mm, 55*mm])
        table.setStyle(table_style)

        elements.append(table)
        elements.append(Spacer(1, 2*mm))
        
        # INFORMATIONS STRUCTURALES
        elements.append(Paragraph("INFORMATIONS STRUCTURALES", subtitle_style))
        elements.append(Spacer(1, 0.5*mm))

        # Tableau pour les informations de base
        data = []

        # Champs communs a tous les echantillons
        structural_fields = [
            ("SMILES", sample.smiles or "Non précisé"),
            ("Formule", html_formula(sample.formula) or "Non précisée"),
        ]
        match sample.analysis_type:
            case 'nmr':
                structural_fields.append(
                    ("Masse", f"{round(sample.mass)}" if sample.mass else "N/A"),
                )
            case 'ms':
                structural_fields.append(
                    ("Masse Exacte", f"{sample.mass:.4f} Da" if sample.mass else "N/A"),
                )

        for label, value in structural_fields:
            data.append([
                Paragraph(label, label_style),
                Paragraph(str(value), value_style)
            ])

        # Créer le tableau
        table = Table(data, colWidths=[40*mm, 55*mm])
        table.setStyle(table_style)

        elements.append(table)
        elements.append(Spacer(1, 2*mm))

        # CHAMPS SPECIFIQUES PAR TYPE

        # Pour les echantillons RMN
        if hasattr(sample, 'solvent') and sample.analysis_type == 'nmr':
            elements.append(Paragraph("INFORMATIONS RMN", subtitle_style))
            elements.append(Spacer(1, 0.5*mm))

            nmr_data = []

            # Stabilite
            stability_map = {0: "Inconnue", 1: "Stable", 2: "Instable", 3: "Tres stable"}
            stability_text = stability_map.get(sample.stability, "Non précisée")
            nmr_data.append([Paragraph("Stabilite", label_style), Paragraph(stability_text, value_style)])

            # Solvant
            nmr_data.append([Paragraph("Solvant", label_style), Paragraph(sample.solvent or "Non précisé", value_style)])

            # Frequence
            nmr_data.append([Paragraph("Frequence", label_style), Paragraph(f"{sample.frequency} MHz", value_style)])

            # Experiences
            experiments = sample.experiments or ""
            other_experiment = sample.other_experiment or ""
            all_experiments = []
            if experiments:
                all_experiments.extend(experiments.split(', '))
            if other_experiment:
                all_experiments.append(other_experiment)
            experiments_text = ", ".join(all_experiments) if all_experiments else "Aucune"
            nmr_data.append([Paragraph("Experiences", label_style), Paragraph(experiments_text, value_style)])

            nmr_table = Table(nmr_data, colWidths=[40*mm, 55*mm])
            nmr_table.setStyle(table_style)
            elements.append(nmr_table)
            elements.append(Spacer(1, 2*mm))

        # Pour les echantillons MS
        elif hasattr(sample, 'solvents') and sample.analysis_type == 'ms':
            elements.append(Paragraph("INFORMATIONS MS", subtitle_style))
            elements.append(Spacer(1, 0.5*mm))

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

            ms_table = Table(ms_data, colWidths=[40*mm, 55*mm])
            ms_table.setStyle(table_style)
            elements.append(ms_table)
            elements.append(Spacer(1, 2*mm))

        # STRUCTURE CHIMIQUE
        if sample.structure_file:
            elements.append(Paragraph("STRUCTURE CHIMIQUE", subtitle_style))

            # Chemin complet du fichier
            file_path = os.path.join(upload_folder, sample.structure_file)

            # Generer l'image de la structure
            mol = mol_from_smiles(sample.smiles)

            if mol:
                elements.append(Image(mol_to_img(mol), width=50*mm, height=50*mm))
                elements.append(Spacer(1, 1*mm))
            else:
                print(f"Erreur lors de l'ajout de la structure.")
                elements.append(Paragraph("Structure: Impossible de charger la structure", value_style))

            elements.append(Spacer(1, 1*mm))

        # Pied de page
        elements.append(Spacer(1, 0.5*mm))
        elements.append(Paragraph("Généré le " + datetime.now().strftime('%d/%m/%Y a %H:%M'), footer_style))

        return elements

    # Créer le contenu pour une seule fiche
    sheet_content = create_sheet_content()

    # Créer deux Frames pour les deux copies A5
    # A5: 148mm x 210mm
    # A4 landscape: 297mm x 210mm

    # Frame gauche (premiere copie A5)
    frame_left = Frame(
        x1=5*mm,
        y1=5*mm,
        width=143*mm,
        height=200*mm,
        leftPadding=20*mm,
        bottomPadding=0,
        rightPadding=10*mm,
        topPadding=20*mm,
        id='left'
    )

    # Frame droite (deuxieme copie A5)
    frame_right = Frame(
        x1=frame_left.x1 + 148*mm,  # Position apres la premiere A5
        y1=frame_left.y1,
        width=frame_left.width,
        height=frame_left.height,
        leftPadding=frame_left.rightPadding,
        bottomPadding=frame_left.bottomPadding,
        rightPadding=frame_left.leftPadding,
        topPadding=frame_left.topPadding,
        id='right'
    )

    # Générer le QR code (si base_url est fourni)
    qr_image = None
    if QRCODE_AVAILABLE and base_url:
        sample_url = urljoin(base_url, f"{sample.analysis_type}/sample/{sample.id}")
        qr_image = ImageReader(generate_qr_code(sample_url, size=200))

    # Configuration du document en A4 landscape
    doc = TwoA5DocTemplate(
        buffer,
        pagesize=landscape(A4),
        rightMargin=0,
        leftMargin=0,
        topMargin=0,
        bottomMargin=0,
        title=f"Fiche de depot - {sample.reference}",
        frames=[frame_left, frame_right],
        qr_image=qr_image
    )

    # Créer un PageTemplate avec les deux frames
    page_template = PageTemplate(id='TwoA5', frames=[frame_left, frame_right])
    doc.addPageTemplates([page_template])

    # Construire le PDF avec FrameBreak
    # Chaque frame va recevoir son propre contenu
    all_elements = []
    left_sheet_content = [element if element != "{{placeholder}}" else Paragraph("Fiche de dépôt", title_style) for element in sheet_content]
    all_elements.extend(left_sheet_content)
    all_elements.append(FrameBreak())
    right_sheet_content = [element if element != "{{placeholder}}" else Paragraph("Fiche à conserver", title_style) for element in sheet_content]
    all_elements.extend(right_sheet_content)

    doc.build(all_elements)

    # Remonter au debut du buffer
    buffer.seek(0)

    return buffer