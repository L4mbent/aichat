#!/bin/bash
# Asuna AI Agent - Auto Installer for Ubuntu/Debian
# Usage: ssh to your server, then run: bash deploy/install.sh
set -e

# =============================================================================
# Config — CHANGE THESE to match your setup
# =============================================================================
DOMAIN="asuna.top"                     # Your domain (must have DNS A record pointing to this server)
DEEPSEEK_API_KEY="sk-611327640d32489aa6e0490c02eb2faf"
DEEPSEEK_MODEL="deepseek-chat"

# =============================================================================
# Colors
# =============================================================================
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log()   { echo -e "${GREEN}[OK]${NC} $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
err()   { echo -e "${RED}[ERR]${NC} $1"; exit 1; }

echo "========================================="
echo "  Asuna AI Agent - Installer"
echo "  结城明日奈 · WeChat iLink ClawBot"
echo "========================================="
echo ""

# =============================================================================
# Step 1: System dependencies
# =============================================================================
log "Step 1: Installing system dependencies..."

apt update -qq
apt install -y -qq python3 python3-pip python3-venv nginx certbot python3-certbot-nginx curl

log "System dependencies installed"

# =============================================================================
# Step 2: Create user and directories
# =============================================================================
log "Step 2: Creating asuna user..."

id -u asuna &>/dev/null || useradd -r -s /bin/false asuna

mkdir -p /opt/asuna/data
log "User and directories created"

# =============================================================================
# Step 3: Python virtualenv + dependencies
# =============================================================================
log "Step 3: Installing Python dependencies..."

VENV_DIR="/opt/asuna/venv"
python3 -m venv "$VENV_DIR"
"$VENV_DIR/bin/pip" install --upgrade pip -q

"$VENV_DIR/bin/pip" install \
    fastapi \
    "uvicorn[standard]" \
    httpx \
    openai \
    "sqlalchemy[asyncio]" \
    aiosqlite \
    pydantic-settings \
    python-dotenv \
    aiofiles

log "Python dependencies installed"

# =============================================================================
# Step 4: Write .env config
# =============================================================================
log "Step 4: Creating .env configuration..."

cat > /opt/asuna/.env << ENVEOF
DEEPSEEK_API_KEY=$DEEPSEEK_API_KEY
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
DEEPSEEK_MODEL=$DEEPSEEK_MODEL
ILINK_BASE_URL=https://ilinkai.weixin.qq.com
ILINK_APP_ID=bot
ILINK_CLIENT_VERSION=131073
ILINK_LONG_POLL_TIMEOUT=35
HOST=0.0.0.0
PORT=8080
DATABASE_URL=sqlite+aiosqlite:///data/asuna.db
RATE_LIMIT_PER_MINUTE=10
RATE_LIMIT_PER_HOUR=100
MAX_HISTORY_TURNS=30
SESSION_TIMEOUT_MINUTES=30
LOG_LEVEL=INFO
ENVEOF

chmod 600 /opt/asuna/.env
log ".env created"

# =============================================================================
# Step 5: Install systemd service
# =============================================================================
log "Step 5: Installing systemd service..."

cat > /etc/systemd/system/asuna.service << UNITEOF
[Unit]
Description=Asuna AI Agent - Yuuki Asuna WeChat Bot
After=network.target

[Service]
Type=simple
User=asuna
Group=asuna
WorkingDirectory=/opt/asuna
Environment="PATH=$VENV_DIR/bin:/usr/local/bin:/usr/bin:/bin"
EnvironmentFile=/opt/asuna/.env
ExecStart=$VENV_DIR/bin/python run.py serve
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=asuna-agent
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ProtectHome=yes
ReadWritePaths=/opt/asuna/data

[Install]
WantedBy=multi-user.target
UNITEOF

systemctl daemon-reload
log "systemd service installed"

# =============================================================================
# Step 6: Setup Nginx
# =============================================================================
log "Step 6: Configuring Nginx..."

cat > /etc/nginx/sites-available/asuna << NGINXEOF
server {
    listen 80;
    server_name $DOMAIN;

    client_max_body_size 10M;

    location /health {
        proxy_pass http://127.0.0.1:8080/health;
        proxy_set_header Host \$host;
    }
}
NGINXEOF

# Remove default site
rm -f /etc/nginx/sites-enabled/default

# Enable asuna site
if [ -d /etc/nginx/sites-enabled ]; then
    ln -sf /etc/nginx/sites-available/asuna /etc/nginx/sites-enabled/
elif [ -d /etc/nginx/conf.d ]; then
    ln -sf /etc/nginx/sites-available/asuna /etc/nginx/conf.d/asuna.conf
fi

nginx -t && systemctl reload nginx
log "Nginx configured"

# =============================================================================
# Step 7: HTTPS certificate
# =============================================================================
log "Step 7: Obtaining HTTPS certificate for $DOMAIN..."

# Open firewall ports if ufw is active
if command -v ufw &>/dev/null; then
    ufw allow 80/tcp 2>/dev/null || true
    ufw allow 443/tcp 2>/dev/null || true
fi

certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos --email "admin@$DOMAIN" --redirect 2>&1 || {
    warn "certbot auto failed. Run manually: certbot --nginx -d $DOMAIN"
    warn "Make sure port 80 is reachable and DNS is set up correctly."
}
log "HTTPS configured"

# =============================================================================
# Step 8: Set permissions and start service
# =============================================================================
log "Step 8: Setting permissions..."

chown -R asuna:asuna /opt/asuna

log "Step 9: Starting Asuna..."

systemctl enable asuna
systemctl restart asuna
sleep 2

if systemctl is-active --quiet asuna; then
    log "Asuna is RUNNING!"
else
    warn "Asuna failed to start. Check: journalctl -u asuna -n 30"
fi

# =============================================================================
# Done
# =============================================================================
echo ""
echo "========================================="
echo "  Installation Complete!"
echo "========================================="
echo ""
echo -e "${YELLOW}Verify:${NC}"
echo "  curl https://$DOMAIN/health"
echo "  systemctl status asuna"
echo "  journalctl -u asuna -f"
echo ""
