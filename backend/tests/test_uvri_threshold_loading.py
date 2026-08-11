import json

from backend.metrics import uvri_gate


def test_zero_threshold_falls_back_to_default(tmp_path, monkeypatch):
    config_path = tmp_path / "uvri_threshold.json"
    config_path.write_text(json.dumps({"threshold": 0.0}))

    monkeypatch.setattr(uvri_gate, "_CONFIG_PATH", config_path)
    uvri_gate._load_threshold.cache_clear()

    assert uvri_gate.active_threshold() == uvri_gate.DEFAULT_THRESHOLD
