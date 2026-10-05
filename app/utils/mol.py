from rdkit import Chem as rdChem
from rdkit.Chem import Draw as rdDraw
from rdkit.Chem.rdMolDescriptors import CalcMolFormula

import molmass

import os
import io

def read_mol(structure_file_path) -> rdChem.Mol:
    """
    Convertir un fichier de structure chimique en object RDKit.Chem.Mol
    Supporte les formats: .cdx, .cdxml, .mol, .sdf
    
    Args:
        structure_file_path: Chemin vers le fichier de structure
    
    Returns:
        RDKit.Chem.Mol object
    """

    if not structure_file_path or not os.path.exists(structure_file_path):
        return None
    
    _, ext = os.path.splitext(structure_file_path)
    
    mol = None
    match ext:
        case '.cdx' | '.cdxml':
            mols = rdChem.MolsFromCDXMLFile(structure_file_path)
            if not mols:
                raise RuntimeError(f'No structure found in {structure_file_path}')
            mol = mols[0]
        case '.sdf':
            mol_supplier = rdChem.SDMolSupplier(structure_file_path)
            try:
                return next(mol_supplier)
            except StopIteration:
                raise RuntimeError(f'No structure found in {structure_file_path}')
        case '.mol':
            mol = rdChem.MolFromMolFile(structure_file_path)
        case _:
            raise RuntimeError(f'Unknown file format for {structure_file_path}')
    
    if mol is None:
        raise RuntimeError(f'No structure found in {structure_file_path}')
        
    return mol

def mol_from_smiles(smiles: str) -> rdChem.Mol:
    """
    Créer un fichier MOL à partir de la représentation SMILES d'une moléculde
    
    Args:
        mol: Chem.Mol object
    
    Returns:
        SMILES de la molécule
    """
    
    return rdChem.MolFromSmiles(smiles)

def mol_to_smiles(mol: rdChem.Mol) -> str:
    """
    Extraire la représentation SMILES d'un fichier MOL
    
    Args:
        mol: Chem.Mol object
    
    Returns:
        SMILES de la molécule
    """

    return rdChem.MolToSmiles(mol)

def mol_to_formula(mol: rdChem.Mol) -> str:
    """
    Calculer la formule brute d'un fichier MOL
    
    Args:
        mol: Chem.Mol object
    
    Returns:
        Formula brute de la molécule
    """
    
    return CalcMolFormula(mol)
    
def mol_to_img(mol: rdChem.Mol, size=(400, 400)) -> io.BytesIO:
    """
    Dessiner la structure de la molécule
    
    Args:
        mol: Chem.Mol object
        size: taille de l'image en sortie
    
    Returns:
        io.BytesIO contenant l'image
        
    """
    
    img = rdDraw.MolToImage(mol, size=(400, 400))
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return buf
 
def formula_to_mass(formula: str) -> float:
    """
    Calculer la masse exacte à partir d'une formule brute
    
    Args:
        formula: Chaine de caractère représentant une formule brute
    
    Returns:
        masse exacte de la molécule (float)
    """
    
    return molmass.Formula(formula).monoisotopic_mass

# From https://github.com/molshape/ChemFormula
# LICENSE: MIT
def text_charge(charge) -> str:
    """Returns the charge of the formula object as a text string, without the number "1" for charges of ±1."""
    # a charge of "1+" or "1-" is printed without the number "1"
    charge_output = ""
    if charge == 0:
        return charge_output
    if not(abs(charge) == 1):
        charge_output = str(abs(charge))
    charge_output += "+" if charge > 0 else "-"
    return charge_output

def html_formula(formula: str):
    """Returns an HTML representation of the chemical formula (including charge information) as a string."""
    html_formula = formula     # start with original formula
    html_charge = text_charge(molmass.Formula(formula).charge)  # start with original text_charge
    # replace all numbers (0 - 9) by subscript numbers (for elemental frequencies)
    # and superscript numbers (for charge information)
    for number in range(0, 10):
        html_formula = html_formula.replace(str(number), f"<sub>{number}</sub>")
        html_charge = html_charge.replace(str(number), f"<sup>{number}</sup>")
    html_charge = html_charge.replace("+", "<sup>+</sup>")
    html_charge = html_charge.replace("-", "<sup>-</sup>")
    return html_formula + html_charge
