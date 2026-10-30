"""Petites fonctions Win32 : écrans, DPI, instance unique, démarrage auto."""

from __future__ import annotations

import ctypes
import sys
import threading
import winreg
from ctypes import wintypes
from pathlib import Path

_user32 = ctypes.windll.user32
_kernel32 = ctypes.windll.kernel32

_MONITOR_DEFAULTTONULL = 0
_MONITOR_DEFAULTTONEAREST = 2
_ERROR_ALREADY_EXISTS = 183
_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_RUN_NAME = "WidgetVolume"


class _MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
    ]


_user32.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
_user32.MonitorFromPoint.restype = wintypes.HMONITOR
_user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(_MONITORINFO)]
_user32.GetMonitorInfoW.restype = wintypes.BOOL


def enable_dpi_awareness() -> None:
    """Rendu net sur les écrans à mise à l'échelle (à appeler avant Tk)."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # par écran
    except (AttributeError, OSError):
        try:
            _user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass


def work_area_at(x: int, y: int) -> tuple[int, int, int, int]:
    """Zone de travail (sans la barre des tâches) de l'écran le plus proche."""
    hmon = _user32.MonitorFromPoint(wintypes.POINT(x, y), _MONITOR_DEFAULTTONEAREST)
    info = _MONITORINFO(cbSize=ctypes.sizeof(_MONITORINFO))
    _user32.GetMonitorInfoW(hmon, ctypes.byref(info))
    r = info.rcWork
    return r.left, r.top, r.right, r.bottom


def point_on_screen(x: int, y: int) -> bool:
    return bool(_user32.MonitorFromPoint(wintypes.POINT(x, y), _MONITOR_DEFAULTTONULL))


_mutex = None


def acquire_single_instance(name: str = "Local\\WidgetVolume") -> bool:
    """False si une autre instance du widget tourne déjà."""
    global _mutex
    _mutex = _kernel32.CreateMutexW(None, False, name)
    return _kernel32.GetLastError() != _ERROR_ALREADY_EXISTS


_MODIFIERS = {"alt": 0x1, "ctrl": 0x2, "control": 0x2, "shift": 0x4, "win": 0x8}
_MOD_NOREPEAT = 0x4000
_WM_HOTKEY = 0x0312
_WM_QUIT = 0x0012


def parse_hotkey(spec: str) -> tuple[int, int] | None:
    """"Ctrl+Alt+S" -> (modificateurs, code de touche), ou None si invalide."""
    mods, vk = 0, None
    for part in (p.strip().lower() for p in spec.split("+")):
        if part in _MODIFIERS:
            mods |= _MODIFIERS[part]
        elif len(part) == 1 and part.isalnum():
            vk = ord(part.upper())
        elif part.startswith("f") and part[1:].isdigit() and 1 <= int(part[1:]) <= 24:
            vk = 0x70 + int(part[1:]) - 1
        else:
            return None
    return (mods, vk) if vk is not None else None


class GlobalHotkey:
    """Raccourci clavier global, actif même quand le widget n'a pas le focus.

    RegisterHotKey envoie WM_HOTKEY à la file de messages du thread qui l'a
    enregistré : on lui dédie donc un thread, et l'interface vient lire
    `consume()` régulièrement (Tk n'est pas utilisable depuis un autre thread).
    """

    def __init__(self, spec: str):
        self.spec = spec
        self.ok = False
        self._pressed = threading.Event()
        self._thread_id = None
        parsed = parse_hotkey(spec)
        if parsed:
            threading.Thread(target=self._run, args=parsed, daemon=True).start()

    def _run(self, mods: int, vk: int) -> None:
        self._thread_id = _kernel32.GetCurrentThreadId()
        if not _user32.RegisterHotKey(None, 1, mods | _MOD_NOREPEAT, vk):
            return  # déjà pris par une autre application
        self.ok = True
        msg = wintypes.MSG()
        while _user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == _WM_HOTKEY:
                self._pressed.set()
        _user32.UnregisterHotKey(None, 1)

    def consume(self) -> bool:
        """True si le raccourci a été pressé depuis le dernier appel."""
        if self._pressed.is_set():
            self._pressed.clear()
            return True
        return False

    def stop(self) -> None:
        if self._thread_id:
            _user32.PostThreadMessageW(self._thread_id, _WM_QUIT, 0, 0)


def _launch_command() -> str:
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    main = Path(__file__).resolve().parent.parent / "main.py"
    return f'"{pythonw}" "{main}"'


def autostart_enabled() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
            winreg.QueryValueEx(key, _RUN_NAME)
        return True
    except OSError:
        return False


def set_autostart(enabled: bool) -> None:
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, _RUN_NAME, 0, winreg.REG_SZ, _launch_command())
        else:
            try:
                winreg.DeleteValue(key, _RUN_NAME)
            except FileNotFoundError:
                pass
