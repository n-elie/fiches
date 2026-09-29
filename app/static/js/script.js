/**
 * Script principal pour l'application de spectrométrie de masse
 */

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
    /*setTimeout(function() {
        $('.flash-message').fadeOut(500, function() {
            $(this).remove();
        });
    }, 5000);*/

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
    $('.sample-form').each(function() {
        const $form = $(this);

        $form.on('submit', function(e) {
            let isValid = true;

            $('.form-group.required input[required], .form-group.required select[required]').each(function() {
                const $input = $(this);
                if ($input.val().trim() === '') {
                    isValid = false;
                    $input.addClass('error');
                    $input.after('<span class="error-message">Ce champ est obligatoire</span>');
                } else {
                    $input.removeClass('error');
                    $input.next('.error-message').remove();
                }
            });

            const $fileInput = $('#structure_file[required]');
            if ($fileInput.length && $fileInput.val() === '') {
                isValid = false;
                $fileInput.addClass('error');
                $fileInput.after('<span class="error-message">Veuillez sélectionner un fichier de structure</span>');
            } else {
                $fileInput.removeClass('error');
                $fileInput.next('.error-message').remove();
            }

            const $quantityInput = $('#quantity');
            if ($quantityInput.length) {
                const quantity = parseFloat($quantityInput.val());
                if (isNaN(quantity) || quantity <= 0) {
                    isValid = false;
                    $quantityInput.addClass('error');
                    $quantityInput.after('<span class="error-message">Veuillez entrer une quantité valide (nombre positif)</span>');
                } else {
                    $quantityInput.removeClass('error');
                    $quantityInput.next('.error-message').remove();
                }
            }

            if (!isValid) {
                e.preventDefault();
                const firstError = $('.error').first();
                if (firstError.length) {
                    $('html, body').animate({
                        scrollTop: firstError.offset().top - 100
                    }, 500);
                }
            }
        });

        $form.on('input change', 'input, select, textarea', function() {
            $(this).removeClass('error');
            $(this).next('.error-message').remove();
        });
    });

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
    $('input[type="file"]').each(function() {
        const $input = $(this);
        const $fileNameDisplay = $('<div class="file-name-display"></div>');

        $input.on('change', function() {
            const fileName = $(this).val().split('\\\\').pop();
            if (fileName) {
                $fileNameDisplay.text(fileName).insertAfter($input);
            } else {
                $fileNameDisplay.remove();
            }
        });

        $input.closest('form').on('reset', function() {
            $fileNameDisplay.remove();
        });
    });

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