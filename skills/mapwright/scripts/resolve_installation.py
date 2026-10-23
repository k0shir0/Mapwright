"""Resolve an installed skill without trusting stale machine paths."""

import argparse
import json
from pathlib import Path


def resolve(skill):
    marker = skill / "installation.json"
    if not marker.is_file():
        return {
            "ok": False,
            "error": "Installation metadata is missing",
            "details": {
                "code": "INSTALLATION_MISSING",
                "hint": "Locate the Mapwright checkout and run scripts/setup_agent.py for this client.",
            },
        }
    try:
        metadata = json.loads(marker.read_text("utf-8"))
        if not isinstance(metadata, dict):
            raise ValueError("Installation metadata must be an object")
        missing = [
            key
            for key in ("checkout", "workspace", "command", "setup_script")
            if not isinstance(metadata.get(key), str)
            or not Path(metadata[key]).is_absolute()
            or not (
                Path(metadata[key]).is_dir()
                if key in {"checkout", "workspace"}
                else Path(metadata[key]).is_file()
            )
        ]
    except (ValueError, OSError) as exc:
        return {
            "ok": False,
            "error": str(exc),
            "details": {
                "code": "INVALID_INSTALLATION",
                "hint": "Rerun setup from the current checkout.",
            },
        }
    if missing:
        return {
            "ok": False,
            "error": "Installation paths are stale",
            "details": {
                "code": "STALE_INSTALLATION",
                "fields": missing,
                "hint": "Locate the current checkout; recreate its venv and rerun scripts/setup_agent.py with the intended workspace/client.",
            },
        }
    return {"ok": True, "data": metadata}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--skill-dir", type=Path, default=Path(__file__).resolve().parents[1]
    )
    result = resolve(parser.parse_args().skill_dir)
    print(json.dumps(result, separators=(",", ":")))
    raise SystemExit(0 if result["ok"] else 1)
