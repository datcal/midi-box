"""
USB Gadget Manager - Makes the Raspberry Pi appear as a USB MIDI device to the Mac.
Uses Linux USB gadget (libcomposite) via configfs.

When connected to a Mac, Logic Pro sees named MIDI ports for each synth.
"""

import subprocess
import logging
from pathlib import Path

import mido

logger = logging.getLogger("midi-box.gadget")

GADGET_BASE = Path("/sys/kernel/config/usb_gadget")
GADGET_NAME = "midi-box"
GADGET_DIR = GADGET_BASE / GADGET_NAME


class GadgetMidi:
    def __init__(self, num_ports: int = 10):
        self.num_ports = num_ports
        self.gadget_alsa_port: str | None = None
        self._input_port = None
        self._output_port = None

    @property
    def is_configured(self) -> bool:
        return GADGET_DIR.exists()

    @property
    def is_connected(self) -> bool:
        """Check if a USB host (Mac) is connected and configured."""
        udc_path = GADGET_DIR / "UDC"
        if not udc_path.exists():
            return False
        try:
            udc_name = udc_path.read_text().strip()
            if not udc_name:
                return False
            state_path = Path(f"/sys/class/udc/{udc_name}/state")
            if state_path.exists():
                return state_path.read_text().strip() == "configured"
        except Exception:
            pass
        return False

    def setup(self) -> bool:
        """
        Configure the USB MIDI gadget via configfs.
        Must be run as root. Typically called from gadget_config.sh at boot.
        """
        if self.is_configured:
            logger.info("USB gadget already configured")
            return True

        try:
            script = Path(__file__).parent.parent / "config" / "gadget_config.sh"
            result = subprocess.run(
                ["sudo", "bash", str(script)],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0:
                logger.error(f"Gadget setup failed: {result.stderr}")
                return False
            logger.info("USB gadget configured successfully")
            return True
        except Exception as e:
            logger.error(f"Gadget setup error: {e}")
            return False

    def teardown(self) -> bool:
        """Remove the USB gadget configuration."""
        if not self.is_configured:
            return True

        try:
            # Disable UDC
            udc_path = GADGET_DIR / "UDC"
            if udc_path.exists():
                udc_path.write_text("")

            # Remove symlinks and dirs (reverse order of creation)
            config_link = GADGET_DIR / "configs" / "c.1" / "midi.usb0"
            if config_link.is_symlink():
                config_link.unlink()

            # Remove directories
            for d in [
                "configs/c.1/strings/0x409",
                "configs/c.1",
                "functions/midi.usb0",
                "strings/0x409",
            ]:
                p = GADGET_DIR / d
                if p.exists():
                    p.rmdir()

            GADGET_DIR.rmdir()
            logger.info("USB gadget removed")
            return True
        except Exception as e:
            logger.error(f"Gadget teardown error: {e}")
            return False

    def find_gadget_midi_port(self) -> str | None:
        """Find the ALSA MIDI port name for the gadget device."""
        try:
            names = mido.get_input_names() + mido.get_output_names()
            for name in names:
                if "midi box" in name.lower() or "f_midi" in name.lower():
                    self.gadget_alsa_port = name
                    logger.info(f"Found gadget MIDI port: {name}")
                    return name
        except Exception as e:
            logger.error(f"Error finding gadget port: {e}")
        return None

    def open_ports(self) -> bool:
        """Open the gadget MIDI ports for reading/writing."""
        port_name = self.gadget_alsa_port or self.find_gadget_midi_port()
        if not port_name:
            logger.warning("Gadget MIDI port not found")
            return False

        try:
            # These are the ports that talk TO/FROM the Mac
            # Input = messages FROM Mac (Logic Pro sends to synths)
            # Output = messages TO Mac (synths send to Logic Pro)
            input_names = mido.get_input_names()
            output_names = mido.get_output_names()

            if port_name in input_names:
                self._input_port = mido.open_input(port_name)
            if port_name in output_names:
                self._output_port = mido.open_output(port_name)

            logger.info("Gadget MIDI ports opened")
            return True
        except Exception as e:
            logger.error(f"Failed to open gadget ports: {e}")
            return False

    def send_to_host(self, message: mido.Message) -> bool:
        """Send a MIDI message to the Mac (via gadget output)."""
        if self._output_port:
            try:
                self._output_port.send(message)
                return True
            except Exception as e:
                logger.error(f"Gadget send error: {e}")
        return False

    def receive_from_host(self) -> list[mido.Message]:
        """Read pending MIDI messages from the Mac."""
        messages = []
        if self._input_port:
            for msg in self._input_port.iter_pending():
                messages.append(msg)
        return messages

    def close(self):
        if self._input_port:
            self._input_port.close()
        if self._output_port:
            self._output_port.close()
        logger.info("Gadget MIDI ports closed")
