# WN Forza Tuner

This is a separate PySide6 / Qt prototype for the FH6 tune app.

It is **not** meant to replace the working CustomTkinter v11.4 build yet. Use it to test whether the Qt layout, rounded cards, sidebar navigation, gradients, and smoother custom telemetry gauges are worth continuing with.

## Run

Double-click:

```bat
run-dev.cmd
```

The launcher creates a local virtual environment and installs:

```txt
PySide6>=6.7
```

## Current prototype features

- Qt/PySide6 FH6 Tune Editor-style sidebar shell.
- Rounded cards and gradient styling.
- Theme settings for accent colour, gradient colour, and corner radius.
- Tune loading from folder or single `Data` file.
- Tune list with thumbnail support.
- Basic tune sections: Upgrades, Gearing, Tyres, Alignment, Springs, Damping, Aero, Brakes, Differential, Raw.
- Save copy.
- Share/import JSON.
- Thumbnail cache.
- Live FH6 Data Out telemetry listener.
- Qt-painted speedometer and steering wheel.

## Known limitations

- This is an early UI prototype. The full calibrated CustomTkinter sliders have not been ported yet.
- It currently shows raw/section values rather than the full mature editor controls.
- Keep `FH6_Tuner_BrowserShell_v11_4_ScrollAndSizingFix.zip` as the fallback build.


## V12.1 changes

Changed:
- Temporary "FH6 TuneLab" branding removed.
- Restored the WN23 FH6 Tune Editor logo in the sidebar.
- Tuning page now displays converted in-game values instead of only raw floats.
- Added proper labels for Gearing, Tyres, Alignment, Anti-roll Bars, Springs, Damping, Aero, Brakes, and Differential.
- Raw tab still shows the underlying raw float values for debugging.
- Added Anti-roll Bars as its own tuning section.


## V12.2 changes

Changed:
- Settings no longer requires typing colour hex codes.
- Primary accent and secondary/gradient colours now use native colour picker buttons.
- Added premade styles:
  - WN23 Pink/Cyan
  - Horizon Orange
  - Midnight Blue
  - Festival Purple
  - Carbon Green
  - Gold Dark
- Rounded corner setting remains available.


## V12.3 changes

Moved over more mature logic from the CustomTkinter version:
- Tuning rows are now editable using sliders and spinboxes.
- Slider values update the underlying raw tune floats.
- Save Copy now saves edited values from the Qt UI.
- Added Export CSV for mapped tune values.
- Raw tab remains available for debugging.

Visual changes:
- Gradient theme now carries into cards, tune cards, value rows, and buttons.
- Added gradient slider styling.
- Value rows now use a stronger card style instead of flat dark blocks.


## V12.3.1 hotfix

Fixed:
- Startup crash: `NameError: name 'background' is not defined`.
- Cause was a stylesheet block accidentally injected outside the Qt stylesheet string.
- Rebuilt the Qt stylesheet cleanly.
- Improved `run-dev.cmd` so it prefers the existing venv/python.exe and avoids the broken `py -3` path where possible.


## V12.3.2 hotfix

Fixed:
- Theme gradients now use blended `#RRGGBB` colours instead of alpha hex colours, so the visible colour should better match the selected preset.
- Gearing/Tyres/Alignment/etc. now use an exception-safe renderer.
- The tune section stack now explicitly switches to the newly rendered page, preventing blank sections.
- Added active highlighting for tuning section buttons.


## V12.3.3 hotfix

Fixed:
- Missing `QSlider` import caused every editable tuning section to fail with:
  `name 'QSlider' is not defined`.
- Tuning sections should now render sliders/spinboxes properly.
- Tuning section buttons are now arranged in a two-row grid with wider buttons so labels do not get cut off.
- Value rows now have a minimum height to prevent visual collapse.


## V12.3.4 changes

Added:
- Collapsible upgrade categories in the Qt upgrade tab.
- Categories:
  - Conversion / Presets
  - Engine
  - Aero & Body
  - Tyres & Rims
  - Drivetrain
  - Platform & Handling
  - Other / Unknown
- Expand All / Collapse All buttons.
- Upgrade cards now show:
  - slot number
  - friendly slot label
  - installed/absent status
  - variant/index
  - source/key
  - raw value


## V12.3.5 changes

Changed:
- Removed the extra Export CSV button from the main tuning action row.
- JSON import/export remains available as Import JSON and Share JSON.
- Added a Discord button to the sidebar.
- Discord button opens: https://discord.gg/jvXwbKwCp


## V12.3.6 changes

Changed:
- Removed the redundant global top header card from the Tuning page.
- The Tuning page now relies on its own hero/tune summary card.
- The global header still appears on Live Telemetry, Thumbnails, and Settings.


## v12.3.9 changes
- Removed the small text under the sidebar logo.
- Switched the sidebar logo to a cleaned transparent version with no black background.


## V12.4.0 changes

Added:
- Special Forza Edition tune-card styling.
- Tune cards for cars containing "Forza Edition" now get a unique gold/pink/cyan gradient and badge.
- Added Telemetry subtabs:
  - Dashboard
  - Race Timer
- Race Timer tab shows:
  - current lap timer
  - last lap
  - best lap
  - lap number
  - race position
  - packet count
- Timer values are best-effort from the current FH6 324-byte telemetry decoder.


## V12.4.1 changes

Changed:
- Race Times is now its own main sidebar page:
  - Tuning
  - Live Telemetry
  - Race Times
  - Settings
- Removed the separate Thumbnails sidebar page.
- Moved thumbnail tools into Settings.
- Added tune list filters:
  - brand
  - year
  - all cars / Forza Edition only / exclude Forza Edition
- Forza Edition tune card styling remains in place.


## V12.4.2 hotfix

Fixed:
- Settings crashed on startup because `refresh_colour_buttons()` was missing after the Race Times / Settings reshuffle.
- Restored the colour picker helper methods:
  - refresh_colour_buttons
  - choose_theme_colour
  - apply_theme_preset
- Made Settings refresh defensive so the page cannot crash if theme helpers are missing again.


## V12.4.3 hotfix

Fixed:
- Tune folders failed to load because the new brand/year filters used `re.sub(...)` without importing `re`.
- Added the missing `import re`.
- Made brand parsing slightly more defensive.


## V12.4.4 changes

Added:
- GitHub release update checker in Settings.
- Default repo:
  - WN2323/FHT
- Uses the GitHub latest-release API:
  - https://api.github.com/repos/WN2323/FHT/releases/latest
- Compares latest release tag against the app version.
- Shows whether an update is available.
- Open Releases button opens the GitHub release page.

Notes:
- Upload future builds as GitHub Releases with tags like `v12.4.5`.
- Attach the ZIP build to the release for users to download.


## V12.4.5 changes

Added:
- Configurable GitHub update source in Settings:
  - GitHub owner
  - GitHub repo
- Download && Install Update button.
- In-app update flow:
  1. Check latest GitHub release.
  2. Detect the attached ZIP asset.
  3. Download the ZIP.
  4. Extract it to `_update_staging`.
  5. Write `_apply_update.cmd`.
  6. Close the app.
  7. Copy the new files into the current app folder.
  8. Relaunch with `run-dev.cmd`.

Notes:
- The updater is designed for ZIP releases.
- It copies new files over the current folder and keeps local files like config/cache.
- If you change GitHub repo later, use Settings → Updates → owner/repo.


## V12.4.6 changes

Added:
- Shared Lap Times main sidebar page.
- Export Current Race Pack:
  - creates `.fh6share` ZIP-style package
  - includes tune data when selected
  - includes thumbnail when cached
  - includes lap summary
  - includes telemetry samples throughout the race/session
  - includes telemetry_summary.csv inside the package
- Import Share Pack.
- Shared lap comparison:
  - shared best lap
  - your best lap from current telemetry log
  - gap
  - car
  - tune hash
  - telemetry sample count
- Shared telemetry viewer:
  - summary stats
  - sampled timeline list with lap time, speed, RPM, gear, throttle, and brake.


## V12.4.7 changes

Fixed / changed Race Times:
- The big Race Times display now uses an app-side stopwatch instead of the unreliable raw FH6 lap-time offset.
- Added manual race timer controls:
  - Start Timer
  - Stop && Save Time
  - Reset Timer
  - Share This Time
- Telemetry can still best-effort auto-start the timer when an event begins.
- If FH6 sends a clear last/best lap update, the app can auto-stop; otherwise use Stop && Save Time.
- Share packs now use the saved app stopwatch time when available.
- Race Times now has a direct Share This Time button.
- Raw game timer values are still shown for debugging.


## V12.4.8 hotfix

Fixed:
- Share Time / Export Current Race Pack failed with:
  - `name 'zipfile' is not defined`
- Added the missing `import zipfile`.


## V12.4.9 changes

Race timer:
- The app timer now uses FH6 telemetry timestamp deltas, not wall-clock time.
- This means the timer should stop advancing when telemetry/game time stops, such as pause or tab-out.
- Auto-start now watches `is_race_on`, raw lap movement, and movement/throttle fallback.
- Auto-stop now watches race-off transitions and raw lap reset/update signals.
- Manual Stop && Save Time remains available when FH6 does not send a clean finish signal.

Sharing:
- Added a cleaner Race Times Share Preview card.
- Share Preview shows:
  - car used during the race
  - share time
  - source
  - telemetry sample count
- Share packs now prefer the race car detected from telemetry over the loaded tune name.
- Export confirmation now shows the car and time clearly.


## V12.5.0 changes

Telemetry visuals:
- Added a custom rev meter widget.
- Upgraded Live Telemetry layout to a more visual dashboard.
- Added a tyre status panel showing live FL/FR/RL/RR tyre temperatures.
- Added tune pressure targets for front/rear tyres when a tune is loaded.
- Speedometer, steering wheel, rev meter, and tyre panel now inherit the active accent colour.

Note: live tyre pressure is not exposed by the currently decoded FH6 telemetry packet in this build, so the telemetry page shows the loaded tune pressure targets alongside live tyre temperatures.


## V12.5.1 changes

Telemetry HUD visual pass:
- Added Forza-style HUD strip.
- Added animated throttle/brake pedal bars.
- Added suspension travel visualiser for FL / FR / RL / RR.
- Improved tyre temperature colour bands:
  - cold blue
  - warming cyan
  - good green
  - hot amber
  - overheated red
- Kept live tyre temps plus loaded tune front/rear pressure targets.
- Reworked telemetry layout to feel more like a dashboard/HUD.


## V12.6.0 release-prep changes

Added:
- Setup page.
- Default tune folder:
  - C:\XboxGames\GameSave\pgs\u_*\current\ContainersRoot
- Setup asks:
  - speed unit: MPH or KM/H
  - auto update check on startup
- Setup clearly states telemetry port 3010.
- Diagnostics export button.
- Car View sidebar page:
  - tune thumbnail
  - car name
  - ordinal
  - drivetrain
  - gears
  - Forza Edition status
  - tune hash
  - tune path
- Settings diagnostics export.
- Dev mode toggle.
- GitHub update repo owner/name fields are hidden unless Dev mode is enabled.
- Last loaded tune folder is remembered.


## V1.0.0 release candidate changes

Changed:
- Application title is now `WN Forza Tuner`.
- Added WNFT app icon from `data/WNFT.ico`.
- Removed the fallback card/text from the bottom of the sidebar.
- Added Windows EXE build script: `build-exe.cmd`.

## Building the EXE

Run:

```bat
build-exe.cmd
```

The built EXE will be here:

```txt
dist\WN Forza Tuner\WN Forza Tuner.exe
```

This uses PyInstaller in onedir mode, which is usually safer for PySide6 apps than onefile mode.


## V1.0.1 build-script hotfix

Fixed:
- `build-exe.cmd` no longer blindly uses `py -3`, which can point at a broken Python 3.14 install.
- The build script now checks:
  - `python`
  - `py -3.13`
  - `py -3.12`
  - `py -3.11`
  - `py -3.10`
  - `py -3.9`
  - `py -3`
- It creates a separate `.build_venv` for PyInstaller.
- It stops properly if a build command fails.
- `run-dev.cmd` now uses the same safer Python detection.


## V1.0.2 EXE resource-path hotfix

Fixed:
- EXE builds could show every car as `Unknown car #...`.
- The app now separates:
  - `BASE_DIR` = folder beside the EXE for config/cache/user files
  - `RESOURCE_BASE_DIR` = PyInstaller `_internal` folder for bundled data
- `car_db.json`, `drivetrain_db.json`, app icon, and logo now load correctly in PyInstaller onedir builds.
- Diagnostics now reports resource folder and car database entry count.


## V1.0.3 community thumbnail cache updater

Added:
- Community thumbnail cache downloads from the latest GitHub release.
- The app looks for a ZIP asset with names like:
  - `thumbnail_cache.zip`
  - `WNFT_Thumbnail_Cache.zip`
  - `car_thumbnails.zip`
- The ZIP should contain ordinal-named images, for example:
  - `417.png`
  - `1234.png`
  - `9876.jpg`
- Images are copied/converted into the local `thumbnail_cache` folder as PNG files.
- Settings → Thumbnails now has `Update Community Cache`.
- Setup and Settings include an option to download the community cache during auto update checks.
- Diagnostics reports the thumbnail cache count.

Recommended release asset naming:
```txt
WNFT_Thumbnail_Cache.zip
```


## V1.0.4 GitHub folder thumbnail cache updater

Changed:
- Community thumbnail cache no longer needs to be attached as a release ZIP.
- The app now downloads missing thumbnails directly from:
  - `https://github.com/WN2323/FHT/tree/main/thumbnail_cache`
- Internally it uses the GitHub Contents API:
  - owner/repo from the app update source
  - branch: `main`
  - folder: `thumbnail_cache`
- It only downloads ordinal-named image files:
  - `417.png`
  - `1234.jpg`
  - `9876.webp`
- Existing local thumbnails are skipped to avoid re-downloading everything.
- Dev mode can change the thumbnail branch/folder.


## V1.0.5 cache folder hotfix

Fixed:
- `Open Cache Folder` could crash if `thumbnail_cache` did not exist yet.
- App now creates writable folders on startup:
  - `thumbnail_cache`
  - `imported_share_tunes`
  - `shared_laps`
  - `_update_downloads`
- `Open Cache Folder` now creates the folder before opening it.


## V1.0.6 thumbnail download hotfix

Fixed:
- Community cache update could leave unreadable `_tmp_####.png` files.
- Thumbnail downloads now use raw bytes and `QImage`, not `QPixmap` in the worker thread.
- PNG files from GitHub are saved directly as cache files.
- JPG/JPEG/WEBP files are converted to PNG with `QImage`.
- `_tmp_*` thumbnail files are cleaned up on app startup.
- ZIP cache import now uses the same safer image handling.


## V1.0.7 build size reduction

Changed:
- `build-exe.cmd` is now an optimised PyInstaller build.
- Removed `--collect-all PySide6` from the main build script.
- Added exclusions for unused PySide6/Qt modules such as WebEngine, QML, Quick, Multimedia, Bluetooth, Charts, PDF, etc.
- Added cleanup for optional Qt folders if PyInstaller still collects them.
- Added `build-exe-safe.cmd` as the old large/safe fallback build.

Recommended:
```bat
build-exe.cmd
```

Fallback if the optimised build fails:
```bat
build-exe-safe.cmd
```

The app only uses QtCore, QtGui, and QtWidgets, so the optimised build should be much smaller than the previous ~660 MB folder.


## V1.0.8 current car tune auto-loader

Added:
- Live Telemetry button: `Load Current Car Tune`.
- Settings → Telemetry button: `Load Current Telemetry Car Tune Now`.
- Setup/Settings option:
  - `Auto-load tune when telemetry detects current car`
- Uses telemetry `car_ordinal` to find a matching tune.
- If multiple tunes exist for the same car, the newest matching tune file is selected.
- Searches the remembered tune folder/default tune folder.
- Diagnostics reports auto-load status and attempted ordinals.

Important:
- FH telemetry identifies the current car ordinal, not always the exact active tune file.
- If several tunes exist for the same car, the app picks the newest matching tune.


## V1.0.9 current-car telemetry wait hotfix

Fixed / improved:
- `Load Current Car Tune` no longer immediately fails if no valid car packet has arrived yet.
- If telemetry is not running, the app starts telemetry first.
- The app waits up to 8 seconds for a telemetry packet with a valid car ordinal.
- It searches recent telemetry samples, not just the latest packet.
- If it still fails, the message now shows:
  - packet count
  - last packet size
  - guidance about FH Data Out/full Dash telemetry format.


## V1.1.0 public release safety changes

Changed:
- Removed automatic update checks on startup.
- Removed in-app update installation.
- Removed automatic thumbnail downloads.
- Replaced the GitHub community thumbnail cache button with a local-only installer:
  - Settings > Thumbnails > Install Thumbnail Folder
- Existing old config files are forced to:
  - auto_update_check = false
  - auto_thumbnail_cache_update = false

Thumbnail installation:
1. Download or prepare a local folder containing thumbnail images.
2. Open Settings > Thumbnails.
3. Click Install Thumbnail Folder.
4. Pick the folder containing images.
5. The app copies/converts usable images into `thumbnail_cache` as `ordinal.png`.

Supported image names:
- `1034.png`
- `1034_2.png`
- `Thumbnail_1034_Big.png`

Supported image formats:
- PNG
- JPG / JPEG
- WEBP
- BMP

If duplicate ordinal images are found, the largest/highest resolution one is kept.


## V1.1.1 thumbnail repo button

Added:
- Settings > Thumbnails > Get Thumbnails on GitHub

This only opens the public GitHub thumbnail folder in the user's browser:
- No automatic download
- No in-app install/update
- No subprocess
- No urllib/network download code
- No command script writing

Users still install thumbnails locally with:
- Settings > Thumbnails > Install Thumbnail Folder


## V1.1.2 thumbnail button cleanup

Changed:
- Removed `Assign Thumbnail To Selected` from the public build UI.
- `Get Thumbnails on GitHub` is now the replacement button in Settings > Thumbnails.
- Local thumbnail flow is now:
  1. Get Thumbnails on GitHub
  2. Download/extract them manually
  3. Install Thumbnail Folder


## V1.3.10 Nuitka build option

Added:
- `build-nuitka.cmd`
- `PUBLIC_RELEASE_BUILD_NOTES.md`

Changed:
- App resource detection now supports:
  - normal Python dev run
  - PyInstaller build
  - Nuitka standalone build

Recommended public release build:
```bat
build-nuitka.cmd
```

Output:
```txt
dist-nuitka\main.dist\WN Forza Tuner.exe
```

Release the whole folder:
```txt
dist-nuitka\main.dist
```

Notes:
- Nuitka may reduce antivirus false positives, but it is not guaranteed.
- The app should function the same.
- Avoid onefile builds for now; standalone folder mode is recommended.


## v1.3.10

Added:
- Car Card Viewer integrated into the main app, replacing the old Car View tab.
- Card front/back flip with branded reverse side.
- Tuning Assist tab with tune-value recommendations and telemetry-aware suggestions.
- Larger sidebar Discord button with Discord icon.
- Ko-fi donation button linking to https://ko-fi.com/wn123.

Notes:
- Tuning Assist does not automatically overwrite tune files yet. It shows recommended target values and can export JSON.
- Telemetry improves suggestions when enough samples are recorded.


## v1.3.10 hotfix

Fixed:
- Car View no longer pulls class/PI/identity from telemetry.
- Car View card now uses the selected loaded tune as its source of truth.
- The card badge now shows `TUNE #ordinal` instead of relying on telemetry PI.
- The details panel now says `Class / PI: Not stored in tune` rather than `Telemetry PI`.
- Telemetry remains available for Live Telemetry and Tuning Assist.


## v1.3.10 hotfix

Fixed:
- Replaced the integrated Car View renderer with the same renderer style/logic used by `WN_CarCard_Prototype_v0_5_1`.
- Kept Car View loaded-tune based only.
- Added `Load Card Image` and `Clear Card Image` buttons so a missing thumbnail can be manually overridden, matching the standalone prototype workflow.
- Kept the v0.5.1 full-background paint clear to prevent card ghosting.


## v1.3.10 update

Added:
- Manual Card Stats section in Car View.
- Optional display-only fields:
  - Class
  - PI
  - Power HP
  - Weight KG
  - Top Speed MPH
  - Handling
  - Acceleration
  - Launch
  - Braking
- When enabled, the card shows the manual stats like the standalone card prototype.
- These values do not edit the tune file.


## v1.3.10 update

Added:
- `Force holographic effect` option in Car View.
- This applies the shiny/foil card effect to any loaded car.
- The `FORZA EDITION` badge still only appears if the loaded car itself is detected as a Forza Edition car.


## v1.3.10 update

Added:
- Integrated the Tune Assist UI prototype into the main Tuning Assist tab.
- Tune Assist now follows the currently viewed/selected tune.
- Tune Assist uses tune-style tabs with dual markers:
  - white = current value
  - gold = suggested value
  - dashed gold = previewed change
- Tune Type / Goal dropdown drives the suggestions.

Fixed:
- Tune folder config no longer gets overwritten by a single `Tuning_####` folder after loading tunes.
- Added separate config tracking for scan folder and last loaded tune file.
- Existing old configs that saved a single tune folder are migrated back to the default scan glob.


## v1.3.10 startup hotfix

Fixed:
- v1.3.0 could close immediately on launch because `build_tune_page` was missing.
- Restored the working Tuning page builder from the previous stable build.
- Added missing `shutil` import used by shared lap import code.
- Updated `run-dev.cmd` so it pauses on Python errors instead of closing instantly.


## v1.3.10 startup hotfix

Fixed:
- Restored `current_tyre_pressure_targets`, which the telemetry refresh loop expected.
- Added a defensive fallback in telemetry refresh so this type of missing helper does not spam/crash.


## v1.3.10 Tune Assist hotfix

Fixed:
- Tune Assist crashed with:
  - `AttributeError: 'FieldDef' object has no attribute 'clamp_display'`
- Added `clamp_display` compatibility to `FieldDef`.
- Made Tune Assist suggestion clamping defensive so it can use either `clamp_display` or `clamp`.


## v1.3.10 visible donate button hotfix

Fixed:
- Donate/Ko-fi button could be missed or pushed too low in the sidebar.
- Moved Donate/Ko-fi and Discord into a visible `SUPPORT` section under the navigation buttons.
- Donate button now clearly says `Donate / Ko-fi` and links to https://ko-fi.com/wn123.


## v1.3.10 header tune names, search and sort

Added:
- Reads the safe tune name/description/date fields from each tune folder's `header` file.
- Tune cards in the Tuning page now show the tune name only.
- Search now checks car name, tune name and tune description.
- Added tune list sorting:
  - Newest first
  - Oldest first
  - Car name A-Z
  - Tune name A-Z

Notes:
- Creator/gamertag/creator ID are intentionally not shown in the main tuner.
- Owner patching is intentionally not included in this release.


## v1.3.10 auto-load header with Data

Added:
- When a `Data` file is loaded/selected, the app automatically checks the same folder for `header`.
- If the header is readable, the tune name is loaded immediately and shown with the selected tune.
- Tuning page header, Car View and Tune Assist now use `Car — Tune Name` when a header tune name exists.
- Car View now has a `Tune Name` chip.
- Search still checks tune name and description, but creator/gamertag/creator ID remain hidden.

Notes:
- If no header exists beside the Data file, the tune still loads normally.
- Owner patching is still not included in the main release.


## v1.3.10 Tune Assist format hotfix

Fixed:
- Tune Assist could crash with:
  - `AttributeError: 'FieldDef' object has no attribute 'format_display'`
- Added `FieldDef.format_display()` so suggested-value boxes render correctly.


## v1.3.10 narrow sidebar and release cleanup

Changed:
- Reduced sidebar width from 235px to 210px.
- Reduced sidebar margins, logo size and button padding slightly.
- Kept the main content area larger for second-monitor/window-size issues.
- Replaced/kept the sidebar Discord icon as `data/discord_logo.png`.
- Removed old unused sidebar logo variants.
- Removed large unused fallback images from the release package.
- Kept only the Nuitka build helper files:
  - `build-nuitka.cmd`
  - `run-dev.cmd`
  - `requirements.txt`

Not included:
- `build-exe.cmd`
- `build-exe-safe.cmd`
- PyInstaller spec files
- old removed sidebar image files


## v1.3.10 adjustable sidebar only

Changed:
- Based on v1.3.8, not v1.3.9.
- Added draggable sidebar resizing only.
- Sidebar width is saved and restored on next launch.
- Added Settings > Theme / Visuals > Sidebar width.
- Sidebar width range: 150px to 360px.

Not included from v1.3.9:
- No telemetry/race UI refresh interval changes.
- No telemetry early-return refresh change.
- No telemetry sample buffer reduction.
- No resource-usage optimisation pass.
