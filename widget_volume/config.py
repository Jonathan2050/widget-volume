"""Configuration persistante (%APPDATA%\\WidgetVolume\\config.json)."""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path

APP_DIR = Path(os.environ.get("APPDATA", Path.home())) / "WidgetVolume"
CONFIG_PATH = APP_DIR / "config.json"

# Chaque source correspond au premier périphérique dont le nom contient un des
# textes de "match" (sans tenir compte de la casse) et aucun texte de "exclude".
# "icon" est un glyphe de la police Segoe Fluent Icons / Segoe MDL2 Assets.
DEFAULT_CONFIG: dict = {
    "sources": [
        {"label": "Enceintes", "icon": "", "match": ["S/PDIF"], "exclude": []},
        {
            "label": "Casque",
            "icon": "",
            "match": ["Haut-parleurs (High Definition Audio Device)"],
            "exclude": [],
        },
        {"label": "Bluetooth", "icon": "", "match": ["JBL"], "exclude": ["Hands-Free"]},
    ],
    "snap_distance": 24,
    "volume_step": 2,
    "position": None,
    "topmost": True,
    "compact": False,
    "fade_when_idle": True,  # s'estompe quand la souris n'est pas dessus
    "idle_opacity": 0.35,  # opacité au repos (0.1 à 1)
    "fade_delay_ms": 1500,  # délai avant de s'estomper
    "vertical_on_sides": True,  # format vertical quand collé à gauche ou à droite
    "hotkey": "Ctrl+Alt+S",  # sortie suivante, depuis n'importe quelle application
    # Bascule sur cette source quand elle se connecte, et revient à la
    # précédente quand elle se déconnecte.
    "auto_switch": True,
    "auto_switch_source": "Bluetooth",
}


def load() -> dict:
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    try:
        with CONFIG_PATH.open(encoding="utf-8") as f:
            cfg.update(json.load(f))
    except FileNotFoundError:
        save(cfg)
    except (OSError, ValueError):
        pass  # fichier illisible : on garde les valeurs par défaut
    return cfg


def save(cfg: dict) -> None:
    try:
        APP_DIR.mkdir(parents=True, exist_ok=True)
        tmp = CONFIG_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(CONFIG_PATH)
    except OSError:
        pass
