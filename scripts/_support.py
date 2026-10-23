"""Consistent script output, retained diagnostics and bounded verification."""

import json
from pathlib import Path
import sys
import traceback
import uuid

from cli.hammerplusplus.errors import (
    AgentError,
    JsonArgumentParser as ErrorParser,
    emit,
    failure,
)

DEBUG = False


class JsonArgumentParser(ErrorParser):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.add_argument(
            "--debug",
            action="store_true",
            help="Also print the retained failure traceback to stderr",
        )


def report_failure(exc, details=None):
    result = failure(exc)
    if details:
        result["details"].update(details)
    trace = "".join(traceback.format_exception(exc))
    workspace = Path.cwd()
    for i, value in enumerate(sys.argv[1:], 1):
        if value == "--workspace" and i + 1 < len(sys.argv):
            workspace = Path(sys.argv[i + 1])
        elif value.startswith("--workspace="):
            workspace = Path(value.split("=", 1)[1])
    try:
        if workspace.is_dir():
            artifact = workspace / ".local/script-errors" / (uuid.uuid4().hex + ".json")
            artifact.parent.mkdir(parents=True, exist_ok=True)
            artifact.write_text(
                json.dumps({**result, "traceback": trace}, indent=2), encoding="utf-8"
            )
            result["details"]["diagnostic"] = str(artifact.resolve())
    except OSError:
        pass  # Reporting the original failure must not depend on writable logs.
    if DEBUG:
        print(trace, file=sys.stderr)
    if len(result["error"]) > 2048:
        result["error"] = result["error"][:2048] + " (full error in diagnostic)"
    emit(result)
    return 1


def run(main):
    global DEBUG
    DEBUG = "--debug" in sys.argv
    if DEBUG:
        sys.argv.remove("--debug")
    try:
        result = main()
        if isinstance(result, dict):
            emit({"ok": True, "data": result})
            return 0
        return result or 0
    except Exception as exc:
        return report_failure(exc)


def verify(scenario, report, output, timeout=600):
    import anyio

    async def bounded():
        with anyio.fail_after(timeout):
            await scenario()

    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        anyio.run(bounded)
    except Exception as exc:
        report["failure"] = failure(exc)
        raise AgentError(
            report["failure"]["error"],
            {
                **report["failure"]["details"],
                "receipt": str(output),
            },
        ) from exc
    finally:
        output.write_text(json.dumps(report, indent=2), encoding="utf-8")
