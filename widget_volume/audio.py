"""Accès aux sorties audio Windows (API Core Audio, via pycaw/comtypes).

Toutes les méthodes doivent être appelées depuis le thread qui a importé
comtypes (le thread Tk principal), car COM y est initialisé en mode STA.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass

import comtypes
from _ctypes import COMError
from pycaw.constants import DEVICE_STATE, EDataFlow, ERole
from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

# Rôles Windows : "Console" (système), "Multimédia" et "Communications".
# On bascule les trois pour que tout le son suive le périphérique choisi.
_ALL_ROLES = [ERole.eConsole, ERole.eMultimedia, ERole.eCommunications]


@dataclass(frozen=True)
class OutputDevice:
    id: str
    name: str
    active: bool


class AudioController:
    """Liste les sorties, change la sortie par défaut, règle son volume."""

    def __init__(self) -> None:
        self._enum = AudioUtilities.GetDeviceEnumerator()
        self._names: dict[str, str] = {}
        self._volume = None
        self._volume_dev_id: str | None = None

    # --- Périphériques -----------------------------------------------------

    def devices(self) -> list[OutputDevice]:
        """Sorties connues de Windows, hors périphériques fantômes."""
        collection = self._enum.EnumAudioEndpoints(
            EDataFlow.eRender.value, DEVICE_STATE.MASK_ALL.value
        )
        result = []
        for i in range(collection.GetCount()):
            dev = collection.Item(i)
            state = dev.GetState()
            if state & DEVICE_STATE.NOTPRESENT.value:
                continue
            dev_id = dev.GetId()
            result.append(
                OutputDevice(
                    dev_id,
                    self._name_of(dev, dev_id),
                    state == DEVICE_STATE.ACTIVE.value,
                )
            )
        return result

    def default_id(self) -> str | None:
        try:
            return self._enum.GetDefaultAudioEndpoint(
                EDataFlow.eRender.value, ERole.eMultimedia.value
            ).GetId()
        except COMError:  # aucune sortie active
            return None

    def set_default(self, dev_id: str) -> None:
        AudioUtilities.SetDefaultDevice(dev_id, roles=_ALL_ROLES)

    def _name_of(self, dev, dev_id: str) -> str:
        # La lecture des propriétés est coûteuse : on la met en cache.
        name = self._names.get(dev_id)
        if name is None:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                name = AudioUtilities.CreateDevice(dev).FriendlyName or dev_id
            self._names[dev_id] = name
        return name

    # --- Volume de la sortie par défaut ------------------------------------

    def _endpoint_volume(self):
        dev_id = self.default_id()
        if dev_id is None:
            self._volume = self._volume_dev_id = None
            return None
        if dev_id != self._volume_dev_id:
            dev = self._enum.GetDevice(dev_id)
            iface = dev.Activate(IAudioEndpointVolume._iid_, comtypes.CLSCTX_ALL, None)
            self._volume = iface.QueryInterface(IAudioEndpointVolume)
            self._volume_dev_id = dev_id
        return self._volume

    def get_volume(self) -> tuple[int, bool] | None:
        """(volume en %, muet) de la sortie par défaut, ou None."""
        vol = self._endpoint_volume()
        if vol is None:
            return None
        return round(vol.GetMasterVolumeLevelScalar() * 100), bool(vol.GetMute())

    def set_volume(self, percent: int) -> None:
        vol = self._endpoint_volume()
        if vol is not None:
            vol.SetMasterVolumeLevelScalar(max(0, min(100, percent)) / 100, None)

    def set_mute(self, muted: bool) -> None:
        vol = self._endpoint_volume()
        if vol is not None:
            vol.SetMute(int(muted), None)

    def reset(self) -> None:
        """Oublie les interfaces en cache (après une erreur COM)."""
        self._volume = self._volume_dev_id = None
