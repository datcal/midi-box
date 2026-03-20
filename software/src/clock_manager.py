"""
Clock Manager — unified BPM and clock source for MIDI Box.

Single source of truth for system BPM.  All timing-dependent modules
(Clip Launcher, Quick Recorder, MIDI Looper) subscribe to this clock
instead of maintaining their own BPM variables.

Clock sources:
  internal   — internal timer thread at the configured BPM
  <device>   — MIDI 0xF8 ticks received from a named external device;
               BPM is detected from inter-tick timing; if the device
               stops sending for EXT_CLOCK_TIMEOUT seconds the manager
               falls back to the internal timer and sets ext_clock_lost=True
               until ticks resume.

Tick subscribers receive: fn(tick, beat, bar, running=True)
  tick  — absolute tick count (96 PPQ, never resets automatically)
  beat  — beat within bar (0-indexed, resets at beats_per_bar)
  bar   — absolute bar count
BPM subscribers receive: fn(bpm)
"""

import os
import time
import threading
import logging
from collections import deque

logger = logging.getLogger("midi-box.clock")

# Internal resolution: 96 ticks per beat (4× MIDI standard 24 PPQ)
INTERNAL_PPQ = 96
# MIDI clock (0xF8) is 24 PPQ — advance 4 internal ticks per MIDI tick
CLOCK_TICKS_PER_MIDI = INTERNAL_PPQ // 24  # = 4

# How long (seconds) without an external 0xF8 tick before we declare clock lost
EXT_CLOCK_TIMEOUT = 2.0


class ClockManager:
    """Single source of truth for system BPM and clock source."""

    def __init__(self):
        self._bpm: float = 120.0
        self._source: str = "internal"   # "internal" | device_name
        self._beats_per_bar: int = 4

        # Absolute clock counters (incremented on every tick)
        self._tick: int = 0
        self._beat: int = 0
        self._bar: int = 0

        # Lifecycle
        self._running: bool = False
        self._lock = threading.Lock()

        # Internal clock thread (used for "internal" mode AND ext-clock fallback)
        self._clock_thread: threading.Thread | None = None
        self._next_tick_time: float = 0.0

        # External clock state
        self._ext_last_tick: float | None = None   # time.monotonic() of last 0xF8
        self._ext_bpm: float | None = None          # detected BPM (linear regression)
        self._ext_tick_times: deque = deque(maxlen=96)  # last 96 tick timestamps (~2 s at 120 BPM)
        self._display_bpm: float | None = None      # display-only EMA of _ext_bpm
        self._ext_clock_active: bool = False        # receiving ticks right now
        self._ext_clock_lost: bool = False          # source≠internal & no ticks

        # Internal fallback while ext clock is lost
        self._fallback_active: bool = False

        # Watchdog thread
        self._watchdog_thread: threading.Thread | None = None

        # Subscribers
        self._tick_subs: list = []  # fn(tick, beat, bar, running)
        self._bpm_subs: list = []   # fn(bpm)

        # MIDI clock output callback: fn() called at 24 PPQ (one MIDI 0xF8 per call).
        # For internal source: fired every 4th internal tick by the clock thread.
        # For external source: fired once per received 0xF8 (forwarding).
        self._midi_clock_callback = None

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def bpm(self) -> float:
        return self._bpm

    @property
    def source(self) -> str:
        return self._source

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def set_bpm(self, bpm: float) -> None:
        """Set the system BPM and notify all BPM subscribers."""
        bpm = max(20.0, min(300.0, float(bpm)))
        with self._lock:
            changed = self._bpm != bpm
            self._bpm = bpm
            if self._running and self._source == "internal":
                # Reset tick timing so the new BPM takes effect immediately
                self._next_tick_time = time.perf_counter()
        if changed:
            for cb in list(self._bpm_subs):
                try:
                    cb(bpm)
                except Exception as e:
                    logger.debug("BPM subscriber %s error: %s", cb, e)
            logger.info(f"Clock BPM: {bpm}")

    def set_source(self, source: str) -> None:
        """Set clock source — 'internal' or a device name."""
        with self._lock:
            self._source = source
            # Reset external state
            self._ext_last_tick = None
            self._ext_bpm = None
            self._display_bpm = None
            self._ext_tick_times.clear()
            self._ext_clock_active = False
            self._ext_clock_lost = False
            # Stop fallback; internal loop will pick up from here
            self._fallback_active = False
            if self._running:
                self._next_tick_time = time.perf_counter()
        logger.info(f"Clock source: {source!r}")

    def set_beats_per_bar(self, beats: int) -> None:
        with self._lock:
            self._beats_per_bar = max(1, min(16, int(beats)))

    # ------------------------------------------------------------------
    # Subscriber registration
    # ------------------------------------------------------------------

    def register_tick_subscriber(self, fn) -> None:
        """Register fn(tick, beat, bar, running) called on every tick."""
        if fn not in self._tick_subs:
            self._tick_subs.append(fn)

    def unregister_tick_subscriber(self, fn) -> None:
        try:
            self._tick_subs.remove(fn)
        except ValueError:
            pass

    def register_bpm_subscriber(self, fn) -> None:
        """Register fn(bpm) called whenever BPM changes."""
        if fn not in self._bpm_subs:
            self._bpm_subs.append(fn)

    def register_midi_clock_callback(self, fn) -> None:
        """Register fn() called on every MIDI clock output tick (24 PPQ).
        Used to broadcast 0xF8 to all connected output devices."""
        self._midi_clock_callback = fn

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the clock (internal thread + watchdog)."""
        self._running = True
        self._tick = 0
        self._beat = 0
        self._bar = 0
        self._next_tick_time = time.perf_counter()

        self._clock_thread = threading.Thread(
            target=self._internal_clock_loop, daemon=True, name="clock-internal"
        )
        self._clock_thread.start()

        self._watchdog_thread = threading.Thread(
            target=self._watchdog_loop, daemon=True, name="clock-watchdog"
        )
        self._watchdog_thread.start()

        logger.info(f"ClockManager started — {self._bpm} BPM, source={self._source!r}")

    def stop(self) -> None:
        """Stop the clock."""
        self._running = False
        logger.info("ClockManager stopped")

    # ------------------------------------------------------------------
    # External clock input
    # ------------------------------------------------------------------

    def on_midi_clock_tick(self) -> None:
        """
        Called by main.py when a MIDI 0xF8 clock message is received from
        the configured external clock source device.
        Advances 4 internal ticks (converts 24 PPQ → 96 PPQ).
        """
        if self._source == "internal":
            return

        now = time.monotonic()

        with self._lock:
            # Accumulate tick timestamps and fit a line through (index, timestamp).
            # Linear regression is immune to USB-bundled ticks: a single jittery
            # timestamp shifts the result by ~1/n² instead of dominating the endpoints.
            self._ext_tick_times.append(now)
            n = len(self._ext_tick_times)
            if n >= 8:
                times = list(self._ext_tick_times)
                i_mean = (n - 1) * 0.5
                t_mean = sum(times) / n
                num = sum((i - i_mean) * (t - t_mean) for i, t in enumerate(times))
                den = n * (n * n - 1) / 12.0  # == Σ(i − ī)² for i = 0..n-1
                if den > 0:
                    slope = num / den  # seconds per MIDI tick
                    if slope > 0:
                        self._ext_bpm = 60.0 / (slope * 24)
                        # Smooth display-only value (α=0.2); absorbs rare GIL-pause outliers
                        if self._display_bpm is None:
                            self._display_bpm = self._ext_bpm
                        else:
                            self._display_bpm = self._display_bpm * 0.8 + self._ext_bpm * 0.2

            was_lost = self._ext_clock_lost
            self._ext_last_tick = now   # kept for watchdog timeout detection
            self._ext_clock_active = True
            self._ext_clock_lost = False
            self._fallback_active = False   # stop any running fallback

        if was_lost:
            logger.info("External clock recovered")

        # Forward the raw clock tick to output devices immediately
        if self._midi_clock_callback:
            try:
                self._midi_clock_callback()
            except Exception:
                pass

        # Advance 4 internal ticks per MIDI 0xF8 (24→96 PPQ conversion)
        for _ in range(CLOCK_TICKS_PER_MIDI):
            self._advance_tick()

    def on_transport_reset(self) -> None:
        """
        Called when MIDI START (0xFA) is received — resets absolute tick
        so beat/bar counters align with the external transport position.
        """
        with self._lock:
            self._tick = 0
            self._beat = 0
            self._bar = 0

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def get_status(self) -> dict:
        with self._lock:
            return {
                "bpm": self._bpm,
                "source": self._source,
                "ext_bpm": round(self._display_bpm) if self._display_bpm is not None else None,
                "ext_clock_active": self._ext_clock_active,
                "ext_clock_lost": self._ext_clock_lost,
            }

    # ------------------------------------------------------------------
    # Internal clock loop
    # ------------------------------------------------------------------

    def _internal_clock_loop(self) -> None:
        """Background thread: tick at the configured BPM using internal timer."""
        # Elevate this thread to real-time scheduling so the OS cannot preempt it
        # for multiple milliseconds mid-tick.  Requires the same LimitRTPRIO=70
        # systemd setting used by the main thread.  Falls back silently on macOS or
        # when running without the right privileges.
        try:
            param = os.sched_param(sched_priority=60)
            os.sched_setscheduler(0, os.SCHED_FIFO, param)
            logger.debug("Clock thread: SCHED_FIFO priority 60")
        except Exception:
            pass

        while self._running:
            now = time.perf_counter()
            if now >= self._next_tick_time:
                # Tick boundary: read shared state under lock.
                # This runs at most INTERNAL_PPQ × BPM/60 times per second
                # (e.g. 192×/s at 120 BPM) — not on every spin iteration.
                with self._lock:
                    active = (self._source == "internal") or self._fallback_active
                    bpm = self._bpm

                if not active:
                    time.sleep(0.001)
                    continue

                tick_interval = 60.0 / (bpm * INTERNAL_PPQ)
                self._next_tick_time += tick_interval
                # Catch up if we fell behind (e.g. after source switch or long sleep)
                if self._next_tick_time < now:
                    self._next_tick_time = now + tick_interval
                self._advance_tick()
            else:
                remaining = self._next_tick_time - now
                if remaining > 0.001:
                    # Coarse sleep: wake up ~1 ms before the tick boundary.
                    # No lock held — source-change detection happens on the next
                    # tick boundary (≤ one tick interval away, ≤ 5 ms at 120 BPM).
                    time.sleep(remaining - 0.001)
                # else: pure busy-wait — tight loop on perf_counter() only,
                # no lock, no sleep; fires within ~50 µs of target on SCHED_FIFO.

    def _advance_tick(self) -> None:
        """Increment absolute tick counter and notify subscribers."""
        with self._lock:
            self._tick += 1
            if self._tick % INTERNAL_PPQ == 0:
                self._beat += 1
                if self._beat >= self._beats_per_bar:
                    self._beat = 0
                    self._bar += 1
            tick = self._tick
            beat = self._beat
            bar = self._bar
            is_internal = (self._source == "internal") or self._fallback_active

        # Send MIDI clock (0xF8) to hardware FIRST — before any subscriber callbacks.
        # Subscribers (launcher, recorder, looper) are not microsecond-sensitive;
        # the USB write latency is.  Putting the hardware send here means only the
        # lock-release above separates "tick decision" from "ALSA write".
        if is_internal and tick % CLOCK_TICKS_PER_MIDI == 0 and self._midi_clock_callback:
            try:
                self._midi_clock_callback()
            except Exception:
                pass

        for sub in list(self._tick_subs):
            try:
                sub(tick, beat, bar, True)
            except Exception as e:
                logger.debug("Tick subscriber %s error: %s", sub, e)

    # ------------------------------------------------------------------
    # Watchdog
    # ------------------------------------------------------------------

    def _watchdog_loop(self) -> None:
        """Detect external clock loss and activate internal fallback."""
        while self._running:
            time.sleep(0.5)
            if not self._running:
                break

            with self._lock:
                source = self._source
                ext_last = self._ext_last_tick
                ext_lost = self._ext_clock_lost
                fallback = self._fallback_active

            if source == "internal":
                continue

            now = time.monotonic()
            clock_absent = ext_last is None or (now - ext_last) > EXT_CLOCK_TIMEOUT

            if clock_absent and not ext_lost:
                with self._lock:
                    self._ext_clock_active = False
                    self._ext_clock_lost = True
                    self._fallback_active = True
                    self._next_tick_time = time.perf_counter()
                    self._ext_tick_times.clear()
                    self._ext_bpm = None
                    self._display_bpm = None
                logger.warning(
                    f"External clock lost (source: {source!r}) — "
                    f"falling back to internal at {self._bpm:.0f} BPM"
                )
