from urllib.parse import urlparse

from flask import redirect, request, url_for


def safe_redirect_back(fallback: str, **url_kwargs):
    """Redirige vers le Referer uniquement s'il pointe vers cette application
    (même hôte, ou chemin relatif interne), sinon vers l'endpoint de repli.

    Protège contre les open redirects (Referer contrôlé par le client)
    et contre les URL protocol-relative ('//evil.com')."""
    
    ref = request.referrer or ''
    parsed = urlparse(ref)
    if parsed.netloc == request.host:
        return redirect(ref)
    if ref.startswith('/') and not ref.startswith('//'):
        return redirect(ref)
    return redirect(url_for(fallback, **url_kwargs))