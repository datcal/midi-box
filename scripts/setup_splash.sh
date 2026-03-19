#!/usr/bin/env bash
# =============================================================================
# MIDI Box — Boot Splash Setup
# =============================================================================
# Installs a custom Plymouth boot splash and silences the Linux boot text.
#
# Called automatically by pi_setup.sh, or run standalone:
#   sudo bash scripts/setup_splash.sh
#
# What this does:
#   1. Installs Plymouth and the script module
#   2. Copies the MIDI Box Plymouth theme
#   3. Sets it as the default theme
#   4. Patches /boot/firmware/cmdline.txt for quiet/splash boot
#   5. Rebuilds initramfs so Plymouth starts from early boot
# =============================================================================

set -euo pipefail

[[ "$(id -u)" -ne 0 ]] && { echo "[✗] Run as root: sudo bash scripts/setup_splash.sh"; exit 1; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
THEME_SRC="$SCRIPT_DIR/splash"
THEME_DST="/usr/share/plymouth/themes/midi-box"

GREEN='\033[0;32m'; CYAN='\033[0;36m'; YELLOW='\033[1;33m'; NC='\033[0m'
log()  { echo -e "${GREEN}[✓]${NC} $*"; }
info() { echo -e "${CYAN}[→]${NC} $*"; }
warn() { echo -e "${YELLOW}[!]${NC} $*"; }

echo
echo -e "${CYAN}━━━ Boot Splash Setup ━━━${NC}"

# ---------------------------------------------------------------------------
# 1. Install Plymouth
# ---------------------------------------------------------------------------
info "Installing Plymouth..."
apt-get install -y -qq plymouth plymouth-themes
log "Plymouth installed"

# ---------------------------------------------------------------------------
# 2. Copy theme files
# ---------------------------------------------------------------------------
info "Installing MIDI Box Plymouth theme..."
mkdir -p "$THEME_DST"
cp "$THEME_SRC/midi-box.plymouth" "$THEME_DST/"
cp "$THEME_SRC/midi-box.script"   "$THEME_DST/"
chmod 644 "$THEME_DST"/*
log "Theme installed at $THEME_DST"

# ---------------------------------------------------------------------------
# 3. Set as default theme
# ---------------------------------------------------------------------------
if command -v plymouth-set-default-theme &>/dev/null; then
    plymouth-set-default-theme midi-box
    log "Default Plymouth theme set to: midi-box"
else
    # Fallback: update-alternatives
    update-alternatives --install \
        /usr/share/plymouth/themes/default.plymouth \
        default.plymouth \
        "$THEME_DST/midi-box.plymouth" 100
    update-alternatives --set \
        default.plymouth \
        "$THEME_DST/midi-box.plymouth"
    log "Default Plymouth theme set via update-alternatives"
fi

# ---------------------------------------------------------------------------
# 4. Patch cmdline.txt — silence boot text, enable Plymouth graphical splash
#    IMPORTANT: Do NOT change console=tty1 — the kiosk autologin needs it.
#    Instead we suppress text with systemd.show_status=0 and quiet/loglevel.
# ---------------------------------------------------------------------------
CMDLINE="/boot/firmware/cmdline.txt"
[[ -f "$CMDLINE" ]] || CMDLINE="/boot/cmdline.txt"   # older Pi OS fallback

if [[ ! -f "$CMDLINE" ]]; then
    warn "Could not find cmdline.txt — skipping kernel cmdline patch"
else
    # Back up original (once)
    [[ -f "${CMDLINE}.bak" ]] || cp "$CMDLINE" "${CMDLINE}.bak"

    CURRENT="$(cat "$CMDLINE")"
    PATCHED="$CURRENT"

    # Remove serial console — it forces Plymouth into text-only "details" mode
    # (Plymouth assumes serial console = headless system, skips graphical splash)
    PATCHED="$(echo "$PATCHED" | sed 's/console=serial0,[0-9]* //')"

    # Ensure console stays on tty1 (kiosk autologin depends on it)
    # If somehow set to tty3 (which breaks kiosk), revert it
    PATCHED="$(echo "$PATCHED" | sed 's/console=tty3/console=tty1/')"

    # Add flags only if not already present
    echo "$PATCHED" | grep -qw "quiet"                    || PATCHED="$PATCHED quiet"
    echo "$PATCHED" | grep -qw "splash"                   || PATCHED="$PATCHED splash"
    echo "$PATCHED" | grep -qw "loglevel"                 || PATCHED="$PATCHED loglevel=0"
    echo "$PATCHED" | grep -qw "vt.global_cursor_default" || PATCHED="$PATCHED vt.global_cursor_default=0"
    echo "$PATCHED" | grep -qw "logo.nologo"              || PATCHED="$PATCHED logo.nologo"
    echo "$PATCHED" | grep -qw "systemd.show_status"      || PATCHED="$PATCHED systemd.show_status=0"

    # Strip trailing whitespace and write back as a single line (required format)
    echo "${PATCHED%% }" | tr -s ' ' > "$CMDLINE"
    log "Patched $CMDLINE"
fi

# ---------------------------------------------------------------------------
# 5. Patch config.txt — disable Pi's early GPU rainbow square
# ---------------------------------------------------------------------------
CONFIG="/boot/firmware/config.txt"
[[ -f "$CONFIG" ]] || CONFIG="/boot/config.txt"

if [[ -f "$CONFIG" ]]; then
    if grep -q "disable_splash" "$CONFIG"; then
        sed -i 's/disable_splash=0/disable_splash=1/' "$CONFIG"
    else
        echo "disable_splash=1" >> "$CONFIG"
    fi
    log "Disabled Pi GPU rainbow splash in $CONFIG"
else
    warn "Could not find config.txt — skipping GPU splash disable"
fi

# ---------------------------------------------------------------------------
# 6. Black out tty1 before Plymouth quits — prevents [OK] text flash
#    systemd writes service status behind the Plymouth splash; when Plymouth
#    quits, those messages briefly appear before X starts. This drop-in
#    clears tty1 to black right before Plymouth exits.
# ---------------------------------------------------------------------------
info "Installing plymouth-quit blackout drop-in..."
DROPIN_DIR="/etc/systemd/system/plymouth-quit.service.d"
mkdir -p "$DROPIN_DIR"
cat > "$DROPIN_DIR/blackout.conf" << 'DROPEOF'
[Service]
ExecStartPre=/bin/sh -c '/usr/bin/setterm --foreground black --background black --clear all --cursor off --term linux </dev/tty1 >/dev/tty1'
DROPEOF
systemctl daemon-reload
log "plymouth-quit blackout drop-in installed"

# ---------------------------------------------------------------------------
# 7. Switch to blank VT on shutdown — hides all service stop messages
# ---------------------------------------------------------------------------
info "Installing shutdown blackout service..."
cat > /etc/systemd/system/midi-box-shutdown-blackout.service << 'SVCEOF'
[Unit]
Description=Switch to blank VT on shutdown to hide service stop messages
DefaultDependencies=no
Before=shutdown.target reboot.target poweroff.target halt.target
Conflicts=getty@tty12.service

[Service]
Type=oneshot
ExecStart=/usr/bin/chvt 12

[Install]
WantedBy=reboot.target poweroff.target halt.target
SVCEOF
systemctl daemon-reload
systemctl enable midi-box-shutdown-blackout.service 2>/dev/null
log "Shutdown blackout service installed"

# ---------------------------------------------------------------------------
# 8. Rebuild initramfs for ALL installed kernels so every boot path has Plymouth
# ---------------------------------------------------------------------------
info "Rebuilding initramfs for all kernels (this may take ~60 seconds)..."
update-initramfs -u -k all 2>&1 | tail -5
log "initramfs rebuilt"

echo
log "Boot splash setup complete — changes take effect on next reboot"
info "  Theme location : $THEME_DST"
info "  To preview    : sudo plymouthd & sleep 1 && sudo plymouth --show-splash && sleep 6 && sudo plymouth quit"
