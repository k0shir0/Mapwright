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
    if "value" in omitted:
        preview["field_complete"] = False
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
        "detail": "Select an omitted field with read_artifact field=NAME and follow next_offset. Read all relevant findings before verification claims; whole-source replacement requires complete source. Raw byte pages and response_mode=full retain the exact result.",
    }
    if omitted:
        preview["response"]["next_call"] = {
            "tool": "read_artifact",
            "arguments": {
                "path": artifact.relative_to(project.root).as_posix(),
                "field": omitted[0],
                "limit": 20,
            },
        }
    for key in sorted(preview, key=lambda k: len(serialized(preview[k])), reverse=True):
        if len(serialized(preview)) <= budget:
            break
        if key not in {
            "response",
            "timeline",
            "valid",
            "complete",
            "field_complete",
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


def read_field(project, source, field, offset=0, limit=20):
    """Select one field without sending unrelated result data to the agent."""
    from .vmf import MapError

    relative = source.relative_to(project.root)
    if (
        relative.parent.as_posix() != ".hammer-agent/results"
        or source.suffix != ".json"
    ):
        raise MapError(
            "Field selection requires an immutable .hammer-agent/results JSON artifact"
        )
    raw = source.read_bytes()
    if digest(raw) != source.stem:
        raise MapError("Immutable result artifact checksum mismatch")
    document = json.loads(raw)
    if field not in document:
        raise MapError(
            f"Unknown result field: {field[:80]}",
            {
                "code": "INVALID_ARGUMENT",
                "hint": "Select a name from response.omitted_fields.",
            },
        )
    value = document[field]
    limit = min(limit, 1000)
    if isinstance(value, dict):
        keys = list(value)[offset : offset + limit]
        page, total, unit = {k: value[k] for k in keys}, len(value), "entries"
    elif isinstance(value, (list, str)):
        page, total = value[offset : offset + limit], len(value)
        unit = "characters" if isinstance(value, str) else "entries"
    else:
        page, total, unit = value if offset == 0 else None, 1, "values"
    next_offset = offset + limit if offset + limit < total else None
    result = {
        "path": relative.as_posix(),
        "revision": source.stem,
        "field": field,
        "value": page,
        "offset": offset,
        "total": total,
        "unit": unit,
        "next_offset": next_offset,
        "field_complete": offset == 0 and next_offset is None,
    }
    if next_offset is not None:
        result["next_call"] = {
            "tool": "read_artifact",
            "arguments": {
                "path": relative.as_posix(),
                "field": field,
                "offset": next_offset,
                "limit": limit,
            },
        }
    return result
