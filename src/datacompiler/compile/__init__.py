"""Compilation API, loaded only when its public resolver is requested."""

from importlib import import_module

__all__ = ["resolve_document", "resoudre"]


def __getattr__(name):
    if name not in {"resolve_document", "resoudre"}:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module("datacompiler.compile.compiler"), "resoudre")
    globals()[name] = value
    return value
