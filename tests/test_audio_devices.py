from friday.adapters.audio_io import AudioDevice, device_names, match_device

MME, DS, WASAPI, WDMKS = "MME", "Windows DirectSound", "Windows WASAPI", "Windows WDM-KS"


def _in(index: int, name: str, hostapi: str) -> AudioDevice:
    return AudioDevice(index, name, hostapi, max_input_channels=2, max_output_channels=0)


def _out(index: int, name: str, hostapi: str) -> AudioDevice:
    return AudioDevice(index, name, hostapi, max_input_channels=0, max_output_channels=2)


# Real listing observed with the USB headset plugged in (MME truncates to 31 chars).
PLUGGED = [
    _in(0, "Mappeur de sons Microsoft - Input", MME),
    _in(1, "Microphone sur casque (2- USB A", MME),
    _in(2, "Microphone (USB Live camera aud", MME),
    _out(5, "Casque (3- USB Audio Device)", MME),
    _out(7, "Casque pour téléphone (A50 X Vo", MME),
    _in(9, "Pilote de capture audio principal", DS),
    _in(10, "Microphone sur casque (2- USB Audio Device)", DS),
    _in(11, "Microphone (USB Live camera audio)", DS),
    _out(16, "Casque pour téléphone (A50 X Voice)", DS),
    _in(22, "Microphone sur casque (2- USB Audio Device)", WASAPI),
    _in(26, "Microphone ()", WDMKS),
]

# Same machine after unplugging the headset: every index has shifted.
UNPLUGGED = [
    _in(0, "Mappeur de sons Microsoft - Input", MME),
    _in(1, "Microphone (USB Live camera aud", MME),
    _in(6, "Microphone (USB Live camera audio)", DS),
    _in(12, "Microphone (USB Live camera audio)", WASAPI),
]


def test_exact_name_prefers_directsound() -> None:
    assert match_device("Microphone sur casque (2- USB Audio Device)", PLUGGED, "input") == 10


def test_partial_name_ignores_case_and_accents() -> None:
    assert match_device("usb live camera", PLUGGED, "input") == 11
    assert match_device("casque pour telephone", PLUGGED, "output") == 16


def test_same_name_follows_the_device_when_indices_shift() -> None:
    assert match_device("Microphone (USB Live camera audio)", PLUGGED, "input") == 11
    assert match_device("Microphone (USB Live camera audio)", UNPLUGGED, "input") == 6


def test_unplugged_or_empty_name_falls_back_to_default() -> None:
    assert match_device("Microphone sur casque", UNPLUGGED, "input") is None
    assert match_device(None, PLUGGED, "input") is None
    assert match_device("  ", PLUGGED, "input") is None


def test_kind_is_respected() -> None:
    assert match_device("Casque (3- USB Audio Device)", PLUGGED, "input") is None


def test_device_names_are_unique_full_and_physical() -> None:
    assert device_names(PLUGGED, "input") == [
        "Microphone (USB Live camera audio)",
        "Microphone sur casque (2- USB Audio Device)",
    ]
    assert device_names(PLUGGED, "output") == [
        "Casque (3- USB Audio Device)",
        "Casque pour téléphone (A50 X Voice)",
    ]
