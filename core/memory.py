"""
memory.py
Hand idle memory back to Windows.

The speech model is ~200 MB of rarely-touched pages. Trimming the process working set while
Bepo is idle lets Windows reuse that physical RAM for other apps; the pages fault back in on
demand (measured: no noticeable delay for the next dictation). This does not change committed
memory and never unloads the model.
"""

import ctypes
import ctypes.wintypes as wt


def trim_working_set() -> bool:
    """Ask Windows to trim this process's working set. Returns True on success."""
    try:
        kernel32 = ctypes.WinDLL("kernel32")
        psapi = ctypes.WinDLL("psapi")
        kernel32.GetCurrentProcess.restype = wt.HANDLE
        psapi.EmptyWorkingSet.argtypes = [wt.HANDLE]
        return bool(psapi.EmptyWorkingSet(kernel32.GetCurrentProcess()))
    except Exception:
        return False
