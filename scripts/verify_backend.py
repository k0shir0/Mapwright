"""Opt-in actual backend test. Missing SDK tools fail, never skip or simulate."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts._support import JsonArgumentParser, report_failure, run

import uuid

from cli.hammerplusplus.backend import compile_map, load_config
from cli.hammerplusplus.project import Project


def main():
    parser = JsonArgumentParser(description=__doc__)
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
        return compile_map(
            project, load_config(project, args.config), name, created["revision"]
        )
    except (ValueError, OSError) as exc:
        return report_failure(exc, {"vmf": str(project.map_path(name))})


if __name__ == "__main__":
    raise SystemExit(run(main))
