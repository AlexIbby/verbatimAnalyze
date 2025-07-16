# Gunicorn configuration for Railway deployment
# Fixes worker timeout issues during long-running classification tasks

# Worker timeout settings
timeout = 300  # 5 minutes - allows time for OpenAI API batch processing
worker_timeout = 300  # Match timeout
graceful_timeout = 30  # Time to gracefully shutdown workers

# Keep-alive to maintain connections
keepalive = 10

# Worker settings optimized for Railway
workers = 1  # Single worker to avoid session sharing issues with in-memory storage
worker_class = "sync"  # Sync workers for Flask app
worker_connections = 1000

# Logging
loglevel = "info"
accesslog = "-"  # Log to stdout
errorlog = "-"   # Log to stderr

# Preload app for better performance
preload_app = True

# Bind to Railway's expected interface
bind = "0.0.0.0:$PORT" if "$PORT" in str(__import__('os').environ) else "0.0.0.0:5000"