"""
MIDI Filter - Channel filtering, message type filtering, and channel remapping.
Applied per-route in the routing engine.
"""

import mido
from dataclasses import dataclass, field


@dataclass
class MidiFilter:
    """
    Filter configuration for a single route.
    All fields are optional — unset fields mean "pass everything".
    """
    # Channel filter: only pass messages on these channels (1-16, MIDI standard)
    # Empty list = pass all channels
    channels: list[int] = field(default_factory=list)

    # Remap channel: change the MIDI channel of passing messages
    # 0 = no remap, 1-16 = force to this channel
    remap_channel: int = 0

    # Message type filter: only pass these message types
    # Empty list = pass all types
    # Options: "note", "cc", "program_change", "pitchwheel", "aftertouch",
    #          "polytouch", "clock", "sysex", "start", "stop", "continue"
    message_types: list[str] = field(default_factory=list)

    # Velocity range (for note messages only)
    velocity_min: int = 0
    velocity_max: int = 127

    # CC filter: only pass these CC numbers. Empty = pass all
    cc_numbers: list[int] = field(default_factory=list)

    # Block clock messages (useful to prevent double-clocking)
    block_clock: bool = False

    # Block sysex
    block_sysex: bool = False

    def apply(self, message: mido.Message) -> mido.Message | None:
        """
        Apply filter to a message. Returns the (possibly modified) message,
        or None if the message should be blocked.
        """
        # Handle clock/timing messages
        if message.type in ("clock", "songpos", "song_select"):
            if self.block_clock:
                return None
            return message

        # Handle transport
        if message.type in ("start", "stop", "continue"):
            if self.block_clock:  # Block transport with clock
                return None
            if self.message_types and "transport" not in self.message_types:
                return None
            return message

        # Handle sysex
        if message.type == "sysex":
            if self.block_sysex:
                return None
            if self.message_types and "sysex" not in self.message_types:
                return None
            return message

        # Channel filtering (for channel messages)
        if hasattr(message, "channel"):
            # MIDI standard: channels 1-16, mido uses 0-15 internally
            midi_channel = message.channel + 1

            if self.channels and midi_channel not in self.channels:
                return None

        # Message type filtering
        if self.message_types:
            type_map = {
                "note_on": "note",
                "note_off": "note",
                "control_change": "cc",
                "program_change": "program_change",
                "pitchwheel": "pitchwheel",
                "aftertouch": "aftertouch",
                "polytouch": "polytouch",
            }
            msg_category = type_map.get(message.type, message.type)
            if msg_category not in self.message_types:
                return None

        # Velocity range filter (note messages)
        if message.type == "note_on" and hasattr(message, "velocity"):
            if not (self.velocity_min <= message.velocity <= self.velocity_max):
                return None

        # CC number filter
        if message.type == "control_change" and self.cc_numbers:
            if message.control not in self.cc_numbers:
                return None

        # Channel remapping
        if self.remap_channel > 0 and hasattr(message, "channel"):
            message = message.copy(channel=self.remap_channel - 1)

        return message

    @classmethod
    def from_dict(cls, data: dict) -> "MidiFilter":
        """Create a MidiFilter from a preset dict."""
        return cls(
            channels=data.get("channels", []),
            remap_channel=data.get("remap_channel", 0),
            message_types=data.get("message_types", []),
            velocity_min=data.get("velocity_min", 0),
            velocity_max=data.get("velocity_max", 127),
            cc_numbers=data.get("cc_numbers", []),
            block_clock=data.get("block_clock", False),
            block_sysex=data.get("block_sysex", False),
        )

    @classmethod
    def pass_all(cls) -> "MidiFilter":
        """Create a filter that passes everything."""
        return cls()

    @classmethod
    def channel_only(cls, channel: int) -> "MidiFilter":
        """Create a filter that only passes a specific channel."""
        return cls(channels=[channel])

    @classmethod
    def notes_only(cls, channel: int = 0) -> "MidiFilter":
        """Create a filter that only passes note messages."""
        channels = [channel] if channel else []
        return cls(channels=channels, message_types=["note"])

    def to_dict(self) -> dict:
        """Serialize to dict for JSON storage."""
        d = {}
        if self.channels:
            d["channels"] = self.channels
        if self.remap_channel:
            d["remap_channel"] = self.remap_channel
        if self.message_types:
            d["message_types"] = self.message_types
        if self.velocity_min > 0:
            d["velocity_min"] = self.velocity_min
        if self.velocity_max < 127:
            d["velocity_max"] = self.velocity_max
        if self.cc_numbers:
            d["cc_numbers"] = self.cc_numbers
        if self.block_clock:
            d["block_clock"] = True
        if self.block_sysex:
            d["block_sysex"] = True
        return d
