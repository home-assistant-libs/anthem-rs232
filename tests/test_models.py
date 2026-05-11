"""Tests for receiver model definitions."""

from anthem_rs232 import AudioListeningMode
from anthem_rs232.models import (
    ALL_MODELS,
    AVM_60,
    MODELS,
    MRX_310,
    MRX_510,
    MRX_520,
    MRX_710,
    MRX_720,
    MRX_1120,
    OTHER,
    ReceiverModel,
)


def test_all_models_have_unique_names():
    names = [m.name for m in ALL_MODELS]
    assert len(names) == len(set(names))


def test_models_dict_keys_match_known_models():
    assert "mrx_1120" in MODELS
    assert MODELS["mrx_1120"] is MRX_1120
    assert MODELS["mrx_710"] is MRX_710
    assert MODELS["other"] is OTHER


def test_mrx_1120_basics():
    assert MRX_1120.name == "MRX 1120"
    assert MRX_1120.zones == 2
    assert MRX_1120.max_inputs == 9
    assert MRX_1120.arc is True
    assert MRX_1120.has_tuner is True
    assert MRX_1120.has_am_tuner is False
    assert MRX_1120.unsupported_startup_queries == frozenset()


def test_avm_60_basics():
    # AVM 60 is the AVP variant in the same family (no power amp).
    assert AVM_60.zones == 2
    assert AVM_60.max_inputs == 9


def test_x10_models_have_am_tuner_and_unsupported_queries():
    # X10 series predates Z1TBS (added in MRX software v1.1.4) and
    # SPN/SSP (added with the X20 protocol). They also support AM tuning.
    for model in (MRX_310, MRX_510, MRX_710):
        assert model.has_am_tuner is True
        assert "Z1TBS" in model.unsupported_startup_queries
        assert "Z2TBS" in model.unsupported_startup_queries
        assert "SPN" in model.unsupported_startup_queries
        assert "SSP" in model.unsupported_startup_queries


def test_models_share_audio_listening_modes():
    for model in (MRX_310, MRX_510, MRX_710, MRX_520, MRX_720, MRX_1120, AVM_60):
        assert AudioListeningMode.DOLBY_SURROUND in model.audio_listening_modes
        assert AudioListeningMode.NONE in model.audio_listening_modes


def test_other_is_a_receiver_model():
    assert isinstance(OTHER, ReceiverModel)
    assert OTHER.max_inputs == 30
