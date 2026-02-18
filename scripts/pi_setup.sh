#!/usr/bin/env bash
# =============================================================================
# MIDI Box — Raspberry Pi One-Command Installer
# =============================================================================
#
# Run ONCE on a fresh Raspberry Pi after first boot:
#
#   git clone <your-repo> ~/midi-box
#   cd ~/midi-box
#   sudo bash scripts/pi_setup.sh
#
# Or specify your WiFi country (ISO 3166-1 alpha-2):
#
#   sudo WIFI_COUNTRY=TR bash scripts/pi_setup.sh
#
# What this does:
#   1. Fixes WiFi (rfkill unblock, country code)
#   2. Updates system packages
#   3. Installs Python 3 + MIDI + networking dependencies
#   4. Creates Python venv + installs pip requirements
#   5. Installs systemd service (autostart on boot)
#   6. Configures WiFi Access Point (MIDI-BOX hotspot)
#   7. Reboots
#
# After reboot:
#   - WiFi network "MIDI-BOX" will be visible
#   - Web UI at http://192.168.4.1:8080
#   - Display / QR page at http://192.168.4.1:8080/display
# =============================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# Config — override via env vars before running
# ---------------------------------------------------------------------------
WIFI_COUNTRY="${WIFI_COUNTRY:-US}"   # Your country code (TR, GB, DE, FR, etc.)
SERVICE_USER="${SERVICE_USER:-$(logname 2>/dev/null || echo pi)}"

# Colours
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
log()   { echo -e "${GREEN}[✓]${NC} $*"; }
info()  { echo -e "${CYAN}[→]${NC} $*"; }
warn()  { echo -e "${YELLOW}[!]${NC} $*"; }
error() { echo -e "${RED}[✗] ERROR:${NC} $*"; exit 1; }
step()  { echo; echo -e "${CYAN}━━━ $* ━━━${NC}"; }

# ---------------------------------------------------------------------------
# Sanity checks
# ---------------------------------------------------------------------------
[[ "$(id -u)" -ne 0 ]] && error "Run as root:  sudo bash scripts/pi_setup.sh"

# Detect project root (the directory containing this script's parent)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
SOFTWARE_DIR="$PROJECT_DIR/software"
CONFIG_DIR="$SOFTWARE_DIR/config"

[[ -d "$SOFTWARE_DIR" ]] || error "Cannot find software/ directory at: $SOFTWARE_DIR"
[[ -f "$SOFTWARE_DIR/requirements.txt" ]] || error "Cannot find requirements.txt at: $SOFTWARE_DIR/requirements.txt"

echo
echo -e "${GREEN}╔══════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║       MIDI Box — Raspberry Pi Setup          ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════╝${NC}"
echo
info "Project dir : $PROJECT_DIR"
info "Software dir: $SOFTWARE_DIR"
info "Run as user : $SERVICE_USER"
info "WiFi country: $WIFI_COUNTRY"
echo

# ---------------------------------------------------------------------------
# 1. Fix WiFi rfkill  (this is the most common first-boot issue)
# ---------------------------------------------------------------------------
step "1/6  Fixing WiFi (rfkill + country code)"

# Unblock all radios
rfkill unblock all 2>/dev/null && log "rfkill: all radios unblocked" || warn "rfkill command not available"

# Set WiFi regulatory country — this is what Pi OS requires before WiFi works
if command -v raspi-config &>/dev/null; then
    raspi-config nonint do_wifi_country "$WIFI_COUNTRY" \
        && log "WiFi country set to $WIFI_COUNTRY via raspi-config" \
        || warn "raspi-config country set failed — trying iw..."
fi

# Fallback: set via iw reg
if command -v iw &>/dev/null; then
    iw reg set "$WIFI_COUNTRY" 2>/dev/null && log "WiFi regulatory domain set via iw" || true
fi

# Make country persist across reboots via /etc/wpa_supplicant/wpa_supplicant.conf
WPA_CONF="/etc/wpa_supplicant/wpa_supplicant.conf"
if [[ -f "$WPA_CONF" ]]; then
    if ! grep -q "country=" "$WPA_CONF"; then
        sed -i "1a country=$WIFI_COUNTRY" "$WPA_CONF"
        log "Added country=$WIFI_COUNTRY to wpa_supplicant.conf"
    else
        sed -i "s/^country=.*/country=$WIFI_COUNTRY/" "$WPA_CONF"
        log "Updated country=$WIFI_COUNTRY in wpa_supplicant.conf"
    fi
else
    # Create minimal wpa_supplicant.conf (AP mode doesn't need networks block)
    cat > "$WPA_CONF" << EOF
ctrl_interface=DIR=/var/run/wpa_supplicant GROUP=netdev
update_config=1
country=$WIFI_COUNTRY
EOF
    log "Created wpa_supplicant.conf with country=$WIFI_COUNTRY"
fi

# ---------------------------------------------------------------------------
# 2. System update
# ---------------------------------------------------------------------------
step "2/6  Updating system packages"

apt-get update -qq
apt-get upgrade -y -qq
log "System packages up to date"

# ---------------------------------------------------------------------------
# 3. Install system dependencies
# ---------------------------------------------------------------------------
step "3/6  Installing Python + MIDI + networking packages"

apt-get install -y -qq \
    python3 python3-pip python3-venv \
    python3-rtmidi \
    libasound2-dev \
    hostapd dnsmasq \
    git curl

log "System packages installed"

# ---------------------------------------------------------------------------
# 4. Python virtual environment + pip packages
# ---------------------------------------------------------------------------
step "4/6  Setting up Python environment"

VENV_DIR="$SOFTWARE_DIR/.venv"

if [[ ! -d "$VENV_DIR" ]]; then
    python3 -m venv "$VENV_DIR"
    log "Created venv at $VENV_DIR"
else
    log "Existing venv found at $VENV_DIR"
fi

"$VENV_DIR/bin/pip" install --upgrade pip -q
"$VENV_DIR/bin/pip" install -r "$SOFTWARE_DIR/requirements.txt" -q
log "Python packages installed"

# ---------------------------------------------------------------------------
# 5. Systemd service
# ---------------------------------------------------------------------------
step "5/6  Installing systemd service"

# Resolve the real home dir for the service user
USER_HOME=$(getent passwd "$SERVICE_USER" | cut -d: -f6 2>/dev/null || echo "/home/$SERVICE_USER")

SERVICE_FILE="/etc/systemd/system/midi-box.service"
cat > "$SERVICE_FILE" << EOF
[Unit]
Description=MIDI Box Router
Documentation=https://github.com/your-org/midi-box
After=network.target sound.target
Wants=network.target

[Service]
Type=simple
User=$SERVICE_USER
WorkingDirectory=$SOFTWARE_DIR
ExecStart=$VENV_DIR/bin/python src/main.py
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1
StandardOutput=journal
StandardError=journal
SyslogIdentifier=midi-box

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable midi-box.service
log "Service installed and enabled: midi-box.service"
info "  Control: sudo systemctl {start|stop|restart|status} midi-box"
info "  Logs:    sudo journalctl -u midi-box -f"

# ---------------------------------------------------------------------------
# 6. WiFi Access Point
# ---------------------------------------------------------------------------
step "6/6  Configuring WiFi Access Point"

bash "$CONFIG_DIR/setup_wifi_ap.sh"

# ---------------------------------------------------------------------------
# Done!
# ---------------------------------------------------------------------------
AP_SSID=$(grep 'AP_SSID=' "$CONFIG_DIR/setup_wifi_ap.sh" | head -1 | cut -d'"' -f2)
AP_PASS=$(grep 'AP_PASS=' "$CONFIG_DIR/setup_wifi_ap.sh" | head -1 | cut -d'"' -f2)
AP_IP=$(grep 'AP_IP=' "$CONFIG_DIR/setup_wifi_ap.sh" | head -1 | cut -d'"' -f2)

echo
echo -e "${GREEN}╔══════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║         Setup complete!                      ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════╝${NC}"
echo
echo -e "  WiFi network : ${CYAN}${AP_SSID:-MIDI-BOX}${NC}"
echo -e "  Password     : ${CYAN}${AP_PASS:-midibox123}${NC}"
echo -e "  Web UI       : ${CYAN}http://${AP_IP:-192.168.4.1}:8080${NC}"
echo -e "  Display/QR   : ${CYAN}http://${AP_IP:-192.168.4.1}:8080/display${NC}"
echo

read -r -p "  Reboot now? [Y/n] " REPLY
REPLY="${REPLY:-Y}"
if [[ "$REPLY" =~ ^[Yy]$ ]]; then
    log "Rebooting in 3 seconds..."
    sleep 3
    reboot
else
    warn "Remember to reboot for WiFi AP to take effect!"
    info "  sudo reboot"
fi
