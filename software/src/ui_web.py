"""
Web UI - Flask + WebSocket server for MIDI Box.

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

import json
import time
import logging
import threading
from pathlib import Path

from flask import Flask, render_template, jsonify, request, Response

logger = logging.getLogger("midi-box.web")

# We'll store a reference to the MidiBox app instance
_midi_box = None


def create_app(midi_box_instance):
    global _midi_box
    _midi_box = midi_box_instance

    app = Flask(
        __name__,
        template_folder=str(Path(__file__).resolve().parent.parent / "web_ui" / "templates"),
        static_folder=str(Path(__file__).resolve().parent.parent / "web_ui" / "static"),
    )
    app.config["SECRET_KEY"] = "midi-box-dev"

    def _persist():
        """Save current routes + state to disk after any change."""
        _midi_box.state.set_routes(_midi_box.router.dump_routes())
        _midi_box.state.set_clock_source(_midi_box.router._clock_source)

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

    # ---------------------------------------------------------------
    # API: Devices
    # ---------------------------------------------------------------

    @app.route("/api/devices")
    def api_devices():
        devices = []
        for name, dev in _midi_box.registry.get_all_devices().items():
            activity_in = _midi_box.router.get_activity(name, is_input=True)
            activity_out = _midi_box.router.get_activity(name, is_input=False)
            devices.append({
                "name": name,
                "port_type": dev.port_type,
                "direction": dev.direction,
                "device_type": dev.device_type,
                "port_id": dev.port_id,
                "midi_channel": dev.midi_channel,
                "connected": dev.connected,
                "activity_in": activity_in.is_active,
                "activity_out": activity_out.is_active,
                "msg_count_in": activity_in.message_count,
                "msg_count_out": activity_out.message_count,
            })
        return jsonify({"devices": devices, "mode": _midi_box.mode})

    # ---------------------------------------------------------------
    # API: Routes
    # ---------------------------------------------------------------

    @app.route("/api/routes")
    def api_routes_list():
        routes = _midi_box.router.dump_routes()
        return jsonify({"routes": routes})

    @app.route("/api/routes", methods=["POST"])
    def api_routes_add():
        data = request.json
        from midi_filter import MidiFilter
        filt = MidiFilter.from_dict(data.get("filter", {}))
        route = _midi_box.router.add_route(
            source=data["from"],
            destination=data["to"],
            midi_filter=filt,
            name=data.get("name", ""),
        )
        _persist()
        return jsonify({"ok": True, "route": route.name})

    @app.route("/api/routes", methods=["DELETE"])
    def api_routes_remove():
        data = request.json
        removed = _midi_box.router.remove_route(data["from"], data["to"])
        _persist()
        return jsonify({"ok": removed})

    @app.route("/api/routes/clear", methods=["POST"])
    def api_routes_clear():
        _midi_box.router.clear_routes()
        _persist()
        return jsonify({"ok": True})

    @app.route("/api/routes/toggle", methods=["POST"])
    def api_routes_toggle():
        data = request.json
        for route in _midi_box.router.get_all_routes():
            if route.source == data["from"] and route.destination == data["to"]:
                route.enabled = not route.enabled
                _persist()
                return jsonify({"ok": True, "enabled": route.enabled})
        return jsonify({"ok": False}), 404

    # ---------------------------------------------------------------
    # API: Presets
    # ---------------------------------------------------------------

    @app.route("/api/presets")
    def api_presets_list():
        names = _midi_box.presets.list_presets()
        return jsonify({
            "presets": names,
            "current": _midi_box.presets.current_preset,
        })

    @app.route("/api/presets/<name>")
    def api_preset_get(name):
        data = _midi_box.presets.load(name)
        if data:
            return jsonify(data)
        return jsonify({"error": "not found"}), 404

    @app.route("/api/presets/<name>/load", methods=["POST"])
    def api_preset_load(name):
        data = _midi_box.presets.load(name)
        if not data:
            return jsonify({"error": "not found"}), 404
        routes = _midi_box.presets.get_routes(data)
        _midi_box.router.load_routes(routes)
        clock = _midi_box.presets.get_clock_source(data)
        _midi_box.router.set_clock_source(clock)
        _midi_box.state.set_preset(name)
        _persist()
        return jsonify({"ok": True, "name": name, "routes": len(routes)})

    @app.route("/api/presets/save", methods=["POST"])
    def api_preset_save():
        data = request.json
        name = data.get("name", "custom")
        preset = {
            "name": data.get("display_name", name),
            "description": data.get("description", ""),
            "routes": _midi_box.router.dump_routes(),
            "clock_source": data.get("clock_source"),
        }
        ok = _midi_box.presets.save(name, preset)
        return jsonify({"ok": ok, "name": name})

    @app.route("/api/presets/<name>", methods=["DELETE"])
    def api_preset_delete(name):
        ok = _midi_box.presets.delete(name)
        return jsonify({"ok": ok})

    # ---------------------------------------------------------------
    # API: MIDI Monitor
    # ---------------------------------------------------------------

    @app.route("/api/monitor")
    def api_monitor():
        limit = request.args.get("limit", 100, type=int)
        offset = request.args.get("offset", 0, type=int)
        entries = _midi_box.midi_logger.get_entries(limit=limit, offset=offset)
        stats = _midi_box.midi_logger.get_stats()
        return jsonify({
            "entries": entries,
            "stats": stats,
            "paused": _midi_box.midi_logger.is_paused,
        })

    @app.route("/api/monitor/clear", methods=["POST"])
    def api_monitor_clear():
        _midi_box.midi_logger.clear()
        return jsonify({"ok": True})

    @app.route("/api/monitor/pause", methods=["POST"])
    def api_monitor_pause():
        _midi_box.midi_logger.pause()
        return jsonify({"ok": True, "paused": True})

    @app.route("/api/monitor/resume", methods=["POST"])
    def api_monitor_resume():
        _midi_box.midi_logger.resume()
        return jsonify({"ok": True, "paused": False})

    # ---------------------------------------------------------------
    # API: Settings
    # ---------------------------------------------------------------

    @app.route("/api/settings")
    def api_settings():
        return jsonify({
            "mode": _midi_box.mode,
            "platform": _midi_box.platform,
            "preset": _midi_box.presets.current_preset,
            "total_routes": len(_midi_box.router.get_all_routes()),
            "total_devices": len(_midi_box.registry.get_all_devices()),
            "clock_source": _midi_box.router._clock_source,
        })

    @app.route("/api/settings/clock", methods=["POST"])
    def api_settings_clock():
        data = request.json
        _midi_box.router.set_clock_source(data.get("source"))
        _persist()
        return jsonify({"ok": True})

    @app.route("/api/settings/rescan", methods=["POST"])
    def api_settings_rescan():
        """Force rescan of MIDI devices."""
        _midi_box._init_usb_midi()
        devices = list(_midi_box.registry.get_all_devices().keys())
        return jsonify({"ok": True, "devices": devices})

    # ---------------------------------------------------------------
    # API: Application Logs
    # ---------------------------------------------------------------

    @app.route("/api/logs")
    def api_logs():
        limit = request.args.get("limit", 200, type=int)
        entries = _midi_box.log_buffer.get_entries(limit)
        return jsonify({"entries": entries})

    @app.route("/api/logs/clear", methods=["POST"])
    def api_logs_clear():
        _midi_box.log_buffer.clear()
        return jsonify({"ok": True})

    # ---------------------------------------------------------------
    # API: Polling endpoint for real-time updates
    # ---------------------------------------------------------------

    @app.route("/api/poll")
    def api_poll():
        """Lightweight endpoint for UI polling — returns activity + stats."""
        devices = []
        for name, dev in _midi_box.registry.get_all_devices().items():
            a_in = _midi_box.router.get_activity(name, is_input=True)
            a_out = _midi_box.router.get_activity(name, is_input=False)
            devices.append({
                "name": name,
                "active_in": a_in.is_active,
                "active_out": a_out.is_active,
                "count_in": a_in.message_count,
                "count_out": a_out.message_count,
            })
        return jsonify({
            "devices": devices,
            "mode": _midi_box.mode,
            "preset": _midi_box.presets.current_preset,
        })

    # ---------------------------------------------------------------
    # API: Export / Import
    # ---------------------------------------------------------------

    @app.route("/api/export")
    def api_export():
        """Export full state as downloadable JSON file."""
        data = _midi_box.state.export_all()
        return Response(
            json.dumps(data, indent=2),
            mimetype="application/json",
            headers={"Content-Disposition": "attachment; filename=midi-box-export.json"},
        )

    @app.route("/api/import", methods=["POST"])
    def api_import():
        """Import state from uploaded JSON."""
        # Accept either file upload or JSON body
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

        ok = _midi_box.state.import_all(data)
        if ok:
            # Reload routes from imported state
            routes = _midi_box.state.get_routes()
            _midi_box.router.load_routes(routes)
            clock = _midi_box.state.get_clock_source()
            _midi_box.router.set_clock_source(clock)
            _midi_box.presets.current_preset = _midi_box.state.get_preset()
            return jsonify({"ok": True, "routes": len(routes)})
        return jsonify({"ok": False, "error": "Import failed"}), 400

    @app.route("/api/state/reset", methods=["POST"])
    def api_state_reset():
        """Reset state to defaults."""
        _midi_box.state.reset()
        _midi_box.router.clear_routes()
        _midi_box.presets.current_preset = None
        return jsonify({"ok": True})

    return app


class LogBuffer:
    """Captures Python logging output for the web UI."""

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
