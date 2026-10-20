# PyArmor decision

The source repository is public. Obfuscating Python files in that repository
would not make the source confidential: the readable source remains available
in Git history and archives. PyArmor is relevant only if the project later
ships a separate obfuscated distribution and has a concrete licensing or
commercial requirement.

For now, do not add PyArmor to the development environment, build pipeline, or
release artifacts. Revisit this decision only after defining the protected
distribution, supported platforms and Python versions, and how users will
install and troubleshoot it. Evaluate the current PyArmor licensing and its
verification/network requirements at that time; do not treat obfuscation as a
security boundary or as a replacement for a software license.

This decision applies to the public source release and can be superseded if
the project adopts a separate closed-source distribution model.
