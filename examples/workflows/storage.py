import hashlib
import sys
import uuid

from limivia import Limivia, TransportKind
from limivia.types import BinaryResult

from .._common import run


def main():
    """高级示例：分块上传、校验读回，并删除文件；失败时中止上传。"""
    name = f"sdk-demo-{uuid.uuid4().hex[:8]}.bin"
    data = bytes(range(256)) * 4
    with Limivia.connect(kind=TransportKind.USB) as board:
        upload_id = board.storage.begin(
            name=name, size=len(data), sha256=hashlib.sha256(data).hexdigest()
        ).data["upload_id"]
        committed = False
        try:
            for offset in range(0, len(data), 384):
                board.storage.chunk(
                    upload_id=upload_id, offset=offset, data=data[offset : offset + 384]
                )
            board.storage.commit(upload_id=upload_id)
            committed = True
            result = board.storage.read(name=name, offset=0, length=4096)
            assert BinaryResult.model_validate(result.data).to_bytes() == data
        finally:
            original = sys.exception()
            try:
                if committed:
                    board.storage.delete(name=name)
                else:
                    board.storage.abort(upload_id=upload_id)
            except Exception as error:
                if original is None:
                    raise
                original.add_note(f"上传/文件清理未确认：{error}")


if __name__ == "__main__":
    run(main)
