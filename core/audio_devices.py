"""
audio_devices.py
Input-device helpers for the microphone setting. Pure Python; sounddevice is imported lazily.

Only devices of the system's default host API are offered (the same API the speech engine
uses when no device is chosen), so each physical microphone appears once.
"""

import logging


def _input_devices():
    """[(index, name)] of capture devices in the default host API."""
    import sounddevice as sd
    devices = sd.query_devices()
    try:
        default_index = sd.query_devices(kind="input")["index"]
        hostapi = devices[default_index]["hostapi"]
    except Exception:
        hostapi = sd.default.hostapi
    return [
        (i, d["name"]) for i, d in enumerate(devices)
        if d["max_input_channels"] > 0 and d["hostapi"] == hostapi
    ]


def list_input_devices() -> list[str]:
    """Names of the available microphones (empty if they can't be queried)."""
    try:
        names: list[str] = []
        for _, name in _input_devices():
            if name not in names:
                names.append(name)
        return names
    except Exception as exc:
        logging.warning("[Audio] Could not list input devices: %s", exc)
        return []


def resolve_device(name: str | None) -> int | None:
    """
    Device index for a saved microphone name, or None for "system default" (also when the
    saved device is not currently connected, so dictation keeps working).
    """
    if not name:
        return None
    try:
        devices = _input_devices()
    except Exception as exc:
        logging.warning("[Audio] Could not query input devices: %s", exc)
        return None
    for index, device_name in devices:
        if device_name == name:
            return index
    lowered = name.lower()
    for index, device_name in devices:      # tolerate driver-truncated / slightly changed names
        if device_name.lower().startswith(lowered) or lowered.startswith(device_name.lower()):
            return index
    logging.warning("[Audio] Microphone %r not found; using the system default", name)
    return None
