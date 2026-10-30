"""Fenêtre du widget : boutons de sortie audio + barre de volume."""

from __future__ import annotations

import os
import time
import tkinter as tk
import tkinter.font as tkfont
from _ctypes import COMError

from . import config, winutil
from .audio import AudioController, OutputDevice
from .widgets import BG, BORDER, TEXT, TEXT_DIM, Slider, SourceButton

GLYPH_CLOSE = ""
GLYPH_MUTE = ""
GLYPH_VOLUME = ("", "", "", "")  # 0 à 3 ondes

POLL_MS = 300  # volume (touches multimédia, autres applis...)
DEVICE_POLL_EVERY = 5  # liste des périphériques : 1 tick sur 5
HOVER_TICK_MS = 80  # survol de la souris et raccourci clavier
FADE_TICK_MS = 20  # animation du fondu
WAKE_EXTRA_S = 1.0  # temps d'affichage supplémentaire après un changement auto


def _icon_family(root: tk.Misc) -> str:
    families = set(tkfont.families(root))
    for name in ("Segoe Fluent Icons", "Segoe MDL2 Assets"):
        if name in families:
            return name
    return "Segoe UI Symbol"


def _find_device(source: dict, devices: list[OutputDevice]) -> OutputDevice | None:
    """Premier périphérique correspondant à la source, les actifs d'abord."""
    match = [m.lower() for m in source.get("match", [])]
    exclude = [e.lower() for e in source.get("exclude", [])]
    candidates = [
        d
        for d in devices
        if any(m in d.name.lower() for m in match)
        and not any(e in d.name.lower() for e in exclude)
    ]
    candidates.sort(key=lambda d: not d.active)
    return candidates[0] if candidates else None


class VolumeWidget:
    def __init__(self, root: tk.Tk, audio: AudioController, cfg: dict):
        self.root = root
        self.audio = audio
        self.cfg = cfg
        self.scale = root.winfo_fpixels("1i") / 96
        self._drag_offset: tuple[int, int] | None = None
        self._tick = 0
        self._devices: list[OutputDevice] = []
        self._default_id: str | None = None
        self._muted = False
        self._volume = 0
        self._alpha = 1.0
        self._last_hover = time.monotonic()
        self._menu_open = False
        self._vertical = False
        self._auto_active: bool | None = None  # état de la source auto au dernier relevé
        self._before_auto: str | None = None  # sortie à rétablir à sa déconnexion
        self.body: tk.Frame | None = None

        root.title("Widget Volume")
        root.overrideredirect(True)  # pas de barre de titre ni d'icône dans la barre des tâches
        root.configure(bg=BORDER)
        root.attributes("-topmost", bool(cfg.get("topmost", True)))

        icon_family = _icon_family(root)
        self.fonts = {
            "icon": (icon_family, 11),
            "icon_big": (icon_family, 15),
            "small": ("Segoe UI", 9),
            "value": ("Segoe UI Semibold", 9),
        }
        self.hotkey = winutil.GlobalHotkey(cfg.get("hotkey", ""))
        root.bind_all("<MouseWheel>", self._on_wheel)
        root.bind_all("<Button-3>", self._show_menu)
        self._build_menu()
        self._build()
        self._place_initially()
        self._update_orientation()
        self._poll(force_devices=True)
        self._fade_tick()

    # --- Construction ------------------------------------------------------

    def _px(self, n: float) -> int:
        return round(n * self.scale)

    def _build(self) -> None:
        """(Re)construit le contenu selon l'orientation et le mode compact."""
        if self.body is not None:
            self.body.destroy()
        body = self.body = tk.Frame(self.root, bg=BG)
        body.pack(padx=1, pady=1, fill="both", expand=True)
        compact = bool(self.cfg.get("compact"))
        if self._vertical:
            draggable = self._build_vertical(body, compact)
        elif compact:
            draggable = self._build_compact(body)
        else:
            draggable = self._build_full(body)
        for w in draggable:
            w.bind("<ButtonPress-1>", self._start_drag)
            w.bind("<B1-Motion>", self._drag)
            w.bind("<ButtonRelease-1>", self._end_drag)
            w.bind("<Double-Button-1>", lambda e: self.toggle_compact())

    def _source_tooltip(self, source: dict) -> str:
        device = _find_device(source, self._devices)
        if device is None:
            detail = "introuvable"
        elif device.active:
            detail = device.name
        else:
            detail = "non connecté"
        return f"{source.get('label', '?')}\n{detail}"

    def _make_source_buttons(self, parent, compact: bool, vertical: bool = False) -> None:
        self.source_buttons: list[SourceButton] = []
        gap = self._px(4)
        for i, source in enumerate(self.cfg["sources"]):
            btn = SourceButton(
                parent, source.get("icon", ""), source.get("label", "?"), self.fonts,
                lambda s=source: self.select_source(s), self.scale, compact,
                tooltip_func=lambda s=source: self._source_tooltip(s),
            )
            if vertical:
                btn.grid(row=i, column=0, sticky="nsew", pady=(0 if i == 0 else gap, 0))
                parent.columnconfigure(0, weight=1)
            else:
                btn.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else gap, 0))
                parent.columnconfigure(i, weight=1, uniform="src")
            self.source_buttons.append(btn)

    def _make_close_button(self, parent) -> tk.Label:
        close = tk.Label(
            parent, text=GLYPH_CLOSE, font=(self.fonts["icon"][0], 8),
            bg=BG, fg=TEXT_DIM, cursor="hand2",
        )
        close.bind("<Button-1>", lambda e: self.quit())
        close.bind("<Enter>", lambda e: close.configure(fg=TEXT))
        close.bind("<Leave>", lambda e: close.configure(fg=TEXT_DIM))
        return close

    def _make_volume_controls(self, parent, slider_length: int, vertical: bool = False) -> None:
        self.mute_label = tk.Label(
            parent, text=GLYPH_VOLUME[3], font=self.fonts["icon"], bg=BG, fg=TEXT,
            cursor="hand2", width=2,
        )
        self.mute_label.bind("<Button-1>", lambda e: self.toggle_mute())
        self.value_label = tk.Label(
            parent, text="--", font=self.fonts["value"], bg=BG, fg=TEXT, width=4,
            anchor="center" if vertical else "e",
        )
        self.slider = Slider(parent, self._px(slider_length), self.scale, self.set_volume, vertical)
        if vertical:  # valeur en haut, barre, haut-parleur en bas
            self.value_label.pack(side="top")
            self.mute_label.pack(side="bottom")
            self.slider.pack(side="top", fill="y", expand=True, pady=self._px(2))
        else:
            self.mute_label.pack(side="left")
            self.value_label.pack(side="right")
            self.slider.pack(side="left", fill="x", expand=True)

    def _build_full(self, body) -> list[tk.Widget]:
        header = tk.Frame(body, bg=BG)
        header.pack(fill="x", padx=self._px(8), pady=(self._px(4), 0))
        title = tk.Label(header, text="Sortie audio", font=self.fonts["small"], bg=BG, fg=TEXT_DIM)
        title.pack(side="left")
        self._make_close_button(header).pack(side="right")

        buttons = tk.Frame(body, bg=BG)
        buttons.pack(fill="x", padx=self._px(8), pady=(self._px(4), 0))
        self._make_source_buttons(buttons, compact=False)

        volume_row = tk.Frame(body, bg=BG)
        volume_row.pack(fill="x", padx=self._px(8), pady=(self._px(6), self._px(8)))
        self._make_volume_controls(volume_row, slider_length=190)
        return [body, header, title, buttons, volume_row, self.value_label]

    def _build_compact(self, body) -> list[tk.Widget]:
        """Une seule ligne : sources en icônes, puis le volume."""
        row = tk.Frame(body, bg=BG)
        row.pack(fill="x", padx=self._px(6), pady=self._px(5))
        buttons = tk.Frame(row, bg=BG)
        buttons.pack(side="left", padx=(0, self._px(6)))
        self._make_source_buttons(buttons, compact=True)
        self._make_volume_controls(row, slider_length=80)
        return [body, row, buttons, self.value_label]

    def _build_vertical(self, body, compact: bool) -> list[tk.Widget]:
        """Une colonne, pour un widget collé au bord gauche ou droit."""
        pad = self._px(6 if compact else 8)
        draggable = [body]
        if not compact:
            header = tk.Frame(body, bg=BG)
            header.pack(fill="x", padx=pad, pady=(self._px(4), 0))
            self._make_close_button(header).pack(side="right")
            draggable.append(header)

        buttons = tk.Frame(body, bg=BG)
        buttons.pack(fill="x", padx=pad, pady=(pad if compact else self._px(2), 0))
        self._make_source_buttons(buttons, compact, vertical=True)

        volume_col = tk.Frame(body, bg=BG)
        volume_col.pack(fill="both", expand=True, padx=pad, pady=(self._px(8), pad))
        self._make_volume_controls(volume_col, slider_length=100 if compact else 130,
                                   vertical=True)
        return draggable + [buttons, volume_col, self.value_label]

    def _build_menu(self) -> None:
        self.topmost_var = tk.BooleanVar(value=bool(self.cfg.get("topmost", True)))
        self.autostart_var = tk.BooleanVar(value=winutil.autostart_enabled())
        self.compact_var = tk.BooleanVar(value=bool(self.cfg.get("compact")))
        self.fade_var = tk.BooleanVar(value=bool(self.cfg.get("fade_when_idle", True)))
        self.vertical_var = tk.BooleanVar(value=bool(self.cfg.get("vertical_on_sides", True)))
        self.auto_var = tk.BooleanVar(value=bool(self.cfg.get("auto_switch", True)))
        m = tk.Menu(self.root, tearoff=False)
        m.add_command(label="Sortie suivante", command=self.next_source)
        self._next_index = m.index("end")
        m.add_checkbutton(
            label=f"Basculer auto sur « {self.cfg.get('auto_switch_source', '')} »",
            variable=self.auto_var, command=lambda: self._set_option("auto_switch", self.auto_var),
        )
        m.add_separator()
        m.add_checkbutton(label="Mode compact (double-clic)", variable=self.compact_var,
                          command=lambda: self.toggle_compact(self.compact_var.get()))
        m.add_checkbutton(label="Vertical sur les bords gauche/droit", variable=self.vertical_var,
                          command=self._toggle_vertical)
        m.add_checkbutton(label="Transparent au repos", variable=self.fade_var,
                          command=lambda: self._set_option("fade_when_idle", self.fade_var))
        m.add_checkbutton(label="Toujours au premier plan", variable=self.topmost_var,
                          command=self._toggle_topmost)
        m.add_checkbutton(label="Lancer au démarrage de Windows", variable=self.autostart_var,
                          command=self._toggle_autostart)
        m.add_separator()
        m.add_command(label="Paramètres son de Windows…",
                      command=lambda: os.startfile("ms-settings:sound"))
        m.add_command(label="Ouvrir le fichier de configuration…",
                      command=lambda: os.startfile(config.CONFIG_PATH))
        m.add_separator()
        m.add_command(label="Quitter", command=self.quit)
        self.menu = m

    # --- Position, aimantation, orientation -------------------------------

    def _place_initially(self) -> None:
        self.root.update_idletasks()
        w, h = self.root.winfo_reqwidth(), self.root.winfo_reqheight()
        pos = self.cfg.get("position")
        if pos and winutil.point_on_screen(pos[0] + w // 2, pos[1] + h // 2):
            x, y = pos
        else:  # par défaut : en bas à droite de l'écran principal
            left, top, right, bottom = winutil.work_area_at(0, 0)
            x, y = right - w - self._px(12), bottom - h - self._px(12)
        self.root.geometry(f"+{x}+{y}")
        self.root.update_idletasks()

    def _geometry(self) -> tuple[int, int, int, int, tuple[int, int, int, int]]:
        x, y = self.root.winfo_x(), self.root.winfo_y()
        w, h = self.root.winfo_reqwidth(), self.root.winfo_reqheight()
        return x, y, w, h, winutil.work_area_at(x + w // 2, y + h // 2)

    def _snap(self, x: int, y: int) -> tuple[int, int]:
        w, h = self.root.winfo_reqwidth(), self.root.winfo_reqheight()
        left, top, right, bottom = winutil.work_area_at(x + w // 2, y + h // 2)
        d = self._px(self.cfg.get("snap_distance", 24))
        if abs(x - left) < d:
            x = left
        elif abs(x + w - right) < d:
            x = right - w
        if abs(y - top) < d:
            y = top
        elif abs(y + h - bottom) < d:
            y = bottom - h
        return x, y

    def _relayout(self) -> None:
        """Reconstruit la fenêtre en gardant collés les bords qui l'étaient."""
        x, y, w, h, (left, top, right, bottom) = self._geometry()
        self._build()
        self.root.update_idletasks()
        nw, nh = self.root.winfo_reqwidth(), self.root.winfo_reqheight()
        if x + w >= right:
            x = right - nw
        if y + h >= bottom:
            y = bottom - nh
        x = max(left, min(x, right - nw))
        y = max(top, min(y, bottom - nh))
        self.root.geometry(f"+{x}+{y}")
        self.root.update_idletasks()
        self._poll(force_devices=True, reschedule=False)
        self.cfg["position"] = [x, y]
        config.save(self.cfg)

    def _update_orientation(self) -> None:
        """Vertical si collé au bord gauche ou droit de l'écran."""
        x, y, w, h, (left, top, right, bottom) = self._geometry()
        vertical = bool(self.cfg.get("vertical_on_sides", True)) and (
            x <= left or x + w >= right
        )
        if vertical != self._vertical:
            self._vertical = vertical
            self._relayout()

    def _start_drag(self, event) -> None:
        self._drag_offset = (event.x_root - self.root.winfo_x(), event.y_root - self.root.winfo_y())

    def _drag(self, event) -> None:
        if self._drag_offset is None:
            return
        x, y = self._snap(event.x_root - self._drag_offset[0], event.y_root - self._drag_offset[1])
        self.root.geometry(f"+{x}+{y}")

    def _end_drag(self, _event) -> None:
        if self._drag_offset is not None:
            self._drag_offset = None
            self.cfg["position"] = [self.root.winfo_x(), self.root.winfo_y()]
            config.save(self.cfg)
            self._update_orientation()

    # --- Actions -----------------------------------------------------------

    def select_source(self, source: dict) -> None:
        device = _find_device(source, self._devices)
        if device is None or not device.active:
            return
        self._safe(self.audio.set_default, device.id)
        self._poll(force_devices=True, reschedule=False)

    def next_source(self) -> None:
        """Passe à la source disponible suivante (raccourci clavier)."""
        self._poll(force_devices=True, reschedule=False)
        available = []
        for source in self.cfg["sources"]:
            device = _find_device(source, self._devices)
            if device is not None and device.active:
                available.append((source, device.id))
        if not available:
            return
        ids = [dev_id for _, dev_id in available]
        i = ids.index(self._default_id) + 1 if self._default_id in ids else 0
        self.select_source(available[i % len(available)][0])
        self._wake()

    def set_volume(self, value: int) -> None:
        if self._muted and value > 0:
            self._safe(self.audio.set_mute, False)
            self._muted = False
        self._safe(self.audio.set_volume, value)
        self._show_volume(value, self._muted)

    def toggle_mute(self) -> None:
        self._safe(self.audio.set_mute, not self._muted)
        self._poll(reschedule=False)

    def _on_wheel(self, event) -> None:
        step = int(self.cfg.get("volume_step", 2))
        notches = event.delta // 120 or (1 if event.delta > 0 else -1)
        value = max(0, min(100, self._volume + notches * step))
        self.set_volume(value)
        self.slider.set(value, self._muted)

    def _show_menu(self, event) -> None:
        self.autostart_var.set(winutil.autostart_enabled())
        hotkey = self.cfg.get("hotkey", "")
        self.menu.entryconfigure(
            self._next_index, accelerator=hotkey if self.hotkey.ok else f"{hotkey} (indisponible)"
        )
        self._menu_open = True  # le menu sort de la fenêtre : ne pas s'estomper
        try:
            self.menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.menu.grab_release()
            self._menu_open = False
            self._last_hover = time.monotonic()

    def toggle_compact(self, compact: bool | None = None) -> None:
        if compact is None:
            compact = not self.cfg.get("compact")
        self.cfg["compact"] = compact
        self.compact_var.set(compact)
        self._drag_offset = None  # le relâchement du double-clic n'arrivera jamais
        self._relayout()

    def _toggle_vertical(self) -> None:
        self._set_option("vertical_on_sides", self.vertical_var)
        self._update_orientation()

    def _set_option(self, key: str, var: tk.BooleanVar) -> None:
        self.cfg[key] = var.get()
        config.save(self.cfg)

    def _toggle_topmost(self) -> None:
        self._set_option("topmost", self.topmost_var)
        self.root.attributes("-topmost", self.cfg["topmost"])

    def _toggle_autostart(self) -> None:
        try:
            winutil.set_autostart(self.autostart_var.get())
        except OSError:
            self.autostart_var.set(winutil.autostart_enabled())

    def quit(self) -> None:
        self.hotkey.stop()
        self.root.destroy()

    # --- Transparence au repos ----------------------------------------------

    def _wake(self) -> None:
        """Rend le widget pleinement visible un instant (changement de sortie)."""
        self._last_hover = time.monotonic() + WAKE_EXTRA_S

    def _pointer_inside(self) -> bool:
        px, py = self.root.winfo_pointerxy()
        x, y = self.root.winfo_rootx(), self.root.winfo_rooty()
        return x <= px < x + self.root.winfo_width() and y <= py < y + self.root.winfo_height()

    def _fade_tick(self) -> None:
        """Estompe le widget quand la souris n'est plus dessus, le fait
        réapparaître dès qu'elle revient. Surveille aussi le raccourci."""
        if self.hotkey.consume():
            self.next_source()
        now = time.monotonic()
        busy = self._menu_open or self._drag_offset is not None or self.slider.dragging
        if busy or self._pointer_inside():
            self._last_hover = max(self._last_hover, now)
        idle = now - self._last_hover > self.cfg.get("fade_delay_ms", 1500) / 1000
        if self.cfg.get("fade_when_idle", True) and idle:
            target = max(0.1, min(1.0, float(self.cfg.get("idle_opacity", 0.35))))
            step = 0.05  # disparition douce
        else:
            target, step = 1.0, 0.2  # réapparition rapide
        if self._alpha != target:
            if abs(target - self._alpha) <= step:
                self._alpha = target
            else:
                self._alpha += step if target > self._alpha else -step
            self.root.attributes("-alpha", self._alpha)
        self.root.after(FADE_TICK_MS if self._alpha != target else HOVER_TICK_MS, self._fade_tick)

    # --- Rafraîchissement ---------------------------------------------------

    def _safe(self, func, *args):
        """Appel audio protégé : une erreur COM (périphérique débranché
        pendant l'appel...) ne doit jamais faire planter le widget."""
        try:
            return func(*args)
        except (COMError, OSError):
            self.audio.reset()
            return None

    def _auto_switch(self, previous_default: str | None) -> None:
        """Bascule sur la source auto (le casque Bluetooth) quand elle se
        connecte, et revient à la sortie d'avant quand elle se déconnecte."""
        label = self.cfg.get("auto_switch_source")
        source = next((s for s in self.cfg["sources"] if s.get("label") == label), None)
        if source is None:
            return
        device = _find_device(source, self._devices)
        active = device is not None and device.active
        was_active, self._auto_active = self._auto_active, active
        if was_active is None or was_active == active or not self.cfg.get("auto_switch", True):
            return  # premier relevé, pas de changement, ou option désactivée

        if active:
            if previous_default != device.id:
                self._before_auto = previous_default
            target = device.id
        elif previous_default == device.id:  # on écoutait dessus
            target = self._fallback_id(exclude=device.id)
            self._before_auto = None
        else:
            return
        if target and target != self._default_id:
            self._safe(self.audio.set_default, target)
            self._default_id = self._safe(self.audio.default_id)
            self._wake()

    def _fallback_id(self, exclude: str) -> str | None:
        active = {d.id for d in self._devices if d.active}
        if self._before_auto in active:
            return self._before_auto
        for source in self.cfg["sources"]:
            device = _find_device(source, self._devices)
            if device is not None and device.active and device.id != exclude:
                return device.id
        return None

    def _poll(self, force_devices: bool = False, reschedule: bool = True) -> None:
        if force_devices or self._tick % DEVICE_POLL_EVERY == 0:
            previous_default = self._default_id
            devices = self._safe(self.audio.devices)
            if devices is not None:
                self._devices = devices
            self._default_id = self._safe(self.audio.default_id)
            self._auto_switch(previous_default)
            for btn, source in zip(self.source_buttons, self.cfg["sources"]):
                device = _find_device(source, self._devices)
                available = device is not None and device.active
                btn.set_state(available and device.id == self._default_id, available)

        if not self.slider.dragging:
            state = self._safe(self.audio.get_volume)
            if state is None:
                self._show_volume(None, False)
            else:
                self._show_volume(*state)
                self.slider.set(*state)

        if reschedule:
            self._tick += 1
            self.root.after(POLL_MS, self._poll)

    def _show_volume(self, value: int | None, muted: bool) -> None:
        if value is None:
            self.value_label.configure(text="--")
            self.mute_label.configure(text=GLYPH_MUTE, fg=TEXT_DIM)
            return
        self._volume, self._muted = value, muted
        if muted:
            glyph = GLYPH_MUTE
        else:
            glyph = GLYPH_VOLUME[0 if value == 0 else 1 if value < 34 else 2 if value < 67 else 3]
        self.mute_label.configure(text=glyph, fg=TEXT_DIM if muted else TEXT)
        self.value_label.configure(text=f"{value}%", fg=TEXT_DIM if muted else TEXT)
