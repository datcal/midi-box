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
step "3/6  Installing Python + MIDI + networking + kiosk packages"

apt-get install -y -qq \
    python3 python3-pip python3-venv \
    python3-rtmidi \
    libasound2-dev \
    hostapd dnsmasq \
    avahi-daemon avahi-utils \
    chromium xorg openbox unclutter \
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

# Sudoers: allow the service user to update hostapd config and restart it
# without a password — needed for the web UI WiFi credential editor.
SUDOERS_FILE="/etc/sudoers.d/midi-box-wifi"
cat > "$SUDOERS_FILE" << EOF
# MIDI Box — allow web UI to update WiFi AP credentials without a password
$SERVICE_USER ALL=(ALL) NOPASSWD: /usr/bin/tee /etc/hostapd/hostapd.conf
$SERVICE_USER ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart hostapd
EOF
chmod 0440 "$SUDOERS_FILE"
log "Sudoers entry written: $SUDOERS_FILE"

# ---------------------------------------------------------------------------
# 6. WiFi Access Point
# ---------------------------------------------------------------------------
step "6/7  Configuring WiFi Access Point"

bash "$CONFIG_DIR/setup_wifi_ap.sh"

# ---------------------------------------------------------------------------
# 7. UART overlays + touchscreen kiosk
# ---------------------------------------------------------------------------
step "7/7  Configuring UART overlays and touchscreen kiosk"

BOOT_CONFIG="/boot/firmware/config.txt"
[[ -f "$BOOT_CONFIG" ]] || BOOT_CONFIG="/boot/config.txt"  # fallback for older Pi OS

# Add UART overlays if not already present
if ! grep -q "disable-bt" "$BOOT_CONFIG"; then
    cat >> "$BOOT_CONFIG" << 'EOF'

# MIDI Box — UART overlays for 4x hardware MIDI OUT ports (replaces SC16IS752)
dtoverlay=disable-bt    # frees UART0 (GPIO 14) from Bluetooth → MS-20 Mini
dtoverlay=uart3         # GPIO 4  → /dev/ttyAMA2 → Volca #1
dtoverlay=uart4         # GPIO 8  → /dev/ttyAMA3 → Volca #2
dtoverlay=uart5         # GPIO 12 → /dev/ttyAMA4 → Volca #3

# Raspberry Pi 7" Official Touchscreen (DSI, auto-detected — no extra config needed)
EOF
    log "UART overlays added to $BOOT_CONFIG"
else
    log "UART overlays already present in $BOOT_CONFIG — skipping"
fi

# Disable Bluetooth service (UART0 is now used for MIDI)
systemctl disable bluetooth 2>/dev/null && log "Bluetooth disabled (UART0 reserved for MIDI)" || true

# Kiosk: create ~/.xinitrc to launch Chromium fullscreen on the touchscreen
XINITRC="/home/$SERVICE_USER/.xinitrc"
cat > "$XINITRC" << 'EOF'
#!/bin/sh
# MIDI Box kiosk — fullscreen Chromium on the 7" touchscreen
xset -dpms          # disable display power management
xset s noblank      # disable screen blanking
xset s off          # disable screensaver
unclutter -idle 1 -root &   # hide mouse cursor after 1s idle

# Wait for the MIDI Box web server to be ready
until curl -sf http://localhost:8080/api/settings > /dev/null 2>&1; do sleep 1; done

exec chromium \
    --kiosk \
    --noerrdialogs \
    --disable-infobars \
    --no-first-run \
    --disable-restore-session-state \
    --disable-session-crashed-bubble \
    --touch-events=enabled \
    http://localhost:8080/display
EOF
chmod +x "$XINITRC"
chown "$SERVICE_USER:$SERVICE_USER" "$XINITRC"
log "Kiosk .xinitrc written for user $SERVICE_USER"

# Systemd service to start the kiosk X session after midi-box is running
KIOSK_SERVICE="/etc/systemd/system/midi-box-kiosk.service"
cat > "$KIOSK_SERVICE" << EOF
[Unit]
Description=MIDI Box Kiosk (Chromium on touchscreen)
After=midi-box.service graphical.target
Wants=midi-box.service

[Service]
Type=simple
User=$SERVICE_USER
PAMName=login
Environment=XDG_RUNTIME_DIR=/run/user/$(id -u "$SERVICE_USER" 2>/dev/null || echo 1000)
ExecStart=/usr/bin/startx /home/$SERVICE_USER/.xinitrc -- :0 vt7
Restart=on-failure
RestartSec=5

[Install]
WantedBy=graphical.target
EOF
systemctl daemon-reload
systemctl enable midi-box-kiosk.service
log "Kiosk service installed: midi-box-kiosk.service"

# ---------------------------------------------------------------------------
# Done!
# ---------------------------------------------------------------------------
AP_SSID=$(grep 'AP_SSID=' "$CONFIG_DIR/setup_wifi_ap.sh" | head -1 | cut -d'"' -f2)
AP_PASS=$(grep 'AP_PASS=' "$CONFIG_DIR/setup_wifi_ap.sh" | head -1 | cut -d'"' -f2)
AP_IP=$(grep 'AP_IP=' "$CONFIG_DIR/setup_wifi_ap.sh" | head -1 | cut -d'"' -f2)

echo
echo -e "${GREEN}╔══════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║         Setup complete!                       ║${NC}"
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
