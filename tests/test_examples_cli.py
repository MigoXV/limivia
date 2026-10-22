import importlib
import subprocess
import sys
from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

from examples import async_adc, sync_state
from limivia import Limivia

from .example_fakes import ExampleBackend


def app_for(module):
    app = typer.Typer()
    app.command()(module.main)
    return app


@pytest.mark.parametrize(
    "module,args",
    [
        ("sync_gpio", ["--mode", "output", "--pull", "up"]),
        ("sync_pwm", ["--breath-ms", "100"]),
        ("async_adc", ["--samples", "0"]),
        ("async_adc", ["--interval-ms", "99"]),
        ("async_events", ["--duration", "0"]),
        ("sync_state", ["--kind", "wifi"]),
    ],
)
def test_invalid_cli_arguments_never_scan(module, args, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("参数不合法时不应扫描设备")

    monkeypatch.setattr("limivia.transports.DeviceBackend.discover", forbidden)
    result = CliRunner().invoke(app_for(importlib.import_module(f"examples.{module}")), args)
    assert result.exit_code == 2, result.output


def test_cli_environment_selection_and_explicit_override(monkeypatch):
    backend = ExampleBackend()
    backend.devices.append({"id": "second", "name": "第二台设备"})
    monkeypatch.setattr(sync_state, "Limivia", lambda: Limivia(backend=backend))
    app = app_for(sync_state)
    runner = CliRunner()
    env = {"LIMIVIA_TRANSPORT": "usb", "LIMIVIA_TARGET": "second"}
    result = runner.invoke(app, [], env=env)
    assert result.exit_code == 0, result.output
    assert backend.scans == ["usb"]
    result = runner.invoke(app, ["--kind", "ble", "--target", "test"], env=env)
    assert result.exit_code == 0, result.output
    assert backend.scans == ["usb", "ble"]


def test_no_device_is_a_readable_nonzero_error(monkeypatch):
    backend = ExampleBackend()
    backend.devices = []
    monkeypatch.setattr(sync_state, "Limivia", lambda: Limivia(backend=backend))
    result = CliRunner().invoke(app_for(sync_state), [])
    assert result.exit_code == 1
    assert "未发现设备" in result.output
    assert "Traceback" not in result.output


def test_async_cli_interrupt_exits_130(monkeypatch):
    async def interrupt(*args):
        raise KeyboardInterrupt

    monkeypatch.setattr(async_adc, "main_async", interrupt)
    result = CliRunner().invoke(app_for(async_adc), [])
    assert result.exit_code == 130
    assert "已中断" in result.output


def test_imports_have_no_logging_or_hardware_side_effects():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import importlib
from pathlib import Path
from unittest.mock import patch

with patch('logging.basicConfig', side_effect=AssertionError('导入时配置日志')), \\
     patch('limivia.transports.DeviceBackend.discover', side_effect=AssertionError('导入时扫描')), \\
     patch('limivia.transports.DeviceBackend.transport', side_effect=AssertionError('导入时连接')):
    for path in Path('examples').glob('*.py'):
        importlib.import_module('examples.' + path.stem)
""",
        ],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr
