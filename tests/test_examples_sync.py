import pytest

from examples import _common
from examples._common import Kind
from limivia import Limivia
from tests.fakes import FakeBackend


def test_resource_example_closes_owned_resource(monkeypatch):
    backend = FakeBackend()
    monkeypatch.setattr(
        _common, "Limivia", lambda: Limivia(backend=backend, job_poll_interval=0.01)
    )
    with _common.connect_sync(Kind.usb, None, control=True) as c:
        with _common.resource_sync(c, "gpio", {"pin": 13}, {"mode": "output"}) as resource:
            assert resource
    assert not backend.connection.resources and backend.connection.closed
    assert [v["op"] for v in backend.connection.commands].count("resource.close") == 1


def test_original_error_is_not_overwritten_by_cleanup_failure(monkeypatch):
    backend = FakeBackend()
    monkeypatch.setattr(
        _common, "Limivia", lambda: Limivia(backend=backend, job_poll_interval=0.01)
    )
    with _common.connect_sync(Kind.usb, None, control=True) as c:
        with pytest.raises(ValueError, match="original"):
            with _common.resource_sync(c, "gpio", {"pin": 13}, {"mode": "output"}):
                backend.connection.refuse = True
                raise ValueError("original")
