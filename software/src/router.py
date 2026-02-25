"""
MIDI Routing Engine - The core of MIDI Box.
Routes MIDI messages between any combination of USB and hardware ports.
Supports filtering, channel remapping, merging, and splitting.
"""

import threading
import time
import logging
from dataclasses import dataclass, field

import mido

from midi_filter import MidiFilter

logger = logging.getLogger("midi-box.router")


@dataclass
class Route:
    """A single MIDI route from one source to one destination."""
    source: str           # Source port/device name
    destination: str      # Destination port/device name
    midi_filter: MidiFilter = field(default_factory=MidiFilter.pass_all)
    enabled: bool = True
    name: str = ""        # Optional friendly name

    def __post_init__(self):
        if not self.name:
            self.name = f"{self.source} -> {self.destination}"


@dataclass
class PortActivity:
    """Tracks MIDI activity on a port for UI display."""
    last_message_time: float = 0
    message_count: int = 0
    last_message_type: str = ""

    @property
    def is_active(self) -> bool:
        return (time.time() - self.last_message_time) < 0.5

    def record(self, msg_type: str):
        self.last_message_time = time.time()
        self.message_count += 1
        self.last_message_type = msg_type


class MidiRouter:
    """
    Central routing engine.

    Usage:
        router = MidiRouter()
        router.set_send_callback(my_send_function)
        router.add_route("KeyLab 88 MK2", "MS-20 Mini", MidiFilter.channel_only(1))
        router.process_message("KeyLab 88 MK2", some_midi_message)
    """

    def __init__(self):
        self.routes: list[Route] = []
        self._lock = threading.Lock()
        self._send_callback = None  # Function to actually send MIDI
        self._activity: dict[str, PortActivity] = {}
        self._clock_source: str | None = None
        self._clock_callback = None  # fn(mido.Message) for clip launcher
        self._running = False
        self._routes_by_source: dict[str, list[Route]] = {}  # O(1) source lookup

    def _rebuild_index(self):
        """Rebuild the source→routes lookup dict. Called after any route change.
        Assignment is atomic in CPython so no lock needed for readers."""
        index: dict[str, list[Route]] = {}
        for r in self.routes:
            index.setdefault(r.source, []).append(r)
        self._routes_by_source = index

    def set_send_callback(self, callback):
        """
        Set the callback for sending MIDI messages.
        Signature: callback(destination_name: str, message: mido.Message) -> bool
        """
        self._send_callback = callback

    def set_clock_source(self, source_name: str | None):
        """Set which device is the master MIDI clock source."""
        self._clock_source = source_name
        logger.info(f"Clock source: {source_name or 'none'}")

    def add_route(
        self,
        source: str,
        destination: str,
        midi_filter: MidiFilter = None,
        name: str = "",
    ) -> Route:
        """Add a routing rule."""
        route = Route(
            source=source,
            destination=destination,
            midi_filter=midi_filter or MidiFilter.pass_all(),
            name=name,
        )
        with self._lock:
            self.routes.append(route)
        self._rebuild_index()
        logger.info(f"Route added: {route.name}")
        return route

    def remove_route(self, source: str, destination: str) -> bool:
        """Remove a specific route."""
        with self._lock:
            before = len(self.routes)
            self.routes = [
                r for r in self.routes
                if not (r.source == source and r.destination == destination)
            ]
            removed = before - len(self.routes)
        if removed:
            self._rebuild_index()
            logger.info(f"Removed {removed} route(s): {source} -> {destination}")
        return removed > 0

    def clear_routes(self):
        """Remove all routes."""
        with self._lock:
            count = len(self.routes)
            self.routes.clear()
        self._rebuild_index()
        logger.info(f"Cleared {count} routes")

    def process_message(self, source_name: str, message: mido.Message):
        """
        Process an incoming MIDI message from a source port.
        Routes it to all matching destinations after filtering.
        """
        # Record activity
        self._record_activity(source_name, message.type, is_input=True)

        # Clock / transport gating.
        #
        # MIDI clock (0xF8) is never routed through the per-device table;
        # ClockManager broadcasts it to all outputs at 24 PPQ.
        #
        # Transport messages (start/stop/continue) from the designated clock
        # source go to ClockManager for broadcast AND then fall through to the
        # routing table so that explicit routes (e.g. SP-404 → KeyStep) can
        # also forward them.  Transport from non-clock-source devices (when an
        # external clock source is selected) is dropped to avoid conflicts.
        if message.type in ("clock", "start", "stop", "continue", "songpos"):
            if message.type == "clock":
                # Raw clock tick: deliver to ClockManager only, never route.
                # Only forward from the designated clock source; drop ticks from
                # all other devices to prevent BPM corruption when multiple
                # devices are sending clock simultaneously.
                if self._clock_callback:
                    if not self._clock_source or source_name == self._clock_source:
                        self._clock_callback(message)
                return

            # Transport (start/stop/continue/songpos):
            # Drop if an external clock source is set and this isn't it.
            if self._clock_source and source_name != self._clock_source:
                return

            # Deliver to ClockManager/Launcher for system-wide broadcast.
            if self._clock_callback and message.type in ("start", "stop", "continue"):
                self._clock_callback(message)

            # Then fall through to the routing table so explicit per-device
            # routes (e.g. SP-404 → KeyStep) also receive the transport message.

        # O(1) source lookup — index rebuilt atomically on route changes
        routes_for_source = self._routes_by_source.get(source_name)
        if not routes_for_source:
            return

        for route in routes_for_source:
            if not route.enabled:
                continue
            filtered = route.midi_filter.apply(message)
            if filtered is None:
                continue
            self._send(route.destination, filtered)

    def _send(self, destination: str, message: mido.Message):
        """Send a message to a destination via the registered callback."""
        if self._send_callback:
            success = self._send_callback(destination, message)
            if success:
                self._record_activity(destination, message.type, is_input=False)
        else:
            logger.warning("No send callback registered")

    def _record_activity(self, port_name: str, msg_type: str, is_input: bool):
        key = f"{'in' if is_input else 'out'}:{port_name}"
        if key not in self._activity:
            self._activity[key] = PortActivity()
        self._activity[key].record(msg_type)

    def get_activity(self, port_name: str, is_input: bool = True) -> PortActivity:
        key = f"{'in' if is_input else 'out'}:{port_name}"
        return self._activity.get(key, PortActivity())

    def get_routes_from(self, source: str) -> list[Route]:
        with self._lock:
            return [r for r in self.routes if r.source == source]

    def get_routes_to(self, destination: str) -> list[Route]:
        with self._lock:
            return [r for r in self.routes if r.destination == destination]

    def get_all_routes(self) -> list[Route]:
        with self._lock:
            return list(self.routes)

    def load_routes(self, route_defs: list[dict]):
        """
        Load routes from a preset definition.
        Each dict: {from, to, filter: {...}, name?}
        """
        self.clear_routes()
        with self._lock:
            for rd in route_defs:
                filter_data = rd.get("filter", {})
                midi_filter = MidiFilter.from_dict(filter_data) if filter_data else MidiFilter.pass_all()
                route = Route(
                    source=rd["from"],
                    destination=rd["to"],
                    midi_filter=midi_filter,
                    name=rd.get("name", ""),
                )
                self.routes.append(route)
                logger.info(f"Route added: {route.name}")
        self._rebuild_index()  # build once for all routes

    def dump_routes(self) -> list[dict]:
        """Serialize current routes for saving."""
        with self._lock:
            return [
                {
                    "from": r.source,
                    "to": r.destination,
                    "filter": r.midi_filter.to_dict(),
                    "name": r.name,
                    "enabled": r.enabled,
                }
                for r in self.routes
            ]

    def status(self) -> str:
        """Return a human-readable status string."""
        lines = [f"MIDI Router: {len(self.routes)} active routes"]
        if self._clock_source:
            lines.append(f"Clock source: {self._clock_source}")
        lines.append("")
        with self._lock:
            for r in self.routes:
                state = "ON" if r.enabled else "OFF"
                filt = ""
                if r.midi_filter.channels:
                    filt = f" [ch {','.join(str(c) for c in r.midi_filter.channels)}]"
                lines.append(f"  [{state}] {r.name}{filt}")
        return "\n".join(lines)
