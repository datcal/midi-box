#!/usr/bin/env bash
# =============================================================================
# MIDI Box — Software Update Script
# =============================================================================
#
# Called by the web UI (via Python subprocess with start_new_session=True):
#   sudo /home/pi/midi-box/scripts/update.sh [simple|full]
#
# Runs DETACHED from midi-box.service so it survives the service restart.
# All output goes to /tmp/midi-box-update.log (stdout+stderr).
#
# Update types:
#   simple — git pull + pip install + service restart
#   full   — git pull + pip install + pi_setup.sh --update-only + service restart
# =============================================================================

set -euo pipefail

UPDATE_TYPE="${1:-simple}"

# Resolve paths from script location (works wherever the repo is cloned)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
SOFTWARE_DIR="$PROJECT_DIR/software"
VENV_DIR="$SOFTWARE_DIR/.venv"
SERVICE_USER="${SERVICE_USER:-pi}"

log() { echo "[$(date '+%H:%M:%S')] $*"; }

log "=== MIDI Box Update Starting ==="
log "Type: $UPDATE_TYPE"
log "Project: $PROJECT_DIR"
log "Running as: $(id)"

# ---------------------------------------------------------------------------
# Step 1: Git fetch + pull (run as service user to respect their gitconfig)
# ---------------------------------------------------------------------------
log "--- Step 1: Fetching latest code from GitHub ---"
cd "$PROJECT_DIR"

sudo -u "$SERVICE_USER" git fetch --tags --force
sudo -u "$SERVICE_USER" git pull --ff-only

LATEST_TAG=$(sudo -u "$SERVICE_USER" git describe --tags --abbrev=0 2>/dev/null || echo "unknown")
log "Pulled successfully. Latest tag: $LATEST_TAG"

# Update VERSION file
echo "$LATEST_TAG" > "$PROJECT_DIR/VERSION"
log "VERSION file updated: $LATEST_TAG"

# ---------------------------------------------------------------------------
# Step 2: Python dependencies
# ---------------------------------------------------------------------------
log "--- Step 2: Updating Python packages ---"
"$VENV_DIR/bin/pip" install --upgrade pip --quiet
"$VENV_DIR/bin/pip" install -r "$SOFTWARE_DIR/requirements.txt" --quiet
log "Python packages updated"

# ---------------------------------------------------------------------------
# Step 3: Full update — run pi_setup.sh for system-level changes
# ---------------------------------------------------------------------------
if [[ "$UPDATE_TYPE" == "full" ]]; then
    log "--- Step 3: Running full system setup (pi_setup.sh --update-only) ---"
    SERVICE_USER="$SERVICE_USER" bash "$SCRIPT_DIR/pi_setup.sh" --update-only
    log "Full system setup complete"
else
    log "--- Step 3: Skipping full system setup (simple update) ---"
fi

# ---------------------------------------------------------------------------
# Step 4: Restart the midi-box service
# systemd will restart the process; this script's detached session survives.
# ---------------------------------------------------------------------------
log "--- Step 4: Restarting midi-box.service ---"
systemctl restart midi-box.service
log "Service restart command sent"

log "=== Update Complete: $LATEST_TAG ==="
