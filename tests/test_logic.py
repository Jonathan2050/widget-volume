"""Tests sans matériel audio : python -m unittest discover tests"""

import copy
import tkinter as tk
import unittest
from unittest import mock

from widget_volume import config, ui, winutil
from widget_volume.audio import OutputDevice

SPDIF = OutputDevice("spdif", "Digital Audio (S/PDIF) (High Definition Audio Device)", True)
CASQUE = OutputDevice("casque", "Haut-parleurs (High Definition Audio Device)", True)
YETI = OutputDevice("yeti", "Haut-parleurs (Yeti Stereo Microphone)", True)
BT_HFP = OutputDevice("hfp", "Casque (JBL Endurance Peak 4 Hands-Free)", True)


def bt(active: bool) -> OutputDevice:
    return OutputDevice("bt", "Casque (JBL Endurance Peak 4)", active)


class FakeAudio:
    """Simule Windows : liste de sorties et sortie par défaut."""

    def __init__(self, devices, default):
        self.list, self.default = devices, default

    def devices(self):
        return list(self.list)

    def default_id(self):
        return self.default

    def set_default(self, dev_id):
        self.default = dev_id

    def get_volume(self):
        return 50, False

    def set_volume(self, percent):
        pass

    def set_mute(self, muted):
        pass

    def reset(self):
        pass


class FindDeviceTest(unittest.TestCase):
    def setUp(self):
        self.sources = {s["label"]: s for s in config.DEFAULT_CONFIG["sources"]}

    def test_default_sources(self):
        devices = [YETI, SPDIF, CASQUE, bt(False), BT_HFP]
        self.assertEqual(ui._find_device(self.sources["Enceintes"], devices), SPDIF)
        self.assertEqual(ui._find_device(self.sources["Casque"], devices), CASQUE)
        # le profil "Hands-Free" est exclu, même actif
        self.assertEqual(ui._find_device(self.sources["Bluetooth"], devices), bt(False))

    def test_missing(self):
        self.assertIsNone(ui._find_device(self.sources["Bluetooth"], [SPDIF]))


class HotkeyParseTest(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(winutil.parse_hotkey("Ctrl+Alt+S"), (0x3, ord("S")))
        self.assertEqual(winutil.parse_hotkey("win + f9"), (0x8, 0x78))
        self.assertIsNone(winutil.parse_hotkey("Ctrl+Alt"))
        self.assertIsNone(winutil.parse_hotkey("Ctrl+Pause"))


class WidgetLogicTest(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.cfg = copy.deepcopy(config.DEFAULT_CONFIG)
        self.cfg.update(hotkey="", position=[400, 300])
        patcher = mock.patch.object(config, "save")  # ne pas toucher la vraie config
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        self.root.destroy()

    def make(self, devices, default):
        self.audio = FakeAudio(devices, default)
        self.widget = ui.VolumeWidget(self.root, self.audio, self.cfg)

    def poll_with(self, devices, default=None):
        self.audio.list = devices
        if default is not None:  # Windows change parfois la sortie de lui-même
            self.audio.default = default
        self.widget._poll(force_devices=True, reschedule=False)

    def test_bluetooth_connect_then_disconnect(self):
        self.make([SPDIF, CASQUE, bt(False)], "casque")
        self.poll_with([SPDIF, CASQUE, bt(True)])
        self.assertEqual(self.audio.default, "bt")
        # à la déconnexion Windows choisit n'importe quoi : on revient au casque
        self.poll_with([SPDIF, CASQUE, bt(False)], default="spdif")
        self.assertEqual(self.audio.default, "casque")

    def test_bluetooth_connected_at_startup_falls_back_to_first_source(self):
        self.make([SPDIF, CASQUE, bt(True)], "bt")
        self.poll_with([SPDIF, CASQUE, bt(False)], default="yeti")
        self.assertEqual(self.audio.default, "spdif")

    def test_no_return_if_user_left_bluetooth(self):
        self.make([SPDIF, CASQUE, bt(False)], "spdif")
        self.poll_with([SPDIF, CASQUE, bt(True)])
        self.audio.default = "casque"  # l'utilisateur choisit le casque
        self.poll_with([SPDIF, CASQUE, bt(True)])
        self.poll_with([SPDIF, CASQUE, bt(False)])
        self.assertEqual(self.audio.default, "casque")

    def test_auto_switch_disabled(self):
        self.cfg["auto_switch"] = False
        self.make([SPDIF, CASQUE, bt(False)], "casque")
        self.poll_with([SPDIF, CASQUE, bt(True)])
        self.assertEqual(self.audio.default, "casque")

    def test_next_source_cycles_available_only(self):
        self.make([SPDIF, CASQUE, bt(False)], "spdif")
        self.widget.next_source()
        self.assertEqual(self.audio.default, "casque")
        self.widget.next_source()  # Bluetooth déconnecté : on le saute
        self.assertEqual(self.audio.default, "spdif")


if __name__ == "__main__":
    unittest.main()
