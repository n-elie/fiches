from app import create_app
import os

# Créer l'application
app = create_app()

# S'assurer que le dossier d'uploads existe
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=app.config['PORT'], debug=app.config['DEBUG'])