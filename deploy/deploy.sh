#!/bin/bash
set -e

APP_DIR="/opt/asuna"
VENV_DIR="$APP_DIR/venv"
DATA_DIR="$APP_DIR/data"

echo "=== Asuna AI Agent Deployment ==="

# Create user if not exists
id -u asuna &>/dev/null || useradd -r -s /bin/false asuna

# Create directories
mkdir -p "$APP_DIR" "$DATA_DIR"
chown -R asuna:asuna "$APP_DIR"

# Copy application files
cp -r asuna/ "$APP_DIR/"
cp requirements.txt "$APP_DIR/"
cp .env.example "$APP_DIR/"

# Setup Python virtualenv
echo "Setting up Python environment..."
python3 -m venv "$VENV_DIR"
"$VENV_DIR/bin/pip" install --upgrade pip
"$VENV_DIR/bin/pip" install -r "$APP_DIR/requirements.txt"

# Install systemd service
cp deploy/asuna.service /etc/systemd/system/

# Install nginx config (if nginx is present)
if command -v nginx &>/dev/null; then
    cp deploy/nginx.conf /etc/nginx/sites-available/asuna-bot
    ln -sf /etc/nginx/sites-available/asuna-bot /etc/nginx/sites-enabled/
    nginx -t && systemctl reload nginx
    echo "Nginx configured."
    echo ""
    echo "Don't forget to set up HTTPS:"
    echo "  certbot --nginx -d asuna-bot.your-domain.com"
fi

echo ""
echo "=== Next Steps ==="
echo "1. Edit /opt/asuna/.env and fill in your API keys and WeCom config"
echo "2. systemctl daemon-reload && systemctl enable asuna && systemctl start asuna"
echo "3. Check status: systemctl status asuna"
echo "4. View logs: journalctl -u asuna -f"
echo ""
echo "Done! Asuna is ready to deploy."
