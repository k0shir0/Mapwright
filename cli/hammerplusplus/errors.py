"""Small, shared failure envelopes for tools and executable scripts."""

import argparse
import json
import subprocess


class AgentError(ValueError):
    def __init__(self, message, details=None):
        super().__init__(message)
        self.details = details or {}


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        raise AgentError(
            message,
            {"code": "INVALID_ARGUMENT", "hint": f"Run {self.prog} --help."},
        )


def error_details(exc):
    if isinstance(exc, (TimeoutError, subprocess.TimeoutExpired)):
        code, hint = (
            "TIMEOUT",
            "Inspect action/process state before retrying a mutation.",
        )
    elif isinstance(exc, FileNotFoundError):
        code, hint = "NOT_FOUND", "Check the path and configured workspace."
    elif isinstance(exc, PermissionError):
        code, hint = "ACCESS_DENIED", "Check access to the named path in this process."
    elif isinstance(exc, ImportError):
        code, hint = (
            "MISSING_DEPENDENCY",
            "Run setup with the checkout's Python environment.",
        )
    elif isinstance(exc, (ValueError, TypeError, KeyError)):
        code, hint = (
            "INVALID_ARGUMENT",
            "Inspect the selected command's schema or --help.",
        )
    else:
        code, hint = (
            "OPERATION_FAILED",
            "Inspect the retained diagnostics before retrying.",
        )
    return {"code": code, "hint": hint, **getattr(exc, "details", {})}


def failure(exc):
    # A task group can wrap the useful tool error in a single-child group.
    while isinstance(exc, BaseExceptionGroup) and len(exc.exceptions) == 1:
        exc = exc.exceptions[0]
    message = str(exc) or type(exc).__name__
    return {"ok": False, "error": message, "details": error_details(exc)}


def emit(result, *, pretty=False, file=None):
    print(
        json.dumps(
            result,
            ensure_ascii=True,
            allow_nan=False,
            indent=2 if pretty else None,
            separators=None if pretty else (",", ":"),
        ),
        file=file,
    )
