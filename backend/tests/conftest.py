"""API contracts never use a developer's paid language-provider configuration."""
import pytest


@pytest.fixture(autouse=True)
def no_paid_language_provider_by_default(monkeypatch):
    monkeypatch.setenv('ROOMWISE_LANGUAGE_PROVIDER', 'disabled')
