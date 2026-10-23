import hashlib

from limivia.types import BinaryResult

from ._common import Kind, KindOption, TargetOption, connect_sync, execute, wait


def main(kind: KindOption = Kind.usb, target: TargetOption = None):
    import uuid

    name = f"sdk-demo-{uuid.uuid4().hex[:8]}.bin"
    data = bytes(range(256)) * 4
    with connect_sync(kind, target, control=True) as c:
        begin = wait(
            c, c.storage.begin(name=name, size=len(data), sha256=hashlib.sha256(data).hexdigest())
        )
        committed = False
        try:
            for offset in range(0, len(data), 384):
                wait(
                    c,
                    c.storage.chunk(
                        upload_id=begin["upload_id"],
                        offset=offset,
                        data=data[offset : offset + 384],
                    ),
                )
            wait(c, c.storage.commit(upload_id=begin["upload_id"]))
            committed = True
            assert (
                BinaryResult.model_validate(
                    wait(c, c.storage.read(name=name, offset=0, length=4096))
                ).to_bytes()
                == data
            )
        finally:
            if committed:
                wait(c, c.storage.delete(name=name))
            else:
                wait(c, c.storage.abort(upload_id=begin["upload_id"]))


if __name__ == "__main__":
    execute(main)()
