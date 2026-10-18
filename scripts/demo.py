"""Create and edit a demo using only the installed CLI. No SDK required."""

import json
from pathlib import Path
import shutil
import subprocess
import tempfile


def main():
    cli = shutil.which("hammer-agent")
    if not cli:
        raise SystemExit(
            "Install the package and put its Scripts/bin directory on PATH"
        )
    workspace = Path(tempfile.mkdtemp(prefix="hammer-agent-demo-")).resolve()

    def call(*args):
        completed = subprocess.run(
            [cli, "--workspace", str(workspace), "--json", *args],
            capture_output=True,
            text=True,
            check=True,
        )
        result = json.loads(completed.stdout)
        if not result["ok"]:
            raise RuntimeError(result)
        return result["data"]

    created = call("new", "agent_room.vmf", "--template", "csgo-room")
    operations = workspace / "edit.json"
    operations.write_text(
        json.dumps(
            [
                {
                    "op": "add_box",
                    "min": [-64, -64, 0],
                    "max": [64, 64, 64],
                    "material": "dev/dev_measuregeneric01b",
                }
            ]
        )
    )
    edited = call(
        "edit",
        "agent_room.vmf",
        "--expect",
        created["revision"],
        "--ops",
        "@" + str(operations),
    )
    inspected = call("inspect", "agent_room.vmf")
    validation = call("validate", "agent_room.vmf")
    print(
        json.dumps(
            {
                "workspace": str(workspace),
                "map": str(workspace / "agent_room.vmf"),
                "revision": edited["revision"],
                "counts": inspected["counts"],
                "validation": validation,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
