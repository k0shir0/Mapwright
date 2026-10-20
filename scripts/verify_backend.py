"""Opt-in actual backend test. Missing SDK tools fail, never skip or simulate."""

import argparse
import json
from pathlib import Path
import sys
import uuid

from cli.hammerplusplus.backend import BackendError, compile_map, load_config
from cli.hammerplusplus.project import Project


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workspace",
        default=".",
        help="Existing Mapwright workspace containing native configuration",
    )
    parser.add_argument(
        "--config",
        default="mapwright.local.json",
        help="Native tool configuration relative to the workspace",
    )
    args = parser.parse_args()
    project = Project(args.workspace)
    name = f".local/backend-verification/{uuid.uuid4().hex}/agent_room.vmf"
    created = project.create(name, "csgo-room")
    try:
        result = compile_map(
            project, load_config(project, args.config), name, created["revision"]
        )
    except (ValueError, OSError) as exc:
        result = {"ok": False, "error": str(exc), "vmf": str(project.map_path(name))}
        if isinstance(exc, BackendError):
            result["details"] = exc.details
        print(json.dumps(result, indent=2))
        return 1
    print(json.dumps({"ok": True, "data": result}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
