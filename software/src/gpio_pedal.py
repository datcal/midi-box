"""
GPIO Foot Pedal Listener — Raspberry Pi only.

Uses gpiozero (pre-installed on Pi OS, or: pip install gpiozero).
Gracefully becomes a no-op on macOS / any platform where gpiozero is absent.

Wiring assumed: pull-up resistor, pedal connects GPIO pin to GND.
Pin goes LOW when pedal is pressed → triggers callback.
"""

import logging
from typing import Callable, Optional

logger = logging.getLogger("midi-box.gpio_pedal")


class GpioPedal:
    """Listens for a foot-pedal press on a GPIO pin and calls a callback."""

    def __init__(
        self,
        pin: int = 17,
        pull_up: bool = True,
        debounce_ms: int = 50,
        callback: Optional[Callable] = None,
    ):
        self._callback = callback
        self._btn = None

        try:
            from gpiozero import Button  # type: ignore
            self._btn = Button(
                pin,
                pull_up=pull_up,
                bounce_time=debounce_ms / 1000.0,
            )
            self._btn.when_pressed = self._on_press
            logger.info(
                f"GPIO pedal ready: pin {pin}, "
                f"pull_{'up' if pull_up else 'down'}, "
                f"debounce {debounce_ms}ms"
            )
        except ImportError:
            logger.warning(
                "gpiozero not available — GPIO pedal disabled. "
                "Install with: pip install gpiozero"
            )
        except Exception as e:
            logger.warning(f"GPIO pedal init failed: {e}")

    def _on_press(self) -> None:
        if self._callback:
            try:
                self._callback()
            except Exception as e:
                logger.error(f"GPIO pedal callback error: {e}")

    def close(self) -> None:
        if self._btn:
            try:
                self._btn.close()
            except Exception:
                pass
        self._btn = None
