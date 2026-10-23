from .._common import Kind, KindOption, TargetOption, connect_sync, execute, wait


def main(kind: KindOption = Kind.usb, target: TargetOption = None):
    with connect_sync(kind, target) as connection:
        snapshot = wait(connection, connection.state.snapshot())
        print(snapshot.to_json())


if __name__ == "__main__":
    execute(main)()
