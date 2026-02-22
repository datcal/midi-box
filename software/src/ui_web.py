"""
Web UI - Flask server for MIDI Box.

Runs as a separate process from the MIDI routing engine.
All state is read from the IPC shared dict; all mutations go through
the command queue so the MIDI process handles them atomically.

Pages:
  /              - Dashboard (device status, activity)
  /routing       - Routing matrix (create/edit/delete routes)
  /presets       - Preset management (load/save/create)
  /monitor       - Live MIDI message monitor
  /settings      - Configuration
  /logs          - Application logs

API:
  /api/devices   - List connected devices
  /api/routes    - CRUD routes
  /api/presets   - CRUD presets
  /api/monitor   - MIDI message log
  /api/settings  - Read/write config
  /api/logs      - Application log stream
"""

import io
import json
import time
import logging
import threading
from pathlib import Path

from flask import Flask, render_template, jsonify, request, Response, send_file

logger = logging.getLogger("midi-box.web")

# IPC bridge reference — set by run_flask_process()
_bridge = None


def run_flask_process(bridge, host: str, port: int):
    """Entry point for the Flask subprocess."""
    global _bridge
    _bridge = bridge

    # Silence Flask/Werkzeug request logging to keep output clean
    log = logging.getLogger("werkzeug")
    log.setLevel(logging.ERROR)

    app = create_app(bridge)
    app.run(
        host=host,
        port=port,
        debug=False,
        use_reloader=False,
        threaded=True,      # each HTTP request gets its own thread
    )


def create_app(bridge):
    """Create the Flask application backed by an IpcBridge."""

    app = Flask(
        __name__,
        template_folder=str(Path(__file__).resolve().parent.parent / "web_ui" / "templates"),
        static_folder=str(Path(__file__).resolve().parent.parent / "web_ui" / "static"),
    )
    app.config["SECRET_KEY"] = "midi-box-dev"

    import updater as _updater
    _updater.start_background_checker()

    def _state():
        """Return a snapshot of the shared state dict."""
        return bridge.state

    def _cmd(action: str, params: dict = None) -> dict:
        """Send a command to the MIDI process and return the result."""
        return bridge.send_command(action, params)

    # ---------------------------------------------------------------
    # Pages
    # ---------------------------------------------------------------

    @app.route("/")
    def dashboard():
        return render_template("index.html", page="dashboard")

    @app.route("/routing")
    def routing():
        return render_template("index.html", page="routing")

    @app.route("/presets")
    def presets():
        return render_template("index.html", page="presets")

    @app.route("/monitor")
    def monitor():
        return render_template("index.html", page="monitor")

    @app.route("/settings")
    def settings():
        return render_template("index.html", page="settings")

    @app.route("/logs")
    def logs_page():
        return render_template("index.html", page="logs")

    @app.route("/display")
    def display_page():
        return render_template("display.html")

    # ---------------------------------------------------------------
    # API: Network / WiFi AP info
    # ---------------------------------------------------------------

    @app.route("/api/network")
    def api_network():
        cfg = _state().get("wifi_config", {})
        ip   = cfg.get("ip", "192.168.4.1")
        port = cfg.get("port", 8080)
        return jsonify({
            "ssid":     cfg.get("ssid", "MIDI-BOX"),
            "password": cfg.get("password", "midibox123"),
            "ip":       ip,
            "port":     port,
            "url":      f"http://{ip}:{port}",
        })

    @app.route("/api/network", methods=["POST"])
    def api_network_update():
        import subprocess
        import threading
        import yaml

        data = request.json or {}
        ssid     = str(data.get("ssid", "")).strip()
        password = str(data.get("password", "")).strip()

        if not ssid or len(ssid) > 32:
            return jsonify({"ok": False, "error": "SSID must be 1–32 characters"}), 400
        if len(password) < 8 or len(password) > 63:
            return jsonify({"ok": False, "error": "Password must be 8–63 characters"}), 400

        # 1. Persist to midi_box.yaml
        config_path = Path(__file__).resolve().parent.parent / "config" / "midi_box.yaml"
        try:
            with open(config_path) as f:
                cfg = yaml.safe_load(f) or {}
            cfg.setdefault("wifi_ap", {})
            cfg["wifi_ap"]["ssid"]     = ssid
            cfg["wifi_ap"]["password"] = password
            with open(config_path, "w") as f:
                yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True)
        except Exception as e:
            return jsonify({"ok": False, "error": f"Could not save config: {e}"}), 500

        # 2. Update shared state so QR codes and display refresh immediately
        wifi = dict(bridge.state.get("wifi_config", {}))
        wifi["ssid"]     = ssid
        wifi["password"] = password
        bridge.state["wifi_config"] = wifi

        # 3. Build and apply the new hostapd config.
        # Write the full config from our values — avoids needing read access to
        # the existing file (which is root-only). Requires sudoers entry written
        # by pi_setup.sh:
        #   <user> ALL=(ALL) NOPASSWD: /usr/bin/tee /etc/hostapd/hostapd.conf
        #   <user> ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart hostapd
        channel = cfg.get("wifi_ap", {}).get("channel", 6)
        hostapd_conf_content = (
            f"interface=uap0\n"
            f"driver=nl80211\n"
            f"ssid={ssid}\n"
            f"hw_mode=g\n"
            f"channel={channel}\n"
            f"wmm_enabled=0\n"
            f"macaddr_acl=0\n"
            f"auth_algs=1\n"
            f"ignore_broadcast_ssid=0\n"
            f"wpa=2\n"
            f"wpa_passphrase={password}\n"
            f"wpa_key_mgmt=WPA-PSK\n"
            f"wpa_pairwise=TKIP\n"
            f"rsn_pairwise=CCMP\n"
        )

        live = False
        try:
            proc = subprocess.run(
                ["sudo", "/usr/bin/tee", "/etc/hostapd/hostapd.conf"],
                input=hostapd_conf_content.encode(),
                capture_output=True,
                timeout=5,
            )
            live = proc.returncode == 0
        except Exception:
            pass

        if live:
            # Restart hostapd in a background thread so the HTTP response
            # reaches the browser before the AP drops the connection.
            def _restart():
                time.sleep(2)
                try:
                    subprocess.run(
                        ["sudo", "/usr/bin/systemctl", "restart", "hostapd"],
                        timeout=15,
                    )
                except Exception:
                    pass
            threading.Thread(target=_restart, daemon=True).start()

        return jsonify({"ok": True, "live": live})

    @app.route("/api/qr/<qr_type>.svg")
    def api_qr(qr_type):
        cfg  = _state().get("wifi_config", {})
        ip   = cfg.get("ip", "192.168.4.1")
        port = cfg.get("port", 8080)

        if qr_type == "wifi":
            data = (
                f"WIFI:T:WPA;S:{cfg.get('ssid','MIDI-BOX')};"
                f"P:{cfg.get('password','midibox123')};;"
            )
        elif qr_type == "url":
            data = f"http://{ip}:{port}"
        else:
            return jsonify({"error": "unknown type"}), 404

        return _make_qr_svg(data)

    # ---------------------------------------------------------------
    # API: Devices
    # ---------------------------------------------------------------

    @app.route("/api/devices")
    def api_devices():
        st = _state()
        return jsonify({
            "devices": list(st.get("devices", [])),
            "mode": st.get("mode", "standalone"),
        })

    @app.route("/api/devices/<name>/config", methods=["POST"])
    def api_device_config(name):
        data = request.json
        result = _cmd("device.config", {
            "name": name,
            "direction": data.get("direction"),
            "device_type": data.get("device_type"),
            "midi_channel": data.get("midi_channel"),
        })
        if not result.get("ok"):
            return jsonify({"ok": False, "error": result.get("error", "Device not found")}), 404
        return jsonify({"ok": True})

    # ---------------------------------------------------------------
    # API: Routes
    # ---------------------------------------------------------------

    @app.route("/api/routes")
    def api_routes_list():
        return jsonify({"routes": list(_state().get("routes", []))})

    @app.route("/api/routes", methods=["POST"])
    def api_routes_add():
        data = request.json
        result = _cmd("route.add", {
            "from": data["from"],
            "to": data["to"],
            "filter": data.get("filter", {}),
            "name": data.get("name", ""),
        })
        return jsonify({"ok": result.get("ok", False), "route": result.get("route", "")})

    @app.route("/api/routes", methods=["DELETE"])
    def api_routes_remove():
        data = request.json
        result = _cmd("route.remove", {"from": data["from"], "to": data["to"]})
        return jsonify({"ok": result.get("ok", False)})

    @app.route("/api/routes/clear", methods=["POST"])
    def api_routes_clear():
        result = _cmd("route.clear")
        return jsonify({"ok": result.get("ok", False)})

    @app.route("/api/routes/toggle", methods=["POST"])
    def api_routes_toggle():
        data = request.json
        result = _cmd("route.toggle", {"from": data["from"], "to": data["to"]})
        if not result.get("ok"):
            return jsonify({"ok": False}), 404
        return jsonify({"ok": True, "enabled": result.get("enabled", False)})

    # ---------------------------------------------------------------
    # API: Presets
    # ---------------------------------------------------------------

    @app.route("/api/presets")
    def api_presets_list():
        st = _state()
        return jsonify({
            "presets": list(st.get("presets", [])),
            "current": st.get("current_preset", "default"),
        })

    @app.route("/api/presets/<name>")
    def api_preset_get(name):
        # Preset file contents are managed by the MIDI process; we load via command.
        # Use a lightweight approach: ask for the raw preset data.
        from preset_manager import PresetManager
        pm = PresetManager()
        data = pm.load(name)
        if data:
            return jsonify(data)
        return jsonify({"error": "not found"}), 404

    @app.route("/api/presets/<name>/load", methods=["POST"])
    def api_preset_load(name):
        result = _cmd("preset.load", {"name": name})
        if result.get("error") == "not found":
            return jsonify({"error": "not found"}), 404
        return jsonify(result)

    @app.route("/api/presets/save", methods=["POST"])
    def api_preset_save():
        data = request.json
        result = _cmd("preset.save", {
            "name": data.get("name", "custom"),
            "display_name": data.get("display_name", data.get("name", "custom")),
            "description": data.get("description", ""),
            "clock_source": data.get("clock_source"),
        })
        return jsonify(result)

    @app.route("/api/presets/<name>", methods=["DELETE"])
    def api_preset_delete(name):
        result = _cmd("preset.delete", {"name": name})
        return jsonify(result)

    # ---------------------------------------------------------------
    # API: MIDI Monitor
    # ---------------------------------------------------------------

    @app.route("/api/monitor")
    def api_monitor():
        limit  = request.args.get("limit", 100, type=int)
        offset = request.args.get("offset", 0, type=int)
        st = _state()
        entries = list(st.get("midi_log", []))
        # Apply offset/limit (state already stores most-recent-first)
        sliced = entries[offset:offset + limit]
        return jsonify({
            "entries": sliced,
            "stats": dict(st.get("midi_stats", {})),
            "paused": st.get("midi_paused", False),
        })

    @app.route("/api/monitor/clear", methods=["POST"])
    def api_monitor_clear():
        return jsonify(_cmd("monitor.clear"))

    @app.route("/api/monitor/pause", methods=["POST"])
    def api_monitor_pause():
        return jsonify(_cmd("monitor.pause"))

    @app.route("/api/monitor/resume", methods=["POST"])
    def api_monitor_resume():
        return jsonify(_cmd("monitor.resume"))

    @app.route("/api/performance/enable", methods=["POST"])
    def api_performance_enable():
        return jsonify(_cmd("performance.enable"))

    @app.route("/api/performance/disable", methods=["POST"])
    def api_performance_disable():
        return jsonify(_cmd("performance.disable"))

    # ---------------------------------------------------------------
    # API: Settings
    # ---------------------------------------------------------------

    @app.route("/api/settings")
    def api_settings():
        st = _state()
        routes = list(st.get("routes", []))
        devices = list(st.get("devices", []))
        return jsonify({
            "mode": st.get("mode", "standalone"),
            "platform": st.get("platform", "unknown"),
            "preset": st.get("current_preset", "default"),
            "total_routes": len(routes),
            "total_devices": len(devices),
            "clock_source": st.get("clock_source"),
            "performance_mode": st.get("performance_mode", False),
        })

    @app.route("/api/settings/clock", methods=["POST"])
    def api_settings_clock():
        data = request.json
        return jsonify(_cmd("settings.clock", {"source": data.get("source")}))

    @app.route("/api/settings/rescan", methods=["POST"])
    def api_settings_rescan():
        result = _cmd("device.rescan")
        logger.info(f"Rescan complete: {len(result.get('devices', []))} devices")
        return jsonify(result)

    # ---------------------------------------------------------------
    # API: Clip Launcher
    # ---------------------------------------------------------------

    @app.route("/api/launcher")
    def api_launcher_status():
        return jsonify(dict(_state().get("launcher", {})))

    @app.route("/api/launcher/poll")
    def api_launcher_poll():
        return jsonify(dict(_state().get("launcher_poll", {})))

    @app.route("/api/launcher/clock", methods=["POST"])
    def api_launcher_clock():
        data = request.json
        return jsonify(_cmd("launcher.clock", data))

    @app.route("/api/launcher/transport/start", methods=["POST"])
    def api_launcher_start():
        return jsonify(_cmd("launcher.start"))

    @app.route("/api/launcher/transport/stop", methods=["POST"])
    def api_launcher_stop_transport():
        return jsonify(_cmd("launcher.stop"))

    @app.route("/api/launcher/layers", methods=["POST"])
    def api_launcher_add_layer():
        data = request.json
        return jsonify(_cmd("launcher.add_layer", {
            "name": data.get("name", ""),
            "destination": data.get("destination", ""),
            "midi_channel": data.get("midi_channel"),
        }))

    @app.route("/api/launcher/layers/<int:layer_id>", methods=["DELETE"])
    def api_launcher_remove_layer(layer_id):
        return jsonify(_cmd("launcher.remove_layer", {"layer_id": layer_id}))

    @app.route("/api/launcher/layers/<int:layer_id>", methods=["PATCH"])
    def api_launcher_update_layer(layer_id):
        data = request.json
        return jsonify(_cmd("launcher.update_layer", {
            "layer_id": layer_id,
            "name": data.get("name"),
            "destination": data.get("destination"),
            "midi_channel": data.get("midi_channel"),
        }))

    @app.route("/api/launcher/layers/<int:layer_id>/clips/<int:slot>", methods=["POST"])
    def api_launcher_assign_clip(layer_id, slot):
        data = request.json
        return jsonify(_cmd("launcher.assign_clip", {
            "layer_id": layer_id,
            "slot": slot,
            "filename": data.get("filename", ""),
            "name": data.get("name", ""),
            "loop": data.get("loop", True),
        }))

    @app.route("/api/launcher/layers/<int:layer_id>/clips/<int:slot>", methods=["DELETE"])
    def api_launcher_remove_clip(layer_id, slot):
        return jsonify(_cmd("launcher.remove_clip", {"layer_id": layer_id, "slot": slot}))

    @app.route("/api/launcher/layers/<int:layer_id>/clips/<int:slot>/launch", methods=["POST"])
    def api_launcher_launch_clip(layer_id, slot):
        return jsonify(_cmd("launcher.launch_clip", {"layer_id": layer_id, "slot": slot}))

    @app.route("/api/launcher/layers/<int:layer_id>/stop", methods=["POST"])
    def api_launcher_stop_layer(layer_id):
        return jsonify(_cmd("launcher.stop_layer", {"layer_id": layer_id}))

    @app.route("/api/launcher/stop_all", methods=["POST"])
    def api_launcher_stop_all():
        return jsonify(_cmd("launcher.stop_all"))

    @app.route("/api/launcher/upload", methods=["POST"])
    def api_launcher_upload():
        file = request.files.get("file")
        if not file or not file.filename:
            return jsonify({"ok": False, "error": "No file"}), 400
        return jsonify(_cmd("launcher.upload", {
            "filename": file.filename,
            "data": file.read(),
        }))

    @app.route("/api/launcher/files/delete", methods=["POST"])
    def api_launcher_delete_file():
        data = request.json
        return jsonify(_cmd("launcher.delete_file", {"file": data.get("file", "")}))

    # ---------------------------------------------------------------
    # API: MIDI Player
    # ---------------------------------------------------------------

    @app.route("/api/player")
    def api_player_status():
        return jsonify(dict(_state().get("player", {"status": {}, "files": []})))

    @app.route("/api/player/upload", methods=["POST"])
    def api_player_upload():
        file = request.files.get("file")
        if not file or not file.filename:
            return jsonify({"ok": False, "error": "No file"}), 400
        return jsonify(_cmd("player.upload", {
            "filename": file.filename,
            "data": file.read(),
        }))

    @app.route("/api/player/play", methods=["POST"])
    def api_player_play():
        data = request.json
        filename = data.get("file")
        destination = data.get("destination")
        if not filename or not destination:
            return jsonify({"ok": False, "error": "file and destination required"}), 400
        return jsonify(_cmd("player.play", {
            "file": filename,
            "destination": destination,
            "loop": data.get("loop", False),
            "tempo": data.get("tempo", 1.0),
        }))

    @app.route("/api/player/stop", methods=["POST"])
    def api_player_stop():
        return jsonify(_cmd("player.stop"))

    @app.route("/api/player/pause", methods=["POST"])
    def api_player_pause():
        return jsonify(_cmd("player.pause"))

    @app.route("/api/player/resume", methods=["POST"])
    def api_player_resume():
        return jsonify(_cmd("player.resume"))

    @app.route("/api/player/loop", methods=["POST"])
    def api_player_loop():
        data = request.json
        return jsonify(_cmd("player.set_loop", {"loop": data.get("loop", False)}))

    @app.route("/api/player/tempo", methods=["POST"])
    def api_player_tempo():
        data = request.json
        return jsonify(_cmd("player.set_tempo", {"tempo": data.get("tempo", 1.0)}))

    @app.route("/api/player/delete", methods=["POST"])
    def api_player_delete():
        data = request.json
        return jsonify(_cmd("player.delete", {"file": data.get("file", "")}))

    # ---------------------------------------------------------------
    # API: Application Logs
    # ---------------------------------------------------------------

    @app.route("/api/logs")
    def api_logs():
        limit = request.args.get("limit", 200, type=int)
        entries = list(_state().get("log_entries", []))[:limit]
        return jsonify({"entries": entries})

    @app.route("/api/logs/clear", methods=["POST"])
    def api_logs_clear():
        return jsonify(_cmd("logs.clear"))

    # ---------------------------------------------------------------
    # API: Polling endpoint for real-time updates
    # ---------------------------------------------------------------

    @app.route("/api/poll")
    def api_poll():
        """Lightweight endpoint for UI polling — returns activity + stats."""
        st = _state()
        return jsonify({
            "devices": list(st.get("activity", [])),
            "mode": st.get("mode", "standalone"),
            "preset": st.get("current_preset", "default"),
        })

    # ---------------------------------------------------------------
    # API: Export / Import
    # ---------------------------------------------------------------

    @app.route("/api/export")
    def api_export():
        """Export full state as downloadable JSON file."""
        result = _cmd("state.export")
        data = result.get("data", {})
        return Response(
            json.dumps(data, indent=2),
            mimetype="application/json",
            headers={"Content-Disposition": "attachment; filename=midi-box-export.json"},
        )

    @app.route("/api/import", methods=["POST"])
    def api_import():
        """Import state from uploaded JSON."""
        if request.content_type and "multipart" in request.content_type:
            file = request.files.get("file")
            if not file:
                return jsonify({"ok": False, "error": "No file uploaded"}), 400
            try:
                data = json.load(file)
            except json.JSONDecodeError:
                return jsonify({"ok": False, "error": "Invalid JSON file"}), 400
        else:
            data = request.json
            if not data:
                return jsonify({"ok": False, "error": "No data provided"}), 400

        result = _cmd("state.import", {"data": data})
        if result.get("ok"):
            return jsonify(result)
        return jsonify({"ok": False, "error": "Import failed"}), 400

    @app.route("/api/state/reset", methods=["POST"])
    def api_state_reset():
        return jsonify(_cmd("state.reset"))

    # ---------------------------------------------------------------
    # API: System stats + service restart
    # ---------------------------------------------------------------

    @app.route("/api/system")
    def api_system():
        st = _state()
        stats = {
            "cpu_percent": 0, "ram_used_mb": 0, "ram_total_mb": 0, "ram_percent": 0,
            "disk_used_gb": 0.0, "disk_total_gb": 0.0, "disk_percent": 0,
            "cpu_temp_c": None, "uptime_seconds": 0,
            "platform": st.get("platform", "unknown"),
        }
        try:
            import psutil
            cpu = psutil.cpu_percent(interval=0.1)
            mem = psutil.virtual_memory()
            disk = psutil.disk_usage("/")
            stats.update({
                "cpu_percent":  round(cpu, 1),
                "ram_used_mb":  mem.used  // (1024 * 1024),
                "ram_total_mb": mem.total // (1024 * 1024),
                "ram_percent":  round(mem.percent, 1),
                "disk_used_gb":  round(disk.used  / 1024**3, 1),
                "disk_total_gb": round(disk.total / 1024**3, 1),
                "disk_percent":  round(disk.percent, 1),
                "uptime_seconds": int(time.time() - psutil.boot_time()),
            })
        except ImportError:
            try:
                import shutil
                total, used, _ = shutil.disk_usage("/")
                stats["disk_used_gb"]  = round(used  / 1024**3, 1)
                stats["disk_total_gb"] = round(total / 1024**3, 1)
                stats["disk_percent"]  = round(used / total * 100, 1)
            except Exception:
                pass
            try:
                with open("/proc/meminfo") as f:
                    m = {p[0].rstrip(":"): int(p[1])
                         for line in f for p in [line.split()] if len(p) >= 2}
                total_kb = m.get("MemTotal", 0)
                used_kb  = total_kb - m.get("MemAvailable", 0)
                stats["ram_total_mb"] = total_kb // 1024
                stats["ram_used_mb"]  = used_kb  // 1024
                stats["ram_percent"]  = round(used_kb / total_kb * 100, 1) if total_kb else 0
            except Exception:
                pass
            try:
                with open("/proc/uptime") as f:
                    stats["uptime_seconds"] = int(float(f.read().split()[0]))
            except Exception:
                pass

        # CPU temperature (Raspberry Pi thermal sensor)
        for tp in ["/sys/class/thermal/thermal_zone0/temp",
                   "/sys/devices/virtual/thermal/thermal_zone0/temp"]:
            try:
                with open(tp) as f:
                    stats["cpu_temp_c"] = round(int(f.read().strip()) / 1000, 1)
                break
            except Exception:
                pass

        return jsonify(stats)

    @app.route("/api/panic", methods=["POST"])
    def api_panic():
        """Send All Notes Off + All Sound Off to every output device."""
        return jsonify(_cmd("midi.panic"))

    # ---------------------------------------------------------------
    # API: MIDI Looper
    # ---------------------------------------------------------------

    @app.route("/api/rtpmidi")
    def api_rtpmidi_status():
        return jsonify(dict(_state().get("rtp_midi", {"enabled": False, "sessions": []})))

    @app.route("/api/looper")
    def api_looper_status():
        return jsonify(dict(_state().get("looper", {"slots": []})))

    @app.route("/api/looper/<int:slot_id>/configure", methods=["POST"])
    def api_looper_configure(slot_id):
        data = request.json or {}
        return jsonify(_cmd("looper.configure", {
            "slot_id":     slot_id,
            "source":      data.get("source", ""),
            "destination": data.get("destination", ""),
            "midi_channel": data.get("midi_channel"),
        }))

    @app.route("/api/looper/<int:slot_id>/record", methods=["POST"])
    def api_looper_record(slot_id):
        return jsonify(_cmd("looper.record", {"slot_id": slot_id}))

    @app.route("/api/looper/<int:slot_id>/play", methods=["POST"])
    def api_looper_play(slot_id):
        return jsonify(_cmd("looper.play", {"slot_id": slot_id}))

    @app.route("/api/looper/<int:slot_id>/stop", methods=["POST"])
    def api_looper_stop(slot_id):
        return jsonify(_cmd("looper.stop", {"slot_id": slot_id}))

    @app.route("/api/looper/<int:slot_id>/clear", methods=["POST"])
    def api_looper_clear(slot_id):
        return jsonify(_cmd("looper.clear", {"slot_id": slot_id}))

    @app.route("/api/looper/clock", methods=["POST"])
    def api_looper_clock():
        data = request.json or {}
        return jsonify(_cmd("looper.clock", data))

    # ---------------------------------------------------------------
    # API: Quick Recorder
    # ---------------------------------------------------------------

    @app.route("/api/recorder")
    def api_recorder():
        return jsonify(dict(_state().get("recorder", {})))

    @app.route("/api/recorder/toggle", methods=["POST"])
    def api_recorder_toggle():
        return jsonify(_cmd("recorder.toggle"))

    @app.route("/api/recorder/play", methods=["POST"])
    def api_recorder_play():
        return jsonify(_cmd("recorder.play"))

    @app.route("/api/recorder/stop", methods=["POST"])
    def api_recorder_stop():
        return jsonify(_cmd("recorder.stop"))

    @app.route("/api/recorder/clear", methods=["POST"])
    def api_recorder_clear():
        return jsonify(_cmd("recorder.clear"))

    @app.route("/api/recorder/auto_play", methods=["POST"])
    def api_recorder_auto_play():
        value = (request.json or {}).get("value", True)
        return jsonify(_cmd("recorder.auto_play", {"value": value}))

    @app.route("/api/recorder/save", methods=["POST"])
    def api_recorder_save():
        name = (request.json or {}).get("name") or None
        return jsonify(_cmd("recorder.save", {"name": name}))

    @app.route("/api/recorder/recordings")
    def api_recorder_recordings():
        return jsonify(_cmd("recorder.list"))

    @app.route("/api/recorder/recordings/<name>", methods=["GET", "DELETE"])
    def api_recorder_recording(name):
        if request.method == "DELETE":
            return jsonify(_cmd("recorder.delete", {"name": name}))
        # GET — download .mid file
        path = _cmd("recorder.get_path", {"name": name}).get("path")
        if not path:
            return jsonify({"ok": False, "error": "Not found"}), 404
        return send_file(path, as_attachment=True, download_name=name + ".mid",
                         mimetype="audio/midi")

    @app.route("/api/recorder/clock", methods=["POST"])
    def api_recorder_clock():
        data = request.json or {}
        return jsonify(_cmd("recorder.clock", data))

    @app.route("/api/system/restart", methods=["POST"])
    def api_system_restart():
        """Restart the MIDI Box service — sends SIGTERM to MIDI engine process."""
        return jsonify(_cmd("system.restart"))

    # ---------------------------------------------------------------
    # API: Software Updates
    # ---------------------------------------------------------------

    @app.route("/api/update/status")
    def api_update_status():
        """Return current version info, update availability, and running log."""
        import updater
        status = updater.get_status()
        log_lines = updater.get_update_log()
        return jsonify({
            "current_version":  status["current_version"],
            "latest_version":   status["latest_version"],
            "update_available": status["update_available"],
            "update_type":      status["update_type"],
            "last_checked":     status["last_checked"],
            "check_error":      status["check_error"],
            "update_status":    status["update_status"],
            "log":              log_lines,
        })

    @app.route("/api/update/check", methods=["POST"])
    def api_update_check():
        """Force an immediate update check against GitHub (runs synchronously)."""
        import updater
        result = updater.check_for_updates()
        return jsonify({
            "ok":               True,
            "current_version":  result["current_version"],
            "latest_version":   result["latest_version"],
            "update_available": result["update_available"],
            "update_type":      result["update_type"],
            "last_checked":     result["last_checked"],
            "check_error":      result["check_error"],
        })

    @app.route("/api/update/trigger", methods=["POST"])
    def api_update_trigger():
        """
        Start the update process as a detached subprocess.
        Body (optional): { "type": "simple" | "full" }
        Falls back to the auto-detected type from the last check.
        """
        import updater
        data = request.json or {}
        status = updater.get_status()
        update_type = data.get("type") or status.get("update_type") or "simple"
        if update_type not in ("simple", "full"):
            return jsonify({"ok": False, "error": f"Invalid type: {update_type}"}), 400
        result = updater.trigger_update(update_type)
        if not result.get("ok"):
            return jsonify(result), 500
        return jsonify(result)

    def _make_qr_svg(data: str) -> Response:
        try:
            import qrcode
            import qrcode.image.svg
            qr = qrcode.QRCode(
                error_correction=qrcode.constants.ERROR_CORRECT_M,
                box_size=10,
                border=3,
            )
            qr.add_data(data)
            qr.make(fit=True)
            img = qr.make_image(image_factory=qrcode.image.svg.SvgFillImage)
            buf = io.BytesIO()
            img.save(buf)
            buf.seek(0)
            return Response(buf.read(), mimetype="image/svg+xml")
        except ImportError:
            placeholder = (
                '<svg xmlns="http://www.w3.org/2000/svg" width="200" height="200">'
                '<rect width="200" height="200" fill="#1e2a45"/>'
                '<text x="100" y="96" text-anchor="middle" fill="#8892a4" '
                'font-family="monospace" font-size="11">install qrcode</text>'
                '<text x="100" y="112" text-anchor="middle" fill="#8892a4" '
                'font-family="monospace" font-size="11">pip install qrcode</text>'
                '</svg>'
            )
            return Response(placeholder, mimetype="image/svg+xml")

    return app


class LogBuffer:
    """Captures Python logging output for the MIDI engine process."""

    def __init__(self, max_entries=500):
        self._entries = []
        self._lock = threading.Lock()
        self.max_entries = max_entries
        self._handler = self._LogHandler(self)

    def install(self):
        root = logging.getLogger()
        root.addHandler(self._handler)

    def add(self, record_dict: dict):
        with self._lock:
            self._entries.append(record_dict)
            if len(self._entries) > self.max_entries:
                self._entries = self._entries[-self.max_entries:]

    def get_entries(self, limit=200) -> list:
        with self._lock:
            return list(reversed(self._entries[-limit:]))

    def clear(self):
        with self._lock:
            self._entries.clear()

    class _LogHandler(logging.Handler):
        def __init__(self, buffer):
            super().__init__()
            self.buffer = buffer

        def emit(self, record):
            self.buffer.add({
                "time": time.strftime("%H:%M:%S", time.localtime(record.created)),
                "level": record.levelname,
                "name": record.name,
                "message": record.getMessage(),
            })
