import logging

from flask import current_app, flash

logger = logging.getLogger(__name__)


def log_error(e: Exception, context: str = "") -> None:
    """Journalise l'exception complète (avec traceback) côté serveur uniquement."""
    
    logger.exception("Erreur interne (%s): %r", context or "contexte inconnu", e)


def report_error(e: Exception, user_message: str) -> None:
    """Loggue l'erreur et affiche un message générique à l'utilisateur.

    Le détail de l'exception n'est ajouté au flash qu'en mode debug.
    """
    
    log_error(e, user_message)
    if current_app.debug:
        flash(f"{user_message} — {e}", 'error')
    else:
        flash(user_message, 'error')