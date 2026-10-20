# Python naming and API compatibility

## Public names

New public APIs use English `snake_case` names. Existing French names remain
available as compatibility aliases for the 0.x series. Do not rename a public
name in place or remove its alias in a minor release without a deprecation
period and a major-version plan.

## Internal names

A single leading underscore marks a module or class implementation detail, for
example `_load_engine`. It is a convention, not access control, encryption, or
confidentiality. Do not use a leading underscore to claim that source code is
private or protected.

A double leading underscore inside a class triggers Python name mangling. Use it
only to avoid accidental subclass name collisions when that is specifically
needed; it does not provide security. Keep double-underscore names for Python's
reserved data model methods (such as `__init__` and `__getattr__`) exactly as
required by the language. Do not invent dunder names for ordinary helpers.

## Migration

When translating an API, introduce and document its English name, preserve the
existing name as an alias, and test both resolve to the same behavior. Rename
private helpers incrementally, updating imports and tests in the same change.
Avoid broad textual replacement: names can be part of serialized data, plugins,
CLI output, or downstream imports.
