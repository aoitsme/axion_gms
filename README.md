# vendor_gms

## Basic usage

- If you just wanna use this repository, then you just need to include `products/gms.mk`
- This is as simple as: `$(call inherit-product-if-exists, vendor/gms/products/gms.mk)`
- Enable GMS by setting `WITH_GMS=true` before inheriting the product makefile.
- Select the package set with `TARGET_GAPPS_VARIANT`:
  - `gms` (default) = full GMS
  - `pico` = minimal GMS
  - `core` = core GMS
- Do not use `TARGET_CORE_GMS`; `TARGET_GAPPS_VARIANT` is the only variant selector.

Example:

```make
WITH_GMS := true
TARGET_GAPPS_VARIANT := pico
$(call inherit-product-if-exists, vendor/gms/products/gms.mk)
```

`TARGET_GAPPS_VARIANT` maps to Soong phony modules as follows:

| Variant | Module |
| --- | --- |
| `gms` / unset | `GmsCoreFull` |
| `core` | `GmsCoreAndroid` |
| `pico` | `GmsCoreMain` |

Build output/version flavor names are `GMS`, `PICO`, `CORE`, or `VANILLA`.

## Extracting / updating

Run all commands from `vendor/gms`.

### Requirements

- `aapt` from the Android build tree.
- `apktool` for overlay decoding.
  - If `APKTOOL_JAR` is set, the scripts use it.
  - Otherwise the overlay extractor tries to fetch apktool automatically, then falls back to `apktool` from `PATH`.
- `xmlstarlet` for overlay XML cleanup.
  - Debian/Ubuntu: `sudo apt install xmlstarlet`
  - Arch: `sudo pacman -S xmlstarlet`

### One-command regeneration

Use `regen` for normal updates. It refreshes the app blobs, package map, generated makefiles, properties, and overlays in one pass.

From a local extracted factory image / dump:

```sh
./regen /path/to/dump
```

Or fetch a Pixel factory image by release prefix:

```sh
./regen bp4a
```

`regen` runs two stages:

1. `./extract-files.py ...`
   - extracts files listed in `proprietary-files.txt`
   - regenerates `common/Android.bp` and `common/common-vendor.mk`
   - updates `proprietary-pkg-map.txt` from extracted APK package names
   - injects explicit dependencies from `proprietary-required-map.txt`
   - grabs SetupWizard/GMS-related product properties into `products/gms-props.mk`
2. `./overlays/extract-files.py ...`
   - decodes source RRO APKs
   - synthesizes per-app resource overlays where needed
   - grabs overlays that target shipped packages, such as Pixel SetupWizard overlays
   - wires generated/grabbed overlays into the target app's `required` deps

### Manual extraction

Extract only the main GMS blobs:

```sh
./extract-files.py /path/to/dump
```

Extract only overlays:

```sh
cd overlays
./extract-files.py /path/to/dump
```

Fetch mode also works for the individual extractors:

```sh
./extract-files.py --fetch bp4a
cd overlays
./extract-files.py --fetch bp4a
```

### Updating blob names

If Google renames APK directories or filenames, use `update-list.py` to update list entries from a new dump.

Example: `arcore-1.42.apk` → `arcore-1.48.apk`

```sh
./update-list.py /path/to/dump
```

Review the result before regenerating.

## Overlay handling

Overlays are handled by `overlays/extract-files.py`.

- Source RRO APKs are decoded into source modules under `overlays/common/proprietary/product/overlay`.
- Resource-only overlays get an `Android.bp` using `runtime_resource_overlay`.
- Files with invalid resource names, such as names containing `$`, are sanitized automatically.
- Overlays targeting packages listed in `proprietary-pkg-map.txt` are grabbed directly and added to that package's `required` deps.
  - Example: an overlay targeting `com.google.android.pixel.setupwizard` is added to `SetupWizardPixelPrebuilt_v802960446`.
- Device-exclusive overlays can be blacklisted in the extractor. Caimito-exclusive overlays are currently skipped.

### Removing overlay resources

- If certain overlays are not required, you can simply add them to `exclude-tag.txt`, those will be removed from the extracted overlays.

Entries use:

```text
type:resource_name
```

Example:

```text
bool:config_wlc_support_enabled
string:config_defaultAssistantAccessComponent
```

### Important map files

| File | Purpose |
| --- | --- |
| `proprietary-pkg-map.txt` | Maps Soong module name to Android package name. Used for overlay target matching and regenerated from APKs. |
| `proprietary-required-map.txt` | Explicit module dependencies that must be added to app imports. |
| `proprietary-target-map.txt` | Redirects OEM overlay target packages to AOSP target packages. |
| `overlays/exclude-tag.txt` | Resource entries removed from extracted overlays. |

## Miscellaneous information

- Overlay extraction uses parallel apktool jobs, so it can be heavy on weak hosts.
- If apktool output looks wrong, remove the generated overlay directory and rerun `./regen`.
- After changing `proprietary-required-map.txt`, rerun `./extract-files.py --regenerate_makefiles` or `./regen` so `common/Android.bp` is updated.
