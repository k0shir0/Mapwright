"""Bounded-memory hashing and verified, atomic stream publication."""

import hashlib
import os
from pathlib import Path
import tempfile

BUFFER = 1024 * 1024


def copy_hash(source, output=None):
    checksum = hashlib.sha256()
    for block in iter(lambda: source.read(BUFFER), b""):
        checksum.update(block)
        if output is not None:
            output.write(block)
    return checksum.hexdigest()


def file_digest(path):
    with Path(path).open("rb") as source:
        return copy_hash(source)


def publish_stream(path, source, *, expected=None, exclusive=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".hammer-agent-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as output:
            revision = copy_hash(source, output)
            output.flush()
            os.fsync(output.fileno())
        if expected is not None and revision != expected:
            raise ValueError(
                "Stream checksum mismatch; incomplete output was discarded"
            )
        if exclusive:
            os.link(temporary, path)
        else:
            os.replace(temporary, path)
        return revision
    finally:
        Path(temporary).unlink(missing_ok=True)
