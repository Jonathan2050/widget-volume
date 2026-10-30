"""Point d'entrée du Widget Volume."""

import sys
import tkinter as tk

from widget_volume import config, winutil
from widget_volume.audio import AudioController
from widget_volume.ui import VolumeWidget


def main() -> int:
    if not winutil.acquire_single_instance():
        return 0  # déjà lancé
    winutil.enable_dpi_awareness()
    root = tk.Tk()
    VolumeWidget(root, AudioController(), config.load())
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
