"""Composants graphiques : bouton de source, barre de volume, infobulle."""

from __future__ import annotations

import tkinter as tk

from . import winutil

BG = "#1e2026"
BORDER = "#3a3e48"
BTN = "#2a2d35"
BTN_HOVER = "#353944"
BTN_SELECTED = "#2d5ea8"
TEXT = "#e8e9ec"
TEXT_DIM = "#6d727d"
ACCENT = "#4c9aff"
TRACK = "#3a3e48"
TIP_BG = "#2b2e36"


class Tooltip:
    """Petite bulle d'aide affichée après un court survol."""

    def __init__(self, owner: tk.Widget, text_func, delay_ms: int = 450):
        self._owner = owner
        self._text_func = text_func
        self._delay = delay_ms
        self._after = None
        self._tip: tk.Toplevel | None = None

    def attach(self, *widgets: tk.Widget) -> None:
        for w in widgets:
            w.bind("<Enter>", self._on_enter, add="+")
            w.bind("<Leave>", self._on_leave, add="+")
            w.bind("<Button-1>", lambda e: self.hide(), add="+")

    def _pointer_inside(self) -> bool:
        o = self._owner
        px, py = o.winfo_pointerxy()
        x, y = o.winfo_rootx(), o.winfo_rooty()
        return x <= px < x + o.winfo_width() and y <= py < y + o.winfo_height()

    def _on_enter(self, _event) -> None:
        if self._after is None and self._tip is None:
            self._after = self._owner.after(self._delay, self._show)

    def _on_leave(self, _event) -> None:
        # Passer d'un sous-élément du bouton à un autre déclenche aussi <Leave>.
        self._owner.after(30, lambda: None if self._pointer_inside() else self.hide())

    def hide(self) -> None:
        if self._after is not None:
            self._owner.after_cancel(self._after)
            self._after = None
        if self._tip is not None:
            self._tip.destroy()
            self._tip = None

    def _show(self) -> None:
        self._after = None
        if not self._pointer_inside():
            return
        tip = self._tip = tk.Toplevel(self._owner)
        tip.overrideredirect(True)
        tip.attributes("-topmost", True)
        tip.configure(bg=BORDER)
        tk.Label(
            tip, text=self._text_func(), bg=TIP_BG, fg=TEXT, font=("Segoe UI", 9),
            justify="left", padx=8, pady=4,
        ).pack(padx=1, pady=1)
        tip.update_idletasks()
        # À côté du bouton, du côté où il y a de la place.
        o = self._owner
        tw, th = tip.winfo_reqwidth(), tip.winfo_reqheight()
        ox, oy, ow, oh = o.winfo_rootx(), o.winfo_rooty(), o.winfo_width(), o.winfo_height()
        left, top, right, bottom = winutil.work_area_at(ox + ow // 2, oy + oh // 2)
        x, y = ox + (ow - tw) // 2, oy + oh + 4  # dessous
        if y + th > bottom:
            y = oy - th - 4  # dessus
        if o.winfo_toplevel().winfo_height() > o.winfo_toplevel().winfo_width():
            # widget vertical : la bulle va sur le côté libre
            y = oy + (oh - th) // 2
            x = ox + ow + 6 if ox + ow + 6 + tw <= right else ox - tw - 6
        x = max(left, min(x, right - tw))
        y = max(top, min(y, bottom - th))
        tip.geometry(f"+{x}+{y}")


class SourceButton(tk.Frame):
    def __init__(self, master, icon: str, label: str, fonts, command, scale: float,
                 compact: bool = False, tooltip_func=None):
        super().__init__(master, bg=BTN, cursor="hand2")
        self._command = command
        self._selected = False
        self._available = True
        pad = round(6 * scale)
        if compact:  # icône seule
            self._icon = tk.Label(self, text=icon, font=fonts["icon"], bg=BTN, fg=TEXT)
            self._icon.pack(padx=pad, pady=round(4 * scale))
            self._widgets = (self, self._icon)
        else:
            self._icon = tk.Label(self, text=icon, font=fonts["icon_big"], bg=BTN, fg=TEXT)
            self._icon.pack(pady=(pad, 0))
            self._text = tk.Label(self, text=label, font=fonts["small"], bg=BTN, fg=TEXT)
            self._text.pack(pady=(0, pad), padx=pad)
            self._widgets = (self, self._icon, self._text)
        for w in self._widgets:
            w.bind("<Button-1>", self._on_click)
            w.bind("<Enter>", lambda e: self._paint(hover=True))
            w.bind("<Leave>", lambda e: self._paint(hover=False))
        if tooltip_func is not None:
            Tooltip(self, tooltip_func).attach(*self._widgets)

    def set_state(self, selected: bool, available: bool) -> None:
        if (selected, available) != (self._selected, self._available):
            self._selected, self._available = selected, available
            self._paint(hover=False)

    def _on_click(self, _event) -> None:
        if self._available and not self._selected:
            self._command()

    def _paint(self, hover: bool) -> None:
        if self._selected:
            bg = BTN_SELECTED
        elif hover and self._available:
            bg = BTN_HOVER
        else:
            bg = BTN
        fg = TEXT if self._available else TEXT_DIM
        cursor = "hand2" if self._available and not self._selected else "arrow"
        for w in self._widgets:
            w.configure(bg=bg, cursor=cursor)
            if w is not self:
                w.configure(fg=fg)


class Slider(tk.Canvas):
    """Barre de volume 0-100 dessinée à la main (plus jolie que ttk.Scale).

    En vertical, 0 est en bas et 100 en haut.
    """

    def __init__(self, master, length: int, scale: float, on_change, vertical: bool = False):
        self._thick = round(22 * scale)
        self._vertical = vertical
        width, height = (self._thick, length) if vertical else (length, self._thick)
        super().__init__(
            master, width=width, height=height, bg=BG, highlightthickness=0, cursor="hand2"
        )
        self._length = length
        self._pad = round(8 * scale)
        self._track_w = max(2, round(4 * scale))
        self._knob_r = round(7 * scale)
        self._on_change = on_change
        self._value = 0
        self._muted = False
        self.dragging = False
        self.bind("<Button-1>", self._on_press)
        self.bind("<B1-Motion>", self._on_drag)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<Configure>", self._on_resize)
        self._redraw()

    def _on_resize(self, event) -> None:
        length = event.height if self._vertical else event.width
        if length != self._length:
            self._length = length
            self._redraw()

    def set(self, value: int, muted: bool) -> None:
        if not self.dragging and (value, muted) != (self._value, self._muted):
            self._value, self._muted = value, muted
            self._redraw()

    def _value_at(self, event) -> int:
        pos = self._length - event.y if self._vertical else event.x
        frac = (pos - self._pad) / (self._length - 2 * self._pad)
        return round(max(0.0, min(1.0, frac)) * 100)

    def _on_press(self, event) -> None:
        self.dragging = True
        self._on_drag(event)

    def _on_drag(self, event) -> None:
        value = self._value_at(event)
        if value != self._value:
            self._value = value
            self._redraw()
            self._on_change(value)

    def _on_release(self, _event) -> None:
        self.dragging = False

    def _point(self, along: float) -> tuple[float, float]:
        """Position le long de la barre -> coordonnées du canevas."""
        c = self._thick // 2
        return (c, self._length - along) if self._vertical else (along, c)

    def _redraw(self) -> None:
        self.delete("all")
        a0, a1 = self._pad, self._length - self._pad
        av = a0 + (a1 - a0) * self._value / 100
        fill = TEXT_DIM if self._muted else ACCENT
        line = dict(width=self._track_w, capstyle="round")
        self.create_line(*self._point(a0), *self._point(a1), fill=TRACK, **line)
        if self._value > 0:
            self.create_line(*self._point(a0), *self._point(av), fill=fill, **line)
        x, y = self._point(av)
        r = self._knob_r
        self.create_oval(x - r, y - r, x + r, y + r, fill=TEXT, outline=fill, width=2)
