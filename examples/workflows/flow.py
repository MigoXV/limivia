import hashlib
import json
import sys
import uuid
from time import sleep

from limivia import Limivia, TransportKind
from limivia.constants import FlowStep

from .._common import run


def main():
    """高级示例：上传、启动、查询流程，最后停止流程并清理文件。"""
    name = f"sdk-demo-{uuid.uuid4().hex[:8]}.flow.json"
    with Limivia.connect(kind=TransportKind.USB) as board:
        assert board.identity is not None
        definition = {
            "version": 1,
            "profile": board.identity.profile,
            "autostart": False,
            "resources": [],
            "variables": {"x": 1},
            "steps": [
                {"op": FlowStep.DELAY, "ms": 100},
                {"op": FlowStep.ADD, "variable": "x", "value": 1},
                {"op": FlowStep.END},
            ],
        }
        data = json.dumps(definition, separators=(",", ":")).encode()
        upload_id = board.storage.begin(
            name=name, size=len(data), sha256=hashlib.sha256(data).hexdigest()
        ).data["upload_id"]
        committed = False
        flow_id = None
        try:
            for offset in range(0, len(data), 384):
                board.storage.chunk(
                    upload_id=upload_id, offset=offset, data=data[offset : offset + 384]
                )
            board.storage.commit(upload_id=upload_id)
            committed = True
            flow_id = board.flow.load(name=name).data["flow_id"]
            board.flow.start(flow_id=flow_id)
            sleep(0.3)
            print(board.flow.get(flow_id=flow_id).to_json())
        finally:
            original = sys.exception()
            try:
                if flow_id is not None:
                    board.flow.stop(flow_id=flow_id)
                    board.flow.remove(flow_id=flow_id)
                if committed:
                    board.storage.delete(name=name)
                else:
                    board.storage.abort(upload_id=upload_id)
            except Exception as error:
                if original is None:
                    raise
                original.add_note(f"流程/文件清理未确认：{error}")


if __name__ == "__main__":
    run(main)
