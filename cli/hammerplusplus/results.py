"""Bound transport context while retaining immutable, byte-pageable evidence."""

import json

from .project import atomic_write, digest

MAX_RESULT_BYTES = 32768


def serialized(value):
    return json.dumps(
        value, ensure_ascii=True, allow_nan=False, separators=(",", ":")
    ).encode("ascii")


def bounded(project, result, mode="bounded", budget=MAX_RESULT_BYTES):
    raw = serialized(result)
    if mode == "full" or len(raw) <= budget:
        return result
    revision = digest(raw)
    artifact = project.confined(f".hammer-agent/results/{revision}.json")
    try:
        atomic_write(artifact, raw, exclusive=True)
    except FileExistsError:
        from .streams import file_digest

        if file_digest(artifact) != revision:
            raise ValueError("Immutable result artifact checksum mismatch")
    preview, omitted, counts = {}, [], {}
    for key, value in result.items():
        size = len(serialized(value))
        if size <= 1024:
            preview[key] = value
        else:
            omitted.append(key)
            if isinstance(value, (list, dict, str)):
                counts[key] = len(value)
            if key in {
                "findings",
                "warnings",
                "errors",
                "unsupported_geometry",
            } and isinstance(value, list):
                preview[key] = [
                    (
                        item
                        if len(serialized(item)) <= 1024
                        else {"preview": str(item)[:240]}
                    )
                    for item in value[:3]
                ]
    if "source" in omitted:
        preview["source_complete"] = False
    preview["response"] = {
        "truncated": True,
        "omitted_fields": omitted,
        "totals": counts,
        "artifact": {
            "path": artifact.relative_to(project.root).as_posix(),
            "revision": revision,
            "bytes": len(raw),
            "encoding": "ascii",
        },
        "read_tool": "read_artifact",
        "page_limit": 8000,
        "detail": "Read every byte page of the immutable artifact, or request response_mode=full. Incomplete source cannot be used for whole-source replacement.",
    }
    for key in sorted(preview, key=lambda k: len(serialized(preview[k])), reverse=True):
        if len(serialized(preview)) <= budget:
            break
        if key not in {
            "response",
            "timeline",
            "valid",
            "complete",
            "revision",
            "status",
            "token",
            "recovery_token",
            "action_id",
            "head",
        }:
            preview.pop(key)
            if key not in omitted:
                omitted.append(key)
    return preview
