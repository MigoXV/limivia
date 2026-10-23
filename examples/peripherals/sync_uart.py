from limivia.types import BinaryResult

from .._common import Kind, KindOption, TargetOption, connect_sync, execute, resource_sync, wait


def main(kind: KindOption = Kind.usb, target: TargetOption = None):
    with (
        connect_sync(kind, target, control=True) as c,
        resource_sync(c, "uart", {"tx": 20, "rx": 21}, {"loopback": True}) as resource,
    ):
        wait(c, c.resource.call(resource=resource, action="write", args={"data": b"limivia-v3"}))
        wait(c, c.resource.call(resource=resource, action="drain", args={}))
        data = wait(c, c.resource.call(resource=resource, action="read", args={"length": 10}))
        print(BinaryResult.model_validate(data).to_bytes())


if __name__ == "__main__":
    execute(main)()
