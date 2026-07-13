# Operations

## Working-directory constraint (config resolution)

The CLI finds `config.toml` relative to the **current working directory** —
commands are expected to run from the repo root. Relative paths inside the
config (`db_path`) then resolve against the config file's directory.

launchd jobs do **not** inherit a working directory (they start at `/`), so
`uv run cortex refresh` would fail to find `config.toml`. The Slice 5
LaunchAgent must either:

- set `WorkingDirectory` to the repo root in
  `launchd/com.fabian.cortex.refresh.plist` (preferred), or
- change the CLI to resolve `config.toml` from the repo root instead of the
  working directory.
