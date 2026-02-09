#!/bin/bash
# startup.sh - Optimized startup script for Unraid

set -e

echo "================================"
echo "Helios Application Startup"
echo "================================"

# Create necessary directories
mkdir -p /app/data /app/logs

# Set proper permissions
chmod 755 /app/data /app/logs

# Log startup
echo "[$(date +'%Y-%m-%d %H:%M:%S')] Application starting..." >> /app/logs/startup.log

# Check Python version
echo "[$(date +'%Y-%m-%d %H:%M:%S')] Python version: $(python --version)" >> /app/logs/startup.log

# Verify dependencies
echo "[$(date +'%Y-%m-%d %H:%M:%S')] Checking dependencies..." >> /app/logs/startup.log
python -c "import flask; import cryptography; print('✓ All dependencies OK')"

# Set environment defaults if not already set
export FLASK_ENV=${FLASK_ENV:-production}
export PYTHONUNBUFFERED=1
export PYTHONDONTWRITEBYTECODE=1

echo "[$(date +'%Y-%m-%d %H:%M:%S')] Environment configured" >> /app/logs/startup.log
echo "[$(date +'%Y-%m-%d %H:%M:%S')] Starting application..." >> /app/logs/startup.log

# Execute the main application
exec "$@"
