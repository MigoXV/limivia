import importlib
import subprocess
import sys
from pathlib import Path

import pytest

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
MODULES = sorted(
    "examples." + ".".join(p.relative_to(EXAMPLES).with_suffix("").parts)
    for p in EXAMPLES.rglob("*.py")
    if not p.name.startswith("_")
)


@pytest.mark.parametrize("name", MODULES)
def test_help_does_not_access_hardware(name):
    result = subprocess.run(
        [sys.executable, "-m", name, "--help"],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "--kind" in result.stdout


@pytest.mark.parametrize("name", MODULES)
def test_import_is_offline_and_does_not_configure_logging(name, monkeypatch):
    def forbidden(*a, **kw):
        raise AssertionError("import must have no side effects")

    monkeypatch.setattr("logging.basicConfig", forbidden)
    monkeypatch.setattr("limivia.transports.DeviceBackend.discover", forbidden)
    importlib.import_module(name)
