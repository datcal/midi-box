#!/usr/bin/env bash
# =============================================================================
# MIDI Box — WiFi Access Point Setup
# =============================================================================
# Run ONCE on the Raspberry Pi to turn wlan0 into a dedicated hotspot.
# After running, reboot. The Pi will broadcast "MIDI-BOX" and serve the
# web UI at http://192.168.4.1:8080
#
# Usage:
#   sudo bash config/setup_wifi_ap.sh
#   sudo reboot
# =============================================================================

set -e

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
echo "  MIDI Box — WiFi AP Setup"
echo "  SSID   : $AP_SSID"
echo "  Pass   : $AP_PASS"
echo "  Pi IP  : $AP_IP"
echo "======================================================"

# --- Install packages ---
echo "[1/5] Installing hostapd and dnsmasq..."
apt-get update -qq
apt-get install -y hostapd dnsmasq

systemctl stop hostapd dnsmasq 2>/dev/null || true

# --- Static IP for wlan0 ---
echo "[2/5] Configuring static IP on wlan0..."
cat >> /etc/dhcpcd.conf << EOF

# MIDI Box WiFi AP
interface wlan0
  static ip_address=${AP_IP}/24
  nohook wpa_supplicant
EOF

# --- dnsmasq: DHCP for connected clients ---
echo "[3/5] Configuring dnsmasq..."
mv /etc/dnsmasq.conf /etc/dnsmasq.conf.bak 2>/dev/null || true
cat > /etc/dnsmasq.conf << EOF
# MIDI Box dnsmasq config
interface=wlan0
dhcp-range=${DHCP_START},${DHCP_END},${NETMASK},24h
domain=local
address=/midi-box.local/${AP_IP}
EOF

# --- hostapd: WiFi broadcast ---
echo "[4/5] Configuring hostapd..."
cat > /etc/hostapd/hostapd.conf << EOF
interface=wlan0
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
sed -i 's|#DAEMON_CONF=""|DAEMON_CONF="/etc/hostapd/hostapd.conf"|' \
    /etc/default/hostapd 2>/dev/null || \
echo 'DAEMON_CONF="/etc/hostapd/hostapd.conf"' >> /etc/default/hostapd

# --- Enable services on boot ---
echo "[5/5] Enabling services..."
systemctl unmask hostapd
systemctl enable hostapd
systemctl enable dnsmasq

echo ""
echo "======================================================"
echo "  Done! Reboot now:"
echo "    sudo reboot"
echo ""
echo "  After reboot:"
echo "  - WiFi network '$AP_SSID' will be visible"
echo "  - Password: $AP_PASS"
echo "  - Web UI: http://${AP_IP}:8080"
echo "  - Or scan the QR code at: http://${AP_IP}:8080/display"
echo "======================================================"
