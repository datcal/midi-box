# MIDI Box — AI Design Prompt

Use the prompt below to generate a new frontend design for this project. Copy-paste it into your AI design tool (v0, Bolt, Lovable, ChatGPT, etc.) and iterate from there.

---

## The Prompt

```
Design a modern, dark-themed web UI for a hardware MIDI router/patchbay called "MIDI Box".
This runs on a Raspberry Pi 4 and is accessed from a phone or laptop over WiFi.
The UI controls MIDI routing between 10 connected instruments (6 USB + 4 hardware DIN).

The design must be a single-page application with a sidebar navigation and a main content area.
Use vanilla HTML + CSS + JS (no frameworks, no build step).
Monospace font family (SF Mono / Fira Code / Consolas fallback).
Dark theme only — this is used in dim studios and on stage.

─────────────────────────────────────────
LAYOUT
─────────────────────────────────────────

Two-column layout:
- LEFT: Fixed sidebar (220px desktop, collapses to 60px icon-only on mobile)
- RIGHT: Scrollable main content area with page-based views

SIDEBAR contains:
- "MIDI BOX" branding header with accent color
- Mode badge (STANDALONE / DAW) — small pill, uppercase
- Live status row: pulsing dot animation + clock label (INT/EXT) + BPM display
- Warning banner when external MIDI clock is lost (yellow/orange)
- Navigation menu (11 items, icons + labels):
  1. Dashboard
  2. Routing
  3. Launcher
  4. Presets
  5. Record
  6. Player
  7. MIDI Monitor
  8. Logs
  9. USB Share
  10. System
  11. Settings
- Footer: large red PANIC button (sends all-notes-off) + device count

─────────────────────────────────────────
COLOR SYSTEM
─────────────────────────────────────────

Use CSS custom properties. Suggested palette (feel free to improve):

  --bg-primary:     deep dark navy      (main background)
  --bg-secondary:   slightly lighter     (sidebar, secondary panels)
  --bg-card:        card surfaces        (elevated cards)
  --bg-hover:       hover/active states
  --text-primary:   light gray           (#e0e0e0 range)
  --text-secondary: medium gray          (labels, hints)
  --text-muted:     dim gray             (disabled, timestamps)
  --accent:         teal/cyan            (primary action color — buttons, links, active states)
  --danger:         red                  (destructive actions, recording indicator)
  --warning:        orange/amber         (queued states, alerts)
  --success:        green                (connected, playing, success)
  --midi-in:        blue                 (MIDI input direction)
  --midi-out:       orange               (MIDI output direction)
  --midi-routed:    purple               (routed messages)
  --border:         subtle dark blue     (card borders, dividers)

─────────────────────────────────────────
PAGE 1: DASHBOARD
─────────────────────────────────────────

Header row with stat chips: device count, route count, total MIDI messages.

Clock widget (2-column card grid):
  - Clock Source card: INT/EXT badge + dropdown to select source device
  - Tempo card: large BPM number input (50px+ font) with −/+ stepper buttons

Connected Devices section:
  - "Rescan Devices" button
  - Warning banner if unconfigured devices detected
  - Responsive grid of device cards (min 240px each), each showing:
    - Device name (bold)
    - Port type badge (USB / DIN)
    - Direction badge (IN / OUT / BOTH)
    - Device type (Controller / Synth / Sampler)
    - Activity indicator dots: blue dot for IN, orange dot for OUT (with glow animation when active)
    - Message count (IN: X / OUT: Y)
    - "Configure" button opening a modal

─────────────────────────────────────────
PAGE 2: ROUTING (Patchbay)
─────────────────────────────────────────

This is the most important and visually striking page.

Mode tabs at top: "Perform" (keyboards → synths only) vs "Advanced" (all devices both sides).
Exclusive mode toggle (pill switch): one source connects to only one destination at a time.

Two-column patchbay layout:
  - LEFT column: Source devices (MIDI senders) — clickable boxes
  - RIGHT column: Destination devices (MIDI receivers) — clickable boxes
  - SVG overlay layer draws bezier curve connection lines between connected pairs
    - Active route: accent/teal colored line with arrow marker
    - Disabled route: gray dashed line
    - Hover preview: green line (will connect) or red line (will disconnect)

Device boxes:
  - Default: card background, subtle border
  - Selected (source): accent border + glow + accent background tint
  - Connected (destination): green border + subtle green background
  - Hover to connect: green border preview
  - Hover to disconnect: red border preview
  - Shows route count badge
  - Shows inline "Filter / Ch" button for connected routes

Below patchbay: Active Routes List
  - Each row: Source → Destination, filter summary text, action buttons (Filter, Enable/Disable toggle, Remove)

─────────────────────────────────────────
PAGE 3: LAUNCHER (Clip Session View)
─────────────────────────────────────────

Inspired by Ableton Live's session view.

Clock bar at top:
  - Clock source selector (Internal / device names)
  - BPM ± buttons and input (disabled when synced to external clock)
  - Quantum selector dropdown (Beat, Bar, 2 Bars, 4 Bars)
  - Time signature selector (4/4, 3/4, 6/8)
  - Beat visualization: "BAR N" label + 4 beat dots (12px circles that light up on active beat, glow animation)
  - Transport: green START button, red STOP button

Layer grid (horizontal rows):
  - Each row = one layer with: layer name, destination device, MIDI channel override
  - Clip slots in columns: 80×56px buttons with rounded corners
    - Empty: dashed border, dim "+" icon
    - Stopped: solid border, clip name label
    - Queued: pulsing orange border + background, warning color
    - Playing: glowing teal border + background, accent color
    - Hover reveals: × remove button (top-right), ↓ start-point marker (bottom-left)

Scene row at bottom: column-wide play buttons to trigger all clips in a column simultaneously.

Controls: Add Layer button, Upload .mid button, Stop All button.

─────────────────────────────────────────
PAGE 4: PRESETS
─────────────────────────────────────────

Simple list/grid of saved routing presets.
  - Each preset: name, click to load
  - Active preset: accent left border + tinted background
  - "Save Current" button opens a save dialog (text input for name)

─────────────────────────────────────────
PAGE 5: RECORD (Quick Recorder)
─────────────────────────────────────────

Clock bar: BPM display (read-only), quantize selector (Free, 1/16, 1/8, 1/4, Bar, 2 Bars, 4 Bars), beat dots.

Transport card:
  - State badge that changes color per state:
    - IDLE (muted), COUNT IN (purple, blinking), ● REC (red, blinking), ▶ PLAYING (green), STOPPED (gray)
  - Elapsed time display
  - Auto-play toggle
  - Buttons: RECORD (red, large), Stop, Play, Clear
  - Stats: event count, loop duration

Live Note Feed (scrollable, monospace):
  - Real-time list of captured MIDI events
  - Columns: Time, Source, Note (green), Velocity, Channel
  - Auto-scrolls during recording

Save section: text input for filename + "Save as .mid" button.

Saved recordings list: rows with name, duration, event count, Play/Download/Delete buttons.

─────────────────────────────────────────
PAGE 6: MIDI MONITOR
─────────────────────────────────────────

Controls: Pause/Resume, Clear, filter checkboxes (hide Clock, hide Active Sensing), message count.

Table with sticky header, 8 columns:
  - Time (HH:MM:SS.mmm)
  - Direction (color-coded: IN=blue, OUT=orange, ROUTED=purple)
  - Source device
  - Destination device
  - Message type (color-coded: NOTE=green, CC=orange, CLOCK=muted)
  - Channel
  - Data (velocity, CC value, etc.)
  - Raw hex bytes

Fast-scrolling, 500 message ring buffer. New messages appear at top.

─────────────────────────────────────────
PAGE 7: PLAYER (MIDI File Playback)
─────────────────────────────────────────

Clock bar: BPM ± and input, destination selector, loop toggle (pill switch), status badge, stop button.

Upload zone:
  - Large dashed-border drop area
  - Icon + "Drop .mid files here or tap to browse"
  - Progress bar overlay during upload

File browser:
  - Breadcrumb navigation for folders
  - Create Folder button
  - File list: folders (icon + name + item count), files (play button + name + duration + tracks)
  - Currently playing file highlighted with accent left border

─────────────────────────────────────────
PAGE 8: LOGS
─────────────────────────────────────────

Simple log viewer card.
  - Clear button
  - Scrollable monospace log area
  - Each entry: timestamp, log level (color-coded: INFO=blue, WARNING=orange, ERROR=red), logger, message

─────────────────────────────────────────
PAGE 9: SYSTEM
─────────────────────────────────────────

Stat cards (3-column grid):
  - CPU: percentage + animated progress bar
  - RAM: percentage + animated progress bar (color changes orange→red at thresholds)
  - Disk: percentage + animated progress bar

Info cards (3-column grid):
  - Temperature (°C)
  - Uptime (formatted)
  - Platform (Raspberry Pi / macOS)

Service control:
  - Status badge (RUNNING = green)
  - Red "Restart Service" button
  - Reconnection status during restart

─────────────────────────────────────────
PAGE 10: SETTINGS
─────────────────────────────────────────

Sections:
  1. Performance Mode toggle
  2. Network MIDI (RTP-MIDI): status badge, session list, rescan button
  3. Software Update: current version, latest version, check/install buttons, update log
  4. WiFi: two QR codes (WiFi join + URL), credentials display, change WiFi form (SSID + password)
  5. Export/Import: download state JSON, upload state JSON
  6. Reset to Defaults (red danger button)

─────────────────────────────────────────
PAGE 11: USB SHARE
─────────────────────────────────────────

  - VirtualHere server status badge + start/stop buttons
  - Warning banner when active (devices pause MIDI routing)
  - Connection instructions with numbered steps
  - Install section with setup button + log output
  - Server log viewer

─────────────────────────────────────────
SHARED COMPONENTS
─────────────────────────────────────────

Cards:
  - Background: card surface color, 1px border, 8px radius, subtle shadow
  - Card header: flex row, space-between, bold title + action buttons

Buttons:
  - Default: subtle border, transparent background, hover highlights
  - Accent: teal/cyan filled, white text
  - Danger: red-tinted background, red border, red text, fills red on hover
  - Small variant for inline actions

Badges/Pills:
  - Small uppercase labels with colored background tint + matching text + thin border
  - Used for: mode (STANDALONE), status (RUNNING), direction (IN/OUT), port type (USB/DIN)

Form inputs:
  - Dark background, subtle border, rounded corners
  - Select dropdowns styled consistently
  - Number inputs with stepper buttons where relevant

Modals:
  - Centered overlay with dark semi-transparent backdrop
  - Card-style modal box (400-500px width)
  - Form rows with labels

Info popovers:
  - Triggered by small circular "ⓘ" buttons
  - Two-section content: "Musician" (friendly) and "Developer" (technical)
  - Positioned within viewport, close on outside click

Toggle switches:
  - Pill-shaped toggle (34×19px track with sliding circle)
  - Off: gray track, On: accent colored track

─────────────────────────────────────────
RESPONSIVE DESIGN
─────────────────────────────────────────

Breakpoints:
  - Desktop (>768px): full sidebar, multi-column grids
  - Tablet/Mobile (≤768px): sidebar collapses to 60px icon-only, grids become single column, patchbay SVG lines hidden

Touch optimization (@media pointer: coarse):
  - Larger buttons (44px+ tap targets)
  - Increased padding on inputs and interactive elements
  - Larger beat dots (16px), clip slots (100px wide, 68px tall)
  - Bigger font sizes for BPM inputs and controls

─────────────────────────────────────────
ANIMATIONS
─────────────────────────────────────────

  - Live pulse: sidebar status dot pulses with scale + opacity (1.5s infinite)
  - Activity glow: device IN/OUT dots glow when receiving MIDI data
  - Clip queued: pulsing border animation (0.8s)
  - Recording blink: red badge blinks during recording (1s), faster during count-in (0.6s)
  - Progress bars: smooth width transitions (0.4s ease)
  - Beat dots: light up sequentially on each beat with subtle glow

─────────────────────────────────────────
DESIGN GOALS
─────────────────────────────────────────

  - Professional music production aesthetic — think Ableton Live, Native Instruments, or DAW plugin UIs
  - High contrast for readability in dark environments (studios, stages)
  - Information-dense but not cluttered — every pixel should serve a purpose
  - The routing patchbay should feel tactile and visual — it's the hero page
  - Real-time feel: activity dots, beat visualization, and state badges should feel alive
  - Touch-friendly: used on phone and Raspberry Pi 5" touchscreen
  - No external dependencies: no CDN fonts, no icon libraries, no CSS frameworks
  - Unicode characters for icons (or inline SVG)

─────────────────────────────────────────
TECHNICAL CONSTRAINTS
─────────────────────────────────────────

  - Output: single HTML file with embedded <style> and <script>, OR separate .html + .css + .js files
  - No build step, no npm, no framework — vanilla only
  - All pages are <div> sections toggled by JS (SPA, hash-based routing)
  - CSS custom properties for theming
  - Must work on: Chrome (desktop + Android), Safari (iOS), Chromium (Pi kiosk)
```

---

## How to Use This Prompt

1. **Copy** everything inside the code fence above
2. **Paste** into your AI design tool (v0.dev, Bolt.new, Lovable, ChatGPT Canvas, etc.)
3. **Iterate** — ask the AI to focus on specific pages ("now redesign just the routing patchbay")
4. **Extract** the HTML/CSS/JS and drop it into `software/web_ui/`

## Tips for Good Results

- Start with one page at a time rather than all 11 at once
- Ask for the **Routing patchbay** first — it's the most complex and visually important
- Then **Dashboard** + **Launcher** — the other two hero pages
- Ask for **just the CSS** if you want to keep the existing HTML structure
- Tell the AI which specific element you want changed ("make the sidebar more minimal", "redesign the device cards")
