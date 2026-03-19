#!/usr/bin/env bash
# =============================================================================
# MIDI Box — WiFi Access Point Setup (Dual-Interface, NetworkManager-aware)
# =============================================================================
# Creates a virtual AP interface (uap0) on top of wlan0 so the Pi can
# simultaneously:
#   - Connect to home WiFi via wlan0  (SSH / internet access)
#   - Broadcast MIDI-BOX hotspot via uap0  (standalone / web UI)
#
# Designed for Raspberry Pi OS Bookworm (NetworkManager default).
# Does NOT touch dhcpcd.conf — IP is assigned directly in the systemd service.
#
# Usage:
#   sudo bash config/setup_wifi_ap.sh
#   sudo reboot
# =============================================================================

set -e

AP_IFACE="uap0"
AP_SSID="MIDI-BOX"
AP_PASS="midibox123"
AP_IP="192.168.4.1"
AP_CHANNEL="6"
NETMASK="255.255.255.0"
DHCP_START="192.168.4.10"
DHCP_END="192.168.4.50"

if [ "$(id -u)" -ne 0 ]; then
  echo "ERROR: Run this script as root (sudo)"
  exit 1
fi

echo "======================================================"
echo "  MIDI Box — WiFi AP Setup (dual-interface)"
echo "  SSID      : $AP_SSID"
echo "  Pass      : $AP_PASS"
echo "  AP iface  : $AP_IFACE  (virtual, on top of wlan0)"
echo "  Pi IP     : $AP_IP"
echo "======================================================"

# --- Fix rfkill ---
echo "[0/6] Unblocking WiFi (rfkill)..."
rfkill unblock all 2>/dev/null || true

# --- Ensure packages are available (already installed by pi_setup.sh) ---
echo "[1/6] Checking hostapd and dnsmasq..."
if ! command -v hostapd &>/dev/null || ! command -v dnsmasq &>/dev/null; then
    apt-get update -qq
    apt-get install -y hostapd dnsmasq
fi

systemctl stop hostapd dnsmasq 2>/dev/null || true

# --- Tell NetworkManager to leave uap0 alone ---
echo "[2/6] Configuring NetworkManager to ignore $AP_IFACE..."
mkdir -p /etc/NetworkManager/conf.d
cat > /etc/NetworkManager/conf.d/midi-box-ap.conf << EOF
# MIDI Box — keep NetworkManager away from the virtual AP interface
[keyfile]
unmanaged-devices=interface-name:${AP_IFACE}
EOF
systemctl reload NetworkManager 2>/dev/null || true

# --- Systemd service: create uap0 and assign static IP on every boot ---
echo "[3/6] Installing uap0 interface service..."
cat > /etc/systemd/system/midi-box-ap-iface.service << EOF
[Unit]
Description=MIDI Box — Create virtual AP interface (uap0)
Before=hostapd.service dnsmasq.service
After=sys-subsystem-net-devices-wlan0.device network.target

[Service]
Type=oneshot
RemainAfterExit=yes
# Delete stale uap0 if it exists from a previous boot (prevents "RTNETLINK: File exists")
ExecStartPre=-/sbin/ip link set ${AP_IFACE} down
ExecStartPre=-/sbin/iw dev ${AP_IFACE} del
# Create the virtual AP interface
ExecStart=/sbin/iw dev wlan0 interface add ${AP_IFACE} type __ap
# Bring it up and assign the static IP
ExecStartPost=/sbin/ip link set ${AP_IFACE} up
ExecStartPost=/sbin/ip addr add ${AP_IP}/24 dev ${AP_IFACE}
# Teardown
ExecStop=/sbin/ip link set ${AP_IFACE} down
ExecStop=/sbin/iw dev ${AP_IFACE} del

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable midi-box-ap-iface.service

# --- dnsmasq: DHCP for AP clients ---
echo "[4/6] Configuring dnsmasq..."
mv /etc/dnsmasq.conf /etc/dnsmasq.conf.bak 2>/dev/null || true
cat > /etc/dnsmasq.conf << EOF
# MIDI Box dnsmasq config
#
# IMPORTANT: use bind-dynamic instead of bind-interfaces!
# bind-interfaces requires the interface to exist at startup.  Since uap0 is a
# virtual AP created AFTER boot by midi-box-ap-iface.service, bind-interfaces
# silently falls back to binding ALL interfaces — which hijacks DNS on wlan0
# and breaks the home WiFi connection.  bind-dynamic watches for new interfaces
# and only attaches to the configured one when it appears.
interface=${AP_IFACE}
bind-dynamic
except-interface=wlan0
listen-address=${AP_IP}
dhcp-range=${DHCP_START},${DHCP_END},${NETMASK},24h

# Do NOT touch .local — it belongs to mDNS/Bonjour (Avahi + zeroconf)
# Without this, dnsmasq hijacks .local and breaks RTP-MIDI discovery
server=/local/
EOF

# --- hostapd: WiFi broadcast on uap0 ---
echo "[5/6] Configuring hostapd..."
cat > /etc/hostapd/hostapd.conf << EOF
interface=${AP_IFACE}
driver=nl80211
ssid=${AP_SSID}
hw_mode=g
channel=${AP_CHANNEL}
wmm_enabled=0
macaddr_acl=0
auth_algs=1
ignore_broadcast_ssid=0
wpa=2
wpa_passphrase=${AP_PASS}
wpa_key_mgmt=WPA-PSK
wpa_pairwise=TKIP
rsn_pairwise=CCMP
EOF

# Point hostapd to config file
if grep -q '#DAEMON_CONF=""' /etc/default/hostapd 2>/dev/null; then
  sed -i 's|#DAEMON_CONF=""|DAEMON_CONF="/etc/hostapd/hostapd.conf"|' /etc/default/hostapd
elif ! grep -q 'DAEMON_CONF=' /etc/default/hostapd 2>/dev/null; then
  echo 'DAEMON_CONF="/etc/hostapd/hostapd.conf"' >> /etc/default/hostapd
fi

# --- Configure Avahi for mDNS on the AP interface ---
echo "[6/7] Configuring Avahi (mDNS/Bonjour) for ${AP_IFACE}..."
mkdir -p /etc/avahi
if [ -f /etc/avahi/avahi-daemon.conf ]; then
  # Ensure Avahi allows uap0 and enables reflector so hotspot clients
  # can discover Bonjour services (RTP-MIDI)
  sed -i 's/^#*allow-interfaces=.*/allow-interfaces=wlan0,'"${AP_IFACE}"'/' /etc/avahi/avahi-daemon.conf
  if ! grep -q "allow-interfaces=" /etc/avahi/avahi-daemon.conf; then
    sed -i '/^\[server\]/a allow-interfaces=wlan0,'"${AP_IFACE}" /etc/avahi/avahi-daemon.conf
  fi
  # Enable reflector so mDNS works across wlan0 ↔ uap0
  sed -i 's/^#*enable-reflector=.*/enable-reflector=yes/' /etc/avahi/avahi-daemon.conf
  if ! grep -q "enable-reflector=" /etc/avahi/avahi-daemon.conf; then
    sed -i '/^\[reflector\]/a enable-reflector=yes' /etc/avahi/avahi-daemon.conf
  fi
fi
systemctl enable avahi-daemon

# --- Ensure dnsmasq and hostapd wait for uap0 to exist ---
# Use Wants (not Requires) — if the AP interface service fails for any reason
# (e.g. uap0 already exists from a previous attempt), Wants lets dnsmasq/hostapd
# still try to start. Requires would cascade-fail and kill the entire AP stack.
echo "[7/8] Ordering dnsmasq/hostapd after uap0 creation..."
mkdir -p /etc/systemd/system/dnsmasq.service.d
cat > /etc/systemd/system/dnsmasq.service.d/midi-box-after-ap.conf << EOF
[Unit]
After=midi-box-ap-iface.service
Wants=midi-box-ap-iface.service
EOF

mkdir -p /etc/systemd/system/hostapd.service.d
cat > /etc/systemd/system/hostapd.service.d/midi-box-after-ap.conf << EOF
[Unit]
After=midi-box-ap-iface.service
Wants=midi-box-ap-iface.service
EOF

# --- Enable services on boot ---
echo "[8/8] Enabling services..."
systemctl daemon-reload
systemctl unmask hostapd
systemctl enable hostapd
systemctl enable dnsmasq

echo ""
echo "======================================================"
echo "  Done! Reboot now:"
echo "    sudo reboot"
echo ""
echo "  After reboot:"
echo "  - wlan0  → home WiFi (SSH / internet)"
echo "  - ${AP_IFACE}   → MIDI-BOX hotspot @ ${AP_IP}"
echo "  - WiFi network : '${AP_SSID}'  password: ${AP_PASS}"
echo "  - Web UI       : http://${AP_IP}:8080"
echo "  - Or scan QR   : http://${AP_IP}:8080/display"
echo "======================================================"
