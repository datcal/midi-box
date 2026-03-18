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
# 4. Patch cmdline.txt — add quiet splash and suppress cursor/penguin logos
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

    # Add flags only if not already present
    echo "$CURRENT" | grep -qw "quiet"                    || PATCHED="$PATCHED quiet"
    echo "$CURRENT" | grep -qw "splash"                   || PATCHED="$PATCHED splash"
    echo "$CURRENT" | grep -qw "loglevel"                 || PATCHED="$PATCHED loglevel=3"
    echo "$CURRENT" | grep -qw "vt.global_cursor_default" || PATCHED="$PATCHED vt.global_cursor_default=0"
    echo "$CURRENT" | grep -qw "logo.nologo"              || PATCHED="$PATCHED logo.nologo"

    # Strip trailing whitespace and write back as a single line (required format)
    echo "${PATCHED%% }" | tr -s ' ' > "$CMDLINE"
    log "Patched $CMDLINE (quiet splash loglevel=3 vt.global_cursor_default=0 logo.nologo)"
fi

# ---------------------------------------------------------------------------
# 5. Rebuild initramfs so Plymouth is available from early boot
# ---------------------------------------------------------------------------
info "Rebuilding initramfs (this may take ~30 seconds)..."
update-initramfs -u 2>&1 | tail -3
log "initramfs rebuilt"

echo
log "Boot splash setup complete — changes take effect on next reboot"
info "  Theme location : $THEME_DST"
info "  To preview now : sudo plymouthd --debug; sudo plymouth --show-splash; sleep 5; sudo plymouth quit"
