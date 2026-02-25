#!/usr/bin/env bash
# =============================================================================
# MIDI Box — VirtualHere USB Server Installer
# =============================================================================
#
# Installs and configures the VirtualHere USB-over-IP server on Raspberry Pi,
# allowing USB MIDI devices to be shared to a Mac over WiFi.
#
# Run manually:
#   sudo bash scripts/setup_virtualhere.sh
#
# Or triggered automatically from the MIDI Box web UI (USB Share page).
#
# =============================================================================

set -euo pipefail

# Colours (same as pi_setup.sh)
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
log()   { echo -e "${GREEN}[✓]${NC} $*"; }
info()  { echo -e "${CYAN}[→]${NC} $*"; }
warn()  { echo -e "${YELLOW}[!]${NC} $*"; }
error() { echo -e "${RED}[✗] ERROR:${NC} $*"; exit 1; }

[[ "$(id -u)" -ne 0 ]] && error "Run as root:  sudo bash scripts/setup_virtualhere.sh"

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
INSTALL_BIN="/usr/local/bin/vhusbd"
SERVICE_FILE="/etc/systemd/system/vhusbd.service"
SUDOERS_FILE="/etc/sudoers.d/midi-box-virtualhere"

# Detect the service user: prefer midi-box.service User= field, fall back to SERVICE_USER env, then datcal
SERVICE_USER="${SERVICE_USER:-}"
if [[ -z "$SERVICE_USER" ]]; then
    SERVICE_USER=$(systemctl show -p User midi-box.service 2>/dev/null | cut -d= -f2 || true)
fi
[[ -z "$SERVICE_USER" ]] && SERVICE_USER="datcal"

echo
echo -e "${CYAN}━━━ MIDI Box: VirtualHere USB Server Setup ━━━${NC}"
echo
info "Service user: $SERVICE_USER"

# ---------------------------------------------------------------------------
# 1. Detect architecture and select binary URL
# ---------------------------------------------------------------------------
ARCH=$(uname -m)
if [[ "$ARCH" == "aarch64" ]]; then
    VH_URL="https://www.virtualhere.com/sites/default/files/usbserver/vhusbdarm64"
    info "Architecture: ARM64 (aarch64)"
elif [[ "$ARCH" == "armv7l" || "$ARCH" == "armv6l" ]]; then
    VH_URL="https://www.virtualhere.com/sites/default/files/usbserver/vhusbdarm"
    info "Architecture: ARM 32-bit ($ARCH)"
else
    error "Unsupported architecture: $ARCH — expected aarch64 or armv7l"
fi

# ---------------------------------------------------------------------------
# 2. Download binary
# ---------------------------------------------------------------------------
info "Downloading VirtualHere USB server binary..."
TMP_BIN="$(mktemp)"
if command -v wget &>/dev/null; then
    wget -q --show-progress -O "$TMP_BIN" "$VH_URL" || error "Download failed (check internet connection)"
elif command -v curl &>/dev/null; then
    curl -L --progress-bar -o "$TMP_BIN" "$VH_URL" || error "Download failed (check internet connection)"
else
    error "Neither wget nor curl found — cannot download binary"
fi

# Verify it looks like an ELF binary
if ! file "$TMP_BIN" 2>/dev/null | grep -q ELF; then
    warn "Downloaded file may not be a valid binary — check the URL or try again"
fi

mv "$TMP_BIN" "$INSTALL_BIN"
chmod +x "$INSTALL_BIN"
log "Binary installed: $INSTALL_BIN"

# ---------------------------------------------------------------------------
# 3. Create systemd service
# ---------------------------------------------------------------------------
cat > "$SERVICE_FILE" << 'EOF'
[Unit]
Description=VirtualHere USB Server
Documentation=https://www.virtualhere.com/usb_server_software
After=network.target

[Service]
ExecStart=/usr/local/bin/vhusbd -b -s
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=vhusbd

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable vhusbd.service
log "Service installed and enabled: vhusbd.service"

# ---------------------------------------------------------------------------
# 4. Sudoers: allow service user to start/stop without password
# ---------------------------------------------------------------------------
cat > "$SUDOERS_FILE" << EOF
# MIDI Box — allow web UI to start/stop VirtualHere USB server without a password
$SERVICE_USER ALL=(ALL) NOPASSWD: /usr/bin/systemctl start vhusbd
$SERVICE_USER ALL=(ALL) NOPASSWD: /usr/bin/systemctl stop vhusbd
EOF
chmod 0440 "$SUDOERS_FILE"
log "Sudoers entry written: $SUDOERS_FILE"

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
echo
echo -e "${GREEN}╔══════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║     VirtualHere setup complete!               ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════╝${NC}"
echo
PI_IP=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "192.168.4.1")
info "Start server : sudo systemctl start vhusbd"
info "Stop server  : sudo systemctl stop vhusbd"
info "View logs    : sudo journalctl -u vhusbd -f"
info "Mac client   : connect to ${PI_IP}:7575"
echo
info "Or use the MIDI Box web UI — USB Share page."
echo
