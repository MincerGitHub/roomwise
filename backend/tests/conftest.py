"""API contracts never use a developer's paid language-provider configuration."""
import pytest


@pytest.fixture(autouse=True)
def no_paid_language_provider_by_default(monkeypatch, tmp_path):
    monkeypatch.setenv('ROOMWISE_LANGUAGE_PROVIDER', 'disabled')
    monkeypatch.setenv('ROOMWISE_VISION_PROVIDER', 'disabled')
    monkeypatch.setenv('ROOMWISE_VISION_ENV_FILE', str(tmp_path / 'absent-vision.env'))
