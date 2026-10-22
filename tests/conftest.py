import pytest


@pytest.fixture(autouse=True)
def local_mode_for_existing_ui_tests(monkeypatch):
    # Cloud tests opt into cloud explicitly. Existing tests exercise local UI.
    monkeypatch.setenv('PAYROLL_MODE', 'local')
