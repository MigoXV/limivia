import hashlib
import json
import time
import uuid

from ._common import Kind, KindOption, TargetOption, connect_sync, execute, wait


def main(kind: KindOption = Kind.usb, target: TargetOption = None):
    name = f"sdk-demo-{uuid.uuid4().hex[:8]}.flow.json"
    with connect_sync(kind, target, control=True) as c:
        hello = wait(c, c.hello())
        definition = {
            "version": 1,
            "profile": hello.profile,
            "autostart": False,
            "resources": [],
            "variables": {"x": 1},
            "steps": [
                {"op": "delay", "ms": 100},
                {"op": "add", "variable": "x", "value": 1},
                {"op": "end"},
            ],
        }
        data = json.dumps(definition, separators=(",", ":")).encode()
        upload = wait(
            c, c.storage.begin(name=name, size=len(data), sha256=hashlib.sha256(data).hexdigest())
        )
        for offset in range(0, len(data), 384):
            wait(
                c,
                c.storage.chunk(
                    upload_id=upload["upload_id"], offset=offset, data=data[offset : offset + 384]
                ),
            )
        wait(c, c.storage.commit(upload_id=upload["upload_id"]))
        loaded = wait(c, c.flow.load(name=name))
        try:
            wait(c, c.flow.start(flow_id=loaded["flow_id"]))
            time.sleep(0.3)
            print(wait(c, c.flow.get(flow_id=loaded["flow_id"])))
        finally:
            wait(c, c.flow.stop(flow_id=loaded["flow_id"]))
            wait(c, c.flow.remove(flow_id=loaded["flow_id"]))
            wait(c, c.storage.delete(name=name))


if __name__ == "__main__":
    execute(main)()
