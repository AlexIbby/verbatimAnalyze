from flask import Flask, render_template
import os
import logging
from config import Config
from routes.upload import upload_bp
from routes.suggest import suggest_bp
from routes.classify import classify_bp
from routes.summary import summary_bp
from routes.download import download_bp
from apscheduler.schedulers.background import BackgroundScheduler
import atexit
import glob
import time

app = Flask(__name__)
app.config.from_object(Config)
Config.init_app(app)

# Configure logging with detailed format
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s'
)
app.logger.setLevel(logging.DEBUG)

# Enable Werkzeug request logging (for HTTP request logs)
werkzeug_logger = logging.getLogger('werkzeug')
werkzeug_logger.setLevel(logging.DEBUG)
werkzeug_logger.addHandler(logging.StreamHandler())

# Register blueprints
app.register_blueprint(upload_bp)
app.register_blueprint(suggest_bp)
app.register_blueprint(classify_bp)
app.register_blueprint(summary_bp)
app.register_blueprint(download_bp)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/favicon.ico')
def favicon():
    return '', 204  # No Content

def cleanup_old_files():
    """Clean up old uploaded files"""
    try:
        upload_folder = app.config['UPLOAD_FOLDER']
        if not os.path.exists(upload_folder):
            return
        
        current_time = time.time()
        cleanup_age = 24 * 60 * 60  # 24 hours in seconds (1 day)
        
        for filepath in glob.glob(os.path.join(upload_folder, "*")):
            if os.path.isfile(filepath):
                file_age = current_time - os.path.getmtime(filepath)
                if file_age > cleanup_age:
                    try:
                        os.remove(filepath)
                        app.logger.info(f"Cleaned up old file: {filepath}")
                    except Exception as e:
                        app.logger.error(f"Failed to cleanup {filepath}: {e}")
    except Exception as e:
        app.logger.error(f"Cleanup job failed: {e}")

# Setup cleanup scheduler
if not app.debug:
    scheduler = BackgroundScheduler()
    scheduler.add_job(func=cleanup_old_files, trigger="interval", minutes=10)
    scheduler.start()
    atexit.register(lambda: scheduler.shutdown())

if __name__ == '__main__':
    app.run(debug=True, port=os.getenv("PORT", default=5000))
