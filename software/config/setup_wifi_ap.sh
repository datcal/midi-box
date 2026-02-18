#!/usr/bin/env bash
# =============================================================================
# MIDI Box — WiFi Access Point Setup (Dual-Interface)
# =============================================================================
# Creates a virtual AP interface (uap0) on top of wlan0 so the Pi can
# simultaneously:
#   - Connect to home WiFi via wlan0  (SSH / internet access)
#   - Broadcast MIDI-BOX hotspot via uap0  (standalone / web UI)
#
# Usage:
#   sudo bash config/setup_wifi_ap.sh
#   sudo reboot
# =============================================================================

set -e

AP_IFACE="uap0"          # virtual interface — wlan0 stays as home WiFi client
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

# --- Install packages ---
echo "[1/6] Installing hostapd and dnsmasq..."
apt-get update -qq
apt-get install -y hostapd dnsmasq

systemctl stop hostapd dnsmasq 2>/dev/null || true

# --- Systemd service: create uap0 on every boot ---
echo "[2/6] Installing uap0 interface service..."
cat > /etc/systemd/system/midi-box-ap-iface.service << EOF
[Unit]
Description=MIDI Box — Create virtual AP interface (uap0)
Before=hostapd.service dhcpcd.service
After=sys-subsystem-net-devices-wlan0.device

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/sbin/iw dev wlan0 interface add uap0 type __ap
ExecStop=/sbin/iw dev uap0 del
ExecStopPost=/bin/true

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable midi-box-ap-iface.service

# --- Clean up old wlan0 static IP block if present, add uap0 block ---
echo "[3/6] Configuring static IP on $AP_IFACE..."
# Remove any previous MIDI Box block (wlan0 or uap0)
if grep -q "# MIDI Box WiFi AP" /etc/dhcpcd.conf 2>/dev/null; then
  # Strip the old block out (from the comment line through the next blank line)
  sed -i '/# MIDI Box WiFi AP/,/^$/d' /etc/dhcpcd.conf
fi
cat >> /etc/dhcpcd.conf << EOF

# MIDI Box WiFi AP
interface ${AP_IFACE}
  static ip_address=${AP_IP}/24
  nohook wpa_supplicant
EOF

# --- dnsmasq: DHCP for AP clients ---
echo "[4/6] Configuring dnsmasq..."
mv /etc/dnsmasq.conf /etc/dnsmasq.conf.bak 2>/dev/null || true
cat > /etc/dnsmasq.conf << EOF
# MIDI Box dnsmasq config
interface=${AP_IFACE}
dhcp-range=${DHCP_START},${DHCP_END},${NETMASK},24h
domain=local
address=/midi-box.local/${AP_IP}
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

# Point hostapd to config
if grep -q '#DAEMON_CONF=""' /etc/default/hostapd 2>/dev/null; then
  sed -i 's|#DAEMON_CONF=""|DAEMON_CONF="/etc/hostapd/hostapd.conf"|' /etc/default/hostapd
elif ! grep -q 'DAEMON_CONF=' /etc/default/hostapd 2>/dev/null; then
  echo 'DAEMON_CONF="/etc/hostapd/hostapd.conf"' >> /etc/default/hostapd
fi

# --- Enable services on boot ---
echo "[6/6] Enabling services..."
systemctl unmask hostapd
systemctl enable hostapd
systemctl enable dnsmasq
# Ensure wpa_supplicant runs so wlan0 connects to home WiFi
systemctl enable wpa_supplicant 2>/dev/null || true

echo ""
echo "======================================================"
echo "  Done! Reboot now:"
echo "    sudo reboot"
echo ""
echo "  After reboot:"
echo "  - wlan0  → home WiFi (SSH / internet)"
echo "  - $AP_IFACE   → MIDI-BOX hotspot @ $AP_IP"
echo "  - WiFi network : '$AP_SSID'  password: $AP_PASS"
echo "  - Web UI       : http://${AP_IP}:8080"
echo "  - Or scan QR   : http://${AP_IP}:8080/display"
echo "======================================================"
