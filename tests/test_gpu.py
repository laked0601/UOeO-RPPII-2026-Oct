"""Tests for the GPU switch in extract_data.reading.gpu."""

from extract_data.reading import gpu


def test_the_setting_is_put_back_after_the_block(monkeypatch):
    monkeypatch.setattr(gpu, "enabled", True)
    with gpu.setting(False):
        assert gpu.enabled is False
    assert gpu.enabled is True


def test_the_setting_is_put_back_after_an_error(monkeypatch):
    monkeypatch.setattr(gpu, "enabled", True)
    try:
        with gpu.setting(False):
            raise RuntimeError
    except RuntimeError:
        pass
    assert gpu.enabled is True


def test_the_gpu_is_looked_for_only_once():
    gpu.available.cache_clear()
    gpu.available()
    gpu.available()
    assert gpu.available.cache_info().hits >= 1
