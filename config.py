import os
from datetime import timedelta

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key-change-in-production'
    UPLOAD_FOLDER = os.path.join(os.getcwd(), 'tmp')
    MAX_CONTENT_LENGTH = 5 * 1024 * 1024  # 5MB max file size
    ALLOWED_EXTENSIONS = {'xlsx', 'xls', 'csv'}
    
    # OpenAI API key
    OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY')
    
    # Cleanup settings
    CLEANUP_INTERVAL = timedelta(minutes=30)
    
    @staticmethod
    def init_app(app):
        # Ensure upload folder exists
        os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)