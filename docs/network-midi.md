# Network MIDI (RTP-MIDI) — MIDI Box Guide

## What Is Network MIDI?

RTP-MIDI (also called Apple MIDI or Network MIDI) lets you send and receive MIDI over a standard WiFi or Ethernet network using UDP. The MIDI Box Pi appears as a MIDI device on your local network — no USB cable needed.

**Protocol:** RFC 6295 over UDP ports 5004 and 5005
**Discovery:** Bonjour/mDNS (automatic) or manual IP entry
**Latency:** Typically 1–5 ms on a local WiFi network

---

## What MIDI Data Can Be Sent?

Everything in MIDI 1.0:

| Category | Messages |
|---|---|
| Notes | Note On, Note Off, Aftertouch (poly & channel) |
| Controllers | Control Change (CC 0–127), Pitch Bend |
| Program | Program Change, Bank Select |
| System | SysEx, Clock (0xF8), Start/Stop/Continue |
| Sync | MIDI Beat Clock (full transport sync) |

The MIDI Box routes all of this bidirectionally — what comes in via Network MIDI goes through the normal routing table to your hardware synths, and vice versa.

---

## Platform Setup

### macOS

1. Open **Audio MIDI Setup** (`/Applications/Utilities/Audio MIDI Setup.app`)
2. Go to **Window → MIDI Studio** (or press Cmd+2)
3. Double-click the **Network** icon
4. Under "My Sessions", click **+** to create a session (or use the existing one)
5. Under "Directory", you should see **MIDI Box** appear automatically via Bonjour
6. Select it and click **Connect**

The MIDI Box now appears as a MIDI device in any macOS app (Logic Pro, Ableton, GarageBand, etc.).

> **If MIDI Box does not appear automatically:** Click **+** under Directory, enter the Pi's IP address (shown in the Settings page) and port 5004.

> **Bonjour requirement:** Install `zeroconf` on the Pi (`pip install zeroconf`) for automatic discovery. Without it you must add the IP manually.

### iOS / iPadOS

1. Install a Core MIDI app that supports Network MIDI. Recommended free options:
   - **midimittr** (free, just for connecting)
   - **MIDI Network** (built into some DAW apps like Cubasis)
   - **AUM** — audio mixer with full Core MIDI support
2. In the app, open MIDI Network settings and select **MIDI Box** from the discovered sessions
3. The connection is now active for all Core MIDI apps on your device simultaneously

On iOS, once a Network MIDI session is established, every Core MIDI app (GarageBand, Cubasis, Moog Model D, etc.) can use it — you do not need to configure each app separately.

### Windows

Windows does not include native RTP-MIDI support. Install one of these free drivers:

- **rtpMIDI** by Tobias Erichsen (recommended): [tobias-erichsen.de/software/rtpmidi.html](https://www.tobias-erichsen.de/software/rtpmidi.html)

Setup:
1. Install rtpMIDI
2. Open the rtpMIDI control panel
3. Create a new session (name it anything, e.g. "MIDI Box")
4. Under "Remote", click **+** and enter the Pi's IP address, port 5004
5. Connect — MIDI Box now appears as a MIDI port in any Windows DAW (FL Studio, Ableton, Cubase, etc.)

---

## Using It With a DAW

Once connected, the MIDI Box appears as a standard MIDI port in your DAW:

- **Logic Pro**: Automatically discovers and uses Network MIDI sessions. Go to Logic → Preferences → MIDI → Inputs to enable it.
- **Ableton Live**: MIDI Box appears under Preferences → MIDI → Inputs/Outputs. Enable Track and Sync as needed.
- **GarageBand (iOS)**: Tap the settings icon in a project → Advanced → Bluetooth & Network MIDI → select MIDI Box.

The full routing table applies — you can route notes from a DAW track to any connected hardware synth (MS-20, Volcas, etc.) just like a USB MIDI device.

---

## Internet Tunneling — Using Your Setup Remotely

You can control your MIDI Box and send/receive MIDI from anywhere in the world with a VPN tunnel. The Pi stays at home; you connect from abroad.

### Option A: Tailscale (Recommended — Easiest)

[Tailscale](https://tailscale.com) creates a private mesh VPN with zero port-forwarding required. Free tier supports up to 100 devices.

**On the Pi:**
```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
```

**On your laptop/phone:** Install the Tailscale app and sign in to the same account.

Both devices now share a private `100.x.x.x` subnet. Use the Pi's Tailscale IP address in your DAW's Network MIDI settings — everything else works exactly the same as on a local network.

> **Latency:** Tailscale routes through the nearest relay if direct connection fails, typically adding 30–80 ms over the internet. MIDI notes are playable but tight sync (DAW recording) is unreliable over WAN — use it for live jamming, not quantized recording.

### Option B: WireGuard (Manual, Lower Overhead)

WireGuard is faster than Tailscale but requires a VPS (cloud server) as relay or direct port forwarding.

```bash
# On Pi
sudo apt install wireguard
# Generate keys and configure wg0.conf
# See: https://www.wireguard.com/quickstart/
```

Once the WireGuard tunnel is up, use the Pi's WireGuard IP in Network MIDI settings.

### Option C: SSH Tunnel (Quick & Dirty)

Forward UDP port 5004/5005 over SSH — works without any VPN software:

```bash
# On your laptop (requires socat on both ends)
ssh -R 5004:localhost:5004 pi@<your-pi-public-ip>
```

This is more complex for UDP (UDP doesn't tunnel over SSH directly — you need `socat` or a UDP-over-TCP wrapper). Tailscale is strongly recommended over this approach.

---

## Audio Streaming From the Pi

The Pi can capture audio from a USB audio interface and stream it to you over the network, so you can hear your hardware synths remotely.

### Option A: SonoBus (Recommended for Jamming)

[SonoBus](https://sonobus.net) — low-latency peer-to-peer audio over the internet. Free, open source.

```bash
# Install on Pi
sudo apt install sonobus   # or build from source
```

Run SonoBus on the Pi (headless via CLI) and on your laptop. Connect to the same room. You get ~20–50 ms latency on a good connection — good enough for playing along.

### Option B: Snapcast (Synchronized Multi-Room Streaming)

[Snapcast](https://github.com/badaix/snapcast) streams audio in perfect sync to multiple clients. Useful if you want to hear the Pi's audio on multiple devices at home.

```bash
sudo apt install snapserver snapclient
```

Connect Snapcast to the Pi's audio output (or JACK) and listen on any device with the Snapcast client app.

### Option C: Darkice + Icecast (Internet Radio Style)

Streams audio as an MP3/Ogg stream anyone can open in a browser or VLC. Higher latency (~5–10 s) but very robust.

```bash
sudo apt install darkice icecast2
```

Configure Darkice to read from ALSA, push to Icecast. Share the stream URL (e.g. `http://<pi-ip>:8000/stream`) and open in VLC.

### Option D: NetJACK2 / JACK over Network

For low-latency professional audio routing between two JACK-enabled machines on a LAN:

```bash
sudo apt install jackd2
jack_netsource -H <laptop-ip>
```

This gives sample-accurate audio sync but requires JACK on both ends and a fast LAN — not suitable over the internet.

---

## Summary: What Works Where

| Use Case | Recommendation |
|---|---|
| Local WiFi MIDI | RTP-MIDI built-in (no extra setup) |
| Remote MIDI over internet | Tailscale + RTP-MIDI |
| Live audio monitoring (local) | Snapcast or direct monitoring |
| Live jamming audio (internet) | SonoBus |
| Internet radio / share stream | Darkice + Icecast |
| DAW sync over internet | Not recommended (latency too variable) |
