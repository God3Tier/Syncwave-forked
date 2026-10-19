"""Fail when checked-in Python gRPC bindings do not match their proto files."""

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path


def generated_paths(proto: Path) -> tuple[Path, Path]:
    parent = proto.parent
    stem = proto.stem
    return parent / f"{stem}_pb2.py", parent / f"{stem}_pb2_grpc.py"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--proto-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("protos", nargs="+", type=Path)
    arguments = parser.parse_args()

    proto_root = arguments.proto_root.resolve()
    output = arguments.output.resolve()
    proto_files = [(proto_root / proto).resolve() for proto in arguments.protos]

    with tempfile.TemporaryDirectory() as directory:
        generated_root = Path(directory)
        command = [
            sys.executable,
            "-m",
            "grpc_tools.protoc",
            f"-I{proto_root}",
            f"--python_out={generated_root}",
            f"--grpc_python_out={generated_root}",
            *(str(proto) for proto in proto_files),
        ]
        subprocess.run(command, check=True)

        stale: list[Path] = []
        for relative_proto in arguments.protos:
            for relative_binding in generated_paths(relative_proto):
                checked_in = output / relative_binding
                generated = generated_root / relative_binding
                if not checked_in.exists() or checked_in.read_bytes() != generated.read_bytes():
                    stale.append(checked_in)

    if stale:
        print("Python gRPC bindings are missing or stale:", file=sys.stderr)
        for path in stale:
            print(f"  {path}", file=sys.stderr)
        print("Regenerate the bindings before committing.", file=sys.stderr)
        return 1

    print(f"Verified {len(proto_files)} protobuf contract(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
