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
