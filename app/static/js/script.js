// Document Ready
$(document).ready(function() {
    initFlashMessages();
    initFormValidation();
    initFileUpload();
});

/**
 * Gestion des messages flash
 */
function initFlashMessages() {
    // Fermer les messages flash après 5 secondes
    setTimeout(function() {
        $('.flash-message').fadeOut(500, function() {
            $(this).remove();
        });
    }, 5000);

    // Fermer manuellement les messages flash
    $('.flash-message').each(function() {
        const $message = $(this);
        const $closeBtn = $('<a href="#" class="flash-close"><i class="fas fa-times"></i></a>');
        $closeBtn.on('click', function() {
            $message.fadeOut(500, function() {
                $(this).remove();
            });
        });
        $message.append($closeBtn);
    });
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
                $username.addClass('error');
                $username.after('<span class="error-message">Le nom d\'utilisateur est obligatoire</span>');
            }

            if ($password.val().trim() === '') {
                e.preventDefault();
                $password.addClass('error');
                $password.after('<span class="error-message">Le mot de passe est obligatoire</span>');
            }
        });

        $form.on('input', 'input', function() {
            $(this).removeClass('error');
            $(this).next('.error-message').remove();
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
                    alert('Le fichier est trop volumineux. La taille maximale autorisée est de 16 Mo.');
                    $fileInput.addClass('error');
                }
            }
        });
    });
}