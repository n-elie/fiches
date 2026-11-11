import re
from molmass import Formula, FormulaError

REFERENCE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\- ]{0,99}$")

def is_valid_reference(reference):
    return bool(reference) and bool(REFERENCE_RE.fullmatch(reference))
    
# Allow only standard chemical formula characters:
# Letters, numbers, parentheses, brackets, charges (+, -), dots/asterisks for hydrates, and spaces
FORMULA_RE = re.compile(r'[A-Za-z0-9()\[\]+\-.* ]+')

def is_valid_formula(formula_str: str) -> bool:
    # 1. Basic type and length check
    if not isinstance(formula_str, str) or not formula_str.strip() or len(formula_str) > 256:
        return False

    # 2. Security check: Reject any disallowed characters like '<', '>', ';', etc.
    if not FORMULA_RE.fullmatch(formula_str):
        return False

    # 3. Chemical validation: Check if molmass can parse it cleanly
    try:
        Formula(formula_str)
        return True
    except FormulaError:
        return False