// Document Ready
document.addEventListener('DOMContentLoaded', function() {
    initFlashMessages();
    initFormValidation();
    initFileUpload();
});

/**
 * Gestion des messages flash (alertes Bootstrap)
 */
function initFlashMessages() {
    // Fermer les messages flash après 5 secondes
    setTimeout(function() {
        document.querySelectorAll('.alert').forEach(function(alertEl) {
            if (alertEl.animate) {
                alertEl.animate(
                    [{opacity: 1}, {opacity: 0}],
                    {duration: 500, fill: 'forwards'}
                ).onfinish = function() {
                    alertEl.remove();
                };
            } else {
                alertEl.remove();
            }
        });
    }, 5000);
}

/**
 * Validation des formulaires
 */
function initFormValidation() {
    document.querySelectorAll('.login-form').forEach(function(form) {
        form.addEventListener('submit', function(e) {
            const username = document.getElementById('username');
            const password = document.getElementById('password');

            if (username && username.value.trim() === '') {
                e.preventDefault();
                username.classList.add('is-invalid');
            }

            if (password && password.value.trim() === '') {
                e.preventDefault();
                password.classList.add('is-invalid');
            }
        });

        form.addEventListener('input', function(e) {
            if (e.target.matches('input')) {
                e.target.classList.remove('is-invalid');
            }
        });
    });
}

/**
 * Gestion des uploads de fichiers
 */
function initFileUpload() {
    document.querySelectorAll('form').forEach(function(form) {
        form.addEventListener('submit', function(e) {
            const fileInput = form.querySelector('input[type="file"]');
            if (fileInput && fileInput.files.length > 0) {
                const file = fileInput.files[0];
                const maxSize = 16 * 1024 * 1024; // 16 Mo

                if (file.size > maxSize) {
                    e.preventDefault();
                    alert((window.I18N && window.I18N.fileTooLarge) || 'The file is too large. Maximum allowed size is 16 MB.');
                    fileInput.classList.add('is-invalid');
                }
            }
        });
    });
}

/**
 * Remplace onsubmit="return confirm(...)" / onclick inline,
 * bloqués par la CSP (script-src-attr). Lire l'attribut avec getAttribute().
 */
document.addEventListener('submit', function(e) {
    const form = e.target.closest('form[data-confirm]');
    if (form && !window.confirm(form.getAttribute('data-confirm'))) {
        e.preventDefault();
    }
});

document.addEventListener('click', function(e) {
    const el = e.target.closest('[data-confirm-click]');
    if (el && window.confirm(el.getAttribute('data-confirm-click'))) {
        const target = el.getAttribute('data-target');
        if (target) {
            document.getElementById(target).submit();
        }
    }
});

/**
 * fetch + parsing JSON robuste : rejette proprement si la réponse n'est pas
 * du JSON (redirection vers la page de login, erreur 500 en HTML, proxy...),
 * au lieu de planter avec "JSON.parse: unexpected character".
 * Contrat : {ok, status, data}
 */
window.fetchJSON = function(url, options) {
	options = Object.assign({}, options);
    const method = (options.method || 'GET').toUpperCase();
    if (method !== 'GET' && method !== 'HEAD') {
        const meta = document.querySelector('meta[name="csrf-token"]');
        if (meta && meta.content) {
            const headers = Object.assign({}, options.headers);
            const hasToken = Object.keys(headers).some(function(h) {
                return h.toLowerCase() === 'x-csrftoken';
            });
            if (!hasToken) {
                headers['X-CSRFToken'] = meta.content;
            }
            options.headers = headers;
        }
    }
    return fetch(url, options).then(function(resp) {
        const contentType = resp.headers.get('Content-Type') || '';
        if (!contentType.includes('application/json')) {
            const err = new Error('HTTP ' + resp.status + ' : réponse non JSON (' + (contentType || 'Content-Type absent') + ')');
            err.status = resp.status;
            throw err;
        }
        return resp.json().then(function(data) {
            return {ok: resp.ok, status: resp.status, data: data};
        });
    });
};