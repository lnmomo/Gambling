import pytest

from football_agents.db import Database
from football_agents.shadow_prediction_store import ShadowPredictionStore
from football_agents.true_odds_config import get_default_true_odds_filter_config


def test_config_version_lifecycle_and_confirm_gate(tmp_path):
    database = Database(tmp_path / "store.db")
    database.initialize()
    store = ShadowPredictionStore(database)
    version = store.create_config_version(get_default_true_odds_filter_config(), name="v1")
    assert version.status == "DRAFT"
    started = store.start_shadow_validation(version.config_version_id)
    assert started.status == "SHADOW_RUNNING"
    with pytest.raises(PermissionError):
        store.activate_filter_only(version.config_version_id, confirm=False)
    started.promotion_status = "ENABLE_FILTER_ONLY_RECOMMENDED"
    store.save_config_version(started)
    active = store.activate_filter_only(version.config_version_id, confirm=True)
    assert active.status == "ACTIVE_FILTER_ONLY"


def test_adjust_probability_cannot_activate(tmp_path):
    database = Database(tmp_path / "store2.db")
    database.initialize()
    config = get_default_true_odds_filter_config()
    config.mode = "ADJUST_PROBABILITY"
    store = ShadowPredictionStore(database)
    version = store.create_config_version(config, name="bad")
    version.promotion_status = "ENABLE_FILTER_ONLY_RECOMMENDED"
    store.save_config_version(version)
    with pytest.raises(ValueError):
        store.activate_filter_only(version.config_version_id, confirm=True)
