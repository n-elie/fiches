"""
Utilitaire pour générer des fiches d'analyse au format PDF avec WeasyPrint.

Le rendu passe par un template HTML (app/templates/pdf/analysis_sheet.html) :
une page A4 paysage par échantillon, avec deux copies A5 côte à côte
(« Analysis sheet » à gauche, « Sheet to keep » à droite).
Les images (logo, QR codes, structure chimique) sont intégrées en data URI
base64, donc aucun accès disque externe n'est nécessaire côté WeasyPrint.
"""

import base64
import io
import os
from datetime import datetime
from urllib.parse import urljoin

from flask import render_template
from flask_babel import gettext as _, format_datetime
from weasyprint import HTML

from .mol import html_formula, mol_to_img, mol_from_smiles

try:
    import qrcode
    QRCODE_AVAILABLE = True
except ImportError:
    QRCODE_AVAILABLE = False


def _image_to_data_uri(buffer: io.BytesIO) -> str:
    """Encode un buffer image PNG en data URI base64 (intégrable dans le HTML)."""
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def generate_qr_code(url: str, size: int = 200):
    """
    Génère un QR code comme image PNG dans un BytesIO
    """
    if not QRCODE_AVAILABLE:
        return None

    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
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


def generate_qr_code_data_uri(url: str, size: int = 200):
    """QR code directement utilisable comme src d'une <img> dans le template."""
    buffer = generate_qr_code(url, size)
    return _image_to_data_uri(buffer) if buffer else None


def molecule_image_data_uri(smiles):
    """Dessine la structure à partir du SMILES et renvoie une data URI PNG (ou None)."""
    if not smiles:
        return None
    mol = mol_from_smiles(smiles)
    if mol is None:
        return None
    return _image_to_data_uri(mol_to_img(mol))


def logo_data_uri(logo_path):
    """Encode le logo en data URI (évite à WeasyPrint de résoudre un chemin externe)."""
    if not logo_path or not os.path.exists(logo_path):
        return None
    mime = "image/svg+xml" if logo_path.lower().endswith(".svg") else "image/png"
    with open(logo_path, "rb") as f:
        encoded = base64.b64encode(f.read()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def build_sheet_context(sample, services=None, base_url=None) -> dict:
    """
    Prépare les données d'une fiche : champs communs, traductions, QR code,
    structure chimique et bloc spécifique au type d'analyse (MS / NMR).
    """
    service_infos = (services or {}).get(sample.analysis_type, {})

    context = {
        "sample": sample,
        "service_name": service_infos.get("name"),
        "phone": service_infos.get("phone"),
        "responsible": service_infos.get("responsible"),
        "team": sample.team or _("Not specified"),
        "reference": sample.reference or "N/A",
        "quantity": f"{sample.quantity} mg" if sample.quantity else "N/A",
        "notes": sample.notes or _("None"),
        "created_at": format_datetime(sample.created_at) if sample.created_at else "N/A",
        "formula_html": html_formula(sample.formula),
        "qr_data_uri": None,
        "has_structure": bool(sample.structure_file),
        "structure_data_uri": None,
        "nmr": None,
        "ms": None,
        "mass_label": None,
        "mass_text": None,
    }

    if base_url:
        sample_url = urljoin(base_url, f"{sample.analysis_type}/sample/{sample.id}")
        context["qr_data_uri"] = generate_qr_code_data_uri(sample_url)

    if sample.structure_file and sample.smiles:
        context["structure_data_uri"] = molecule_image_data_uri(sample.smiles)

    if sample.analysis_type == "nmr":
        stability_map = {0: _("Unknown"), 1: _("Stable"), 2: _("Unstable"), 3: _("Very stable")}
        experiments = sample.experiments.split(", ") if sample.experiments else []
        if sample.other_experiment:
            experiments.append(sample.other_experiment)
        context["nmr"] = {
            "stability": stability_map.get(sample.stability, _("Not specified")),
            "solvent": sample.solvent or _("Not specified"),
            "frequency": f"{sample.frequency} MHz" if sample.frequency else "N/A",
            "experiments": ", ".join(experiments) if experiments else _("None"),
        }
        context["mass_label"] = _("Mass")
        context["mass_text"] = str(round(sample.mass)) if sample.mass else "N/A"
    elif sample.analysis_type == "ms":
        solvents = sample.solvents.split(", ") if sample.solvents else []
        if sample.other_solvent:
            solvents.append(sample.other_solvent)
        context["ms"] = {
            "solvents": ", ".join(solvents) if solvents else _("None"),
        }
        context["mass_label"] = _("Exact mass")
        context["mass_text"] = f"{sample.mass:.4f} Da" if sample.mass else "N/A"

    return context


def create_analysis_sheet_pdf(samples: list, upload_folder: str, services=None, logo_path=None, base_url=None) -> io.BytesIO:
    """
    Crée un PDF de fiches d'analyse avec WeasyPrint : une page A4 paysage par
    échantillon, contenant deux copies A5 côte à côte (fiche + « Sheet to keep »),
    chacune avec son QR code.

    Args:
        samples: Liste d'objets Sample, MSSample ou NMRSample
        upload_folder: conservé pour compatibilité de signature (les structures
            sont rendues depuis le SMILES, pas depuis le fichier uploadé)
        services: dict app.config['SERVICES'] (résout nom/responsable/téléphone par type)
        logo_path: chemin du logo (encodé en data URI dans le HTML)
        base_url: URL de base de l'application (ex: "http://localhost:5000/") pour les QR codes

    Returns:
        BytesIO: Contenu du PDF
    """
    sheets = [build_sheet_context(s, services=services, base_url=base_url) for s in samples]

    title = _("Analysis sheet - %(ref)s", ref=samples[0].reference) if len(samples) == 1 else _("Analysis sheets")

    html = render_template(
        "pdf/analysis_sheet.html",
        title=title,
        sheets=sheets,
        logo_data_uri=logo_data_uri(logo_path),
        generated_on=format_datetime(datetime.now()),
    )

    pdf_bytes = HTML(string=html, base_url=base_url or "").write_pdf()
    return io.BytesIO(pdf_bytes)