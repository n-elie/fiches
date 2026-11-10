// Document Ready
$(document).ready(function() {
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
        $('.alert').fadeOut(500, function() {
            $(this).remove();
        });
    }, 5000);
}

/**
 * Validation des formulaires
 */
function initFormValidation() {
    $('.login-form').each(function() {
        const $form = $(this);

        $form.on('submit', function(e) {
            const $username = $('#username');
            const $password = $('#password');

            if ($username.val().trim() === '') {
                e.preventDefault();
                $username.addClass('is-invalid');
            }

            if ($password.val().trim() === '') {
                e.preventDefault();
                $password.addClass('is-invalid');
            }
        });

        $form.on('input', 'input', function() {
            $(this).removeClass('is-invalid');
        });
    });
}

/**
 * Gestion des uploads de fichiers
 */
function initFileUpload() {
    $('form').each(function() {
        const $form = $(this);

        $form.on('submit', function(e) {
            const $fileInput = $form.find('input[type="file"]');
            if ($fileInput.length && $fileInput[0].files.length > 0) {
                const file = $fileInput[0].files[0];
                const maxSize = 16 * 1024 * 1024; // 16 Mo

                if (file.size > maxSize) {
                    e.preventDefault();
                    alert((window.I18N && window.I18N.fileTooLarge) || 'The file is too large. Maximum allowed size is 16 MB.');
                    $fileInput.addClass('is-invalid');
                }
            }
        });
    });
}