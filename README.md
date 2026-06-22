# WN Forza Tuner v1.3.13

Public source package for WN Forza Tuner.

## Included

- Tuning file viewer/editor UI
- Header tune-name reading
- Tune-name / description search
- Newest / oldest / A-Z tune sorting
- Tuning Assist preview UI
- Car Card view
- Live telemetry view
- Race timer and shared lap tools
- Local thumbnail folder install
- Manual thumbnail repo link
- Discord and Ko-fi buttons
- Adjustable sidebar
- Nuitka-only build flow

## Public-package cleanup

This build removes inactive source left behind by features that are no longer shipped.

Removed from source:

- old in-app update code paths
- old automatic thumbnail retrieval code paths
- old network placeholder stubs
- old GitHub API helper code
- old update staging constants
- old dev/source-editing controls
- stale config keys from removed systems
- unused release/package clutter

## Build / run

Run from source:

```bat
run-dev.cmd
```

Build with Nuitka:

```bat
build-nuitka.cmd
```

Only these root helper files are included:

```txt
build-nuitka.cmd
run-dev.cmd
requirements.txt
```

## Notes

The app uses local files and user-selected folders. Thumbnail images are installed from a local folder. The GitHub thumbnail button only opens the repo in a browser for manual access.
