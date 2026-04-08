# Security Policy

## Reporting a Vulnerability

Please avoid opening a public issue for security-sensitive problems right away.

Examples:

- unsafe editor code execution paths
- destructive scene or asset operations that can be triggered unexpectedly
- bridge exposure beyond intended localhost boundaries
- command injection or unsafe parameter handling
- secrets or token leakage in logs or output

If possible, send the report privately through the repository contact method or GitHub security reporting when the repo is public.

## What to Include

Please include:

- what you found
- the affected command or workflow
- steps to reproduce
- expected impact
- any workaround or mitigation you found

## Scope Notes

This repo is a CLI client for a local Unity bridge. Some security issues may actually belong to the Unity plugin or another upstream dependency. If that happens, the report may be redirected or mirrored to the correct repo.
