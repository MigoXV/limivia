"""故障注入只检验全局恢复编排，不连接设备或调用固件工具。"""

from types import SimpleNamespace

from scripts import verify_sdk_hardware as runner


def test_global_finally_restores_bus_after_a_failed_ota(tmp_path, monkeypatch):
    state = {"profile": "bus"}
    calls = []

    async def probe(args, manifest, report):
        return {"profile": state["profile"], "build_id": state["profile"]}

    def ota(args, profile, label):
        calls.append((profile, label))
        state["profile"] = profile
        if profile == "signal":
            raise RuntimeError("original OTA failure")

    async def profile(args, manifest, name):
        return {"profile": name, "status": "passed", "cleanup": {"status": "confirmed"}}

    async def cleanup(args, manifest):
        assert state["profile"] == "bus"
        return {"status": "confirmed"}

    monkeypatch.setattr(runner, "probe", probe)
    monkeypatch.setattr(runner, "ota", ota)
    monkeypatch.setattr(runner, "run_profile", profile)
    monkeypatch.setattr(runner, "final_cleanup", cleanup)
    args = SimpleNamespace(output=tmp_path)
    manifest = {"images": {p: {"build_id": p} for p in ("bus", "signal", "iot")}}
    report = {"profiles": []}
    assert runner.execute(args, manifest, report) == 1
    assert calls == [("signal", "switch"), ("bus", "restore")]
    assert "original OTA failure" in report["error"]
    assert report["restore"]["status"] == "confirmed"


def test_finally_tries_firmware_identity_check_when_sdk_probe_fails(tmp_path, monkeypatch):
    calls = []

    async def probe(*args):
        raise TimeoutError("SDK link lost")

    def ota(args, profile, label):
        calls.append((profile, label))
        raise TimeoutError("firmware identity also unavailable")

    monkeypatch.setattr(runner, "probe", probe)
    monkeypatch.setattr(runner, "ota", ota)
    report = {"profiles": []}
    manifest = {"images": {"bus": {"build_id": "bus"}}}
    assert runner.execute(SimpleNamespace(output=tmp_path), manifest, report) == 1
    assert calls == [("bus", "restore")]
    assert "SDK link lost" in report["error"]
    assert report["restore"]["status"] == "unknown"
    assert "firmware identity" in report["restore"]["error"]
