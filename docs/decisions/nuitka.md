# Nuitka build decision

DataCompiler builds its distribution with Nuitka. The build backend is
`nuitka.distutils.Build`, provided by `nuitka[build-wheel]`, and the current
configuration in `pyproject.toml` enables the NumPy plugin, removes build
output, disables docstrings and assertions in the compiled application, and
prevents following selected optional or development imports.

This is a packaging and distribution choice, not a confidentiality or security
boundary. The repository remains public, so its readable source is available
in Git history and archives; compiled binaries may also be inspected or
reverse-engineered. Nuitka does not replace a license or protect public source
from disclosure.

Keep the source distribution and compiled wheel aligned with the current
configuration. Revisit the build approach if supported platforms or release
requirements change, but do not rewrite public Git history or claim that
compilation makes the source confidential.
