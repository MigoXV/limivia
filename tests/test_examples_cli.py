import subprocess
import sys
from pathlib import Path

import pytest

from examples import _common

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
MODULES = sorted(
    "examples." + ".".join(p.relative_to(EXAMPLES).with_suffix("").parts)
    for p in EXAMPLES.rglob("*.py")
    if not p.name.startswith("_")
)
# 子进程也禁止访问设备，帮助入口回归时不会意外触碰硬件。
PROGRAM = """
import runpy, sys
from limivia.transports import DeviceBackend
def forbidden(*args, **kwargs):
    raise AssertionError("help must not access hardware")
DeviceBackend.discover = forbidden
DeviceBackend.transport = forbidden
sys.argv = [sys.argv[1], *sys.argv[2:]]
runpy.run_module(sys.argv[0], run_name="__main__")
"""


@pytest.mark.parametrize("name", MODULES)
def test_help_does_not_access_hardware(name):
    result = subprocess.run(
        [sys.executable, "-c", PROGRAM, name, "--help"],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "--help" in result.stdout
    assert ("--kind" in result.stdout) == (name == "examples.device.connect")


@pytest.mark.parametrize("name", MODULES)
def test_import_is_offline_and_does_not_configure_logging(name):
    program = """
import importlib, logging, sys
from limivia.transports import DeviceBackend
def forbidden(*args, **kwargs):
    raise AssertionError("import must have no side effects")
logging.basicConfig = forbidden
DeviceBackend.discover = forbidden
DeviceBackend.transport = forbidden
importlib.import_module(sys.argv[1])
"""
    result = subprocess.run(
        [sys.executable, "-c", program, name],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_plain_example_rejects_old_cli_options_before_connecting():
    result = subprocess.run(
        [sys.executable, "-c", PROGRAM, "examples.peripherals.gpio", "--kind", "usb"],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 2
    assert "unrecognized arguments" in result.stderr


def test_runner_parses_help_before_calling_example_or_configuring_logging(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("help must not run example or configure logging")

    monkeypatch.setattr(sys, "argv", ["example", "--help"])
    monkeypatch.setattr("logging.basicConfig", forbidden)
    with pytest.raises(SystemExit) as caught:
        _common.run(forbidden)
    assert caught.value.code == 0
