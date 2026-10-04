from rdkit import Chem as rdChem
from rdkit.Chem.rdMolDescriptors import CalcMolFormula

import molmass

import os

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
    
def formula_to_mass(formula: str) -> float:
    """
    Calculer la masse exacte à partir d'une formule brute
    
    Args:
        formula: Chaine de caractère représentant une formule brute
    
    Returns:
        masse exacte de la molécule (float)
    """
    
    return molmass.Formula(formula).monoisotopic_mass
