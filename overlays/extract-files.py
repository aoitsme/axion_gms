#!/usr/bin/env -S PYTHONPATH=../../../tools/extract-utils python3
#
# SPDX-FileCopyrightText: 2025 AxionAOSP
# SPDX-License-Identifier: Apache-2.0
#

import fnmatch
import glob
import os
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

from argparse import ArgumentParser
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from extract_utils.extract import extract_fns_user_type
from extract_utils.extract_pixel import (
    extract_pixel_factory_image,
    extract_pixel_firmware,
    pixel_factory_image_regex,
    pixel_firmware_regex,
)

from extract_utils.file import FileArgs, FileList
from extract_utils.fixups_blob import (
    blob_fixup,
    blob_fixups_user_type,
)

from extract_utils.fixups_lib import (
    lib_fixups,
    lib_fixups_user_type,
)

from extract_utils.main import (
    ExtractUtils,
    ExtractUtilsModule,
)

def _apktool_cmd(job_count: int | None = None):
    jar = os.environ.get("APKTOOL_JAR")
    base_cmd = ["java", "-jar", jar] if jar and os.path.isfile(jar) else ["apktool"]
    decode_opts = ["-j", str(job_count)] if job_count is not None else []
    return base_cmd, decode_opts


def overlay_fixup(path: str, apktool_jobs: int | None = None):
    print(f"Applying overlay fixup to {path} (APK file)")
    my_dir = os.path.dirname(os.path.abspath(__file__))
    folder_name = Path(path).stem
    decomp_dir = path + "_decomp"
    target_dir = path.rsplit(".apk", 1)[0]
    package_name = folder_name
    log_prefix = f"[overlay:{package_name}]"
    print(f"{log_prefix} starting fixup")
    if os.path.exists(decomp_dir):
        print(f"{log_prefix} removing stale temporary directory {decomp_dir}")
        shutil.rmtree(decomp_dir)
    try:
        print(f"{log_prefix} running apktool decode -> {decomp_dir}")
        apktool_base_cmd, decode_opts = _apktool_cmd(apktool_jobs)
        subprocess.check_call(apktool_base_cmd + ["d"] + decode_opts + [path, "-o", decomp_dir, "-f"])
        print(f"Decompiled to {decomp_dir}")
    except subprocess.CalledProcessError as e:
        print(f"apktool failed: {e}")
        if os.path.exists(decomp_dir):
            print(f"{log_prefix} cleaning failed temporary directory {decomp_dir}")
            shutil.rmtree(decomp_dir)
        return False
    except FileNotFoundError:
        print("apktool not found. Please install apktool.")
        if os.path.exists(decomp_dir):
            print(f"{log_prefix} cleaning failed temporary directory {decomp_dir}")
            shutil.rmtree(decomp_dir)
        return False
    os.unlink(path)
    print(f"Unlinked APK: {path}")
    folder = decomp_dir
    apktool_yml = os.path.join(folder, "apktool.yml")
    print(f"{log_prefix} cleaning apktool metadata and temporary files")
    if os.path.exists(apktool_yml):
        os.unlink(apktool_yml)
    original_dir = os.path.join(folder, "original")
    if os.path.exists(original_dir):
        shutil.rmtree(original_dir)
    public_xml = os.path.join(folder, "res", "values", "public.xml")
    if os.path.exists(public_xml):
        os.unlink(public_xml)
    unknown_dir = os.path.join(folder, "unknown")
    if os.path.exists(unknown_dir):
        shutil.rmtree(unknown_dir)
    manifest_path = os.path.join(folder, "AndroidManifest.xml")
    overlay_pkg = package_name
    target_pkg = None
    if os.path.exists(manifest_path):
        try:
            tree = ET.parse(manifest_path)
            root = tree.getroot()
            manifest_pkg = root.get('package', overlay_pkg)
            overlay_elem = root.find('overlay')
            if overlay_elem is not None:
                target_pkg = overlay_elem.get('{http://schemas.android.com/apk/res/android}targetPackage', None)
            print(f"Parsed manifest: package={manifest_pkg}, targetPackage={target_pkg}")
        except ET.ParseError as e:
            print(f"Failed to parse manifest: {e}")
    print(f"Using overlay package (name): {overlay_pkg}, target package: {target_pkg or 'N/A'}")
    template_path = os.path.join(my_dir, "overlay-template.txt")
    bp_path = os.path.join(folder, "Android.bp")
    if not os.path.exists(template_path):
        print(f"Template not found: {template_path}. Skipping Android.bp generation.")
    else:
        print(f"{log_prefix} generating Android.bp from template {template_path}")
        shutil.copy2(template_path, bp_path)
        with open(bp_path, "r", encoding="utf-8") as f:
            content = f.read()
        content = content.replace("dummy", overlay_pkg)
        with open(bp_path, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"Generated Android.bp for {overlay_pkg}")
    print(f"{log_prefix} removing unwanted wallpaper assets")
    for root, _dirs, files in os.walk(folder):
        for file in files:
            if file == "default_wallpaper.png":
                os.unlink(os.path.join(root, file))
    print(f"{log_prefix} normalizing AndroidManifest extractNativeLibs flags")
    manifest_pattern = os.path.join(folder, "**", "AndroidManifest.xml")
    for manifest in glob.glob(manifest_pattern, recursive=True):
        with open(manifest, "r", encoding="utf-8") as f:
            content = f.read()
        content = re.sub(
            r'extractNativeLibs\s*=\s*["\']false["\']',
            r'extractNativeLibs="true"',
            content,
            flags=re.IGNORECASE,
        )
        with open(manifest, "w", encoding="utf-8") as f:
            f.write(content)
    exclude_tags_path = os.path.join(my_dir, "exclude-tag.txt")
    if os.path.exists(exclude_tags_path):
        print(f"{log_prefix} applying XML exclude-tag cleanup using {exclude_tags_path}")
        with open(exclude_tags_path, "r") as f:
            exclude_tags = [line.strip() for line in f if line.strip()]
        res_dir = os.path.join(folder, "res")
        if os.path.exists(res_dir):
            for root, _dirs, files in os.walk(res_dir):
                for file in files:
                    if not file.endswith(".xml"):
                        continue
                    file_path = os.path.join(root, file)
                    full_path = os.path.abspath(file_path)
                    folder_abs = os.path.abspath(folder)
                    raw_pattern = os.path.join(folder_abs, "res/raw")
                    xml_pattern = os.path.join(folder_abs, "res/xml")
                    drawable_pattern = os.path.join(folder_abs, "res/drawable*")
                    if (
                        fnmatch.fnmatch(full_path, raw_pattern)
                        or fnmatch.fnmatch(full_path, xml_pattern)
                        or fnmatch.fnmatch(full_path, drawable_pattern)
                    ):
                        continue
                    for tag in exclude_tags:
                        if ":" not in tag:
                            continue
                        type_, node = tag.split(":", 1)
                        try:
                            cmd_ed = [
                                "xmlstarlet",
                                "ed",
                                "-L",
                                "-d",
                                f"/resources/{type_}[@name='{node}']",
                                file_path,
                            ]
                            subprocess.check_call(cmd_ed)
                            cmd_fo = ["xmlstarlet", "fo", "-s", "4", file_path]
                            formatted = subprocess.check_output(cmd_fo).decode("utf-8")
                            with open(file_path, "w", encoding="utf-8") as f:
                                f.write(formatted)
                        except subprocess.CalledProcessError as e:
                            print(f"xmlstarlet failed for {file_path}: {e}")
                        except FileNotFoundError:
                            print("xmlstarlet not found. Install it to remove excluded tags.")
                    with open(file_path, "r", encoding="utf-8") as f:
                        content = f.read()
                    content = re.sub(r"\?android:\^attr-private", "@*android:attr", content)
                    content = re.sub(r"@android:color", "@*android:color", content)
                    content = re.sub(r"\^attr-private", "attr", content)
                    with open(file_path, "w", encoding="utf-8") as f:
                        f.write(content)
    else:
        print("exclude-tag.txt not found. Skipping tag removal.")
    print(f"{log_prefix} sanitizing resource filenames containing '$'")
    for root, _dirs, files in os.walk(folder):
        for file in files:
            if "$" in file:
                new_name = re.sub(r"\$", "", file)
                old_path = os.path.join(root, file)
                new_path = os.path.join(root, new_name)
                os.rename(old_path, new_path)
                print(f"Renamed file: {file} -> {new_name}")
    res_dir = os.path.join(folder, "res")
    if os.path.exists(res_dir):
        print(f"{log_prefix} patching XML resource references")
        for root, _dirs, files in os.walk(res_dir):
            for file in files:
                if file.endswith(".xml"):
                    file_path = os.path.join(root, file)
                    file_name = os.path.basename(file_path)
                    with open(file_path, "r", encoding="utf-8") as f:
                        content = f.read()
                    if "illo_sim_app_dialog" in file_name:
                        content = re.sub(r"\$", "", content)
                        print(f"Removed $ from content in {file_path}")
                    elif "deferred_setup_welcome_illustration" in file_name:
                        content = content.replace("$deferred_setup_welcome_illustration__0", "deferred_setup_welcome_illustration__0")
                        print(f"Replaced specific $ reference in {file_path}")
                    elif "assistant_icon" in file_name:
                        content = content.replace("$assistant_icon__0", "assistant_icon__0")
                        print(f"Replaced specific $ reference in {file_path}")
                    elif "a11ymenu_intro" in file_name:
                        content = content.replace("$a11ymenu_intro__0", "a11ymenu_intro__0")
                        print(f"Replaced specific $ reference in {file_path}")
                    elif "ic_logo_a11y_assistant" in file_name:
                        content = content.replace("$ic_logo_a11y_assistant__0", "ic_logo_a11y_assistant__0")
                        print(f"Replaced specific $ reference in {file_path}")
                    with open(file_path, "w", encoding="utf-8") as f:
                        f.write(content)
    if "SimAppDialogOverlay" in package_name:
        illo_path = os.path.join(folder, "res", "drawable", "illo_sim_app_dialog.xml")
        if os.path.exists(illo_path):
            pass
    if "PixelSetupWizardOverlay2024" in package_name:
        deferred_path = os.path.join(folder, "res", "drawable", "deferred_setup_welcome_illustration.xml")
        if os.path.exists(deferred_path):
            pass
        deferred_night_path = os.path.join(folder, "res", "drawable-night", "deferred_setup_welcome_illustration.xml")
        if os.path.exists(deferred_night_path):
            pass
        assistant_path = os.path.join(folder, "res", "drawable", "assistant_icon.xml")
        if os.path.exists(assistant_path):
            pass
    bad_xml = os.path.join(folder, "res", "xml", "bookmarks.xml")
    if os.path.exists(bad_xml):
        os.unlink(bad_xml)
        print(f"Removed apktool-mangled bookmarks.xml from {package_name}")

    print(f"{log_prefix} finalizing output directory -> {target_dir}")
    try:
        os.rename(decomp_dir, target_dir)
    except OSError as e:
        print(f"{log_prefix} failed to finalize output directory: {e}")
        if os.path.exists(decomp_dir):
            print(f"{log_prefix} cleaning failed temporary directory {decomp_dir}")
            shutil.rmtree(decomp_dir)
        return False
    print(f"Renamed {decomp_dir} to {target_dir} (now a directory)")
    print(f"Overlay fixup completed for {package_name}. Directory ready at {os.path.isdir(target_dir)}")
    return True
lib_fixups: lib_fixups_user_type = {}
blob_fixups: blob_fixups_user_type = {}
extract_fns: extract_fns_user_type = {
    pixel_factory_image_regex: extract_pixel_factory_image,
    pixel_firmware_regex: extract_pixel_firmware,
}


PER_APP_OVERLAYS = {
    "GoogleDialerOverlay": {
        "target_pkg": "android",
        "priority": 1000,
        "strings": [("config_defaultDialer", "com.google.android.dialer")],
        "required_by": "GoogleDialer",
    },
    "GoogleMessagesOverlay": {
        "target_pkg": "android",
        "priority": 1000,
        "strings": [("config_defaultSms", "com.google.android.apps.messaging")],
        "required_by": "PrebuiltBugle",
    },
    "GoogleContactsOverlay": {
        "target_pkg": "android",
        "priority": 1000,
        "strings": [("config_systemContacts", "com.google.android.contacts")],
        "required_by": "GoogleContacts",
    },
    "VelvetOverlay": {
        "target_pkg": "android",
        "priority": 1000,
        "strings": [("config_defaultAssistant", "com.google.android.googlequicksearchbox")],
        "required_by": "Velvet",
    },
    "GoogleDeskClockOverlay": {
        "target_pkg": "android",
        "priority": 1000,
        "strings": [
            ("widget_default_package_name", "com.google.android.deskclock"),
            ("widget_default_class_name", "com.android.alarmclock.DigitalAppWidgetProvider"),
            ("config_dreamsDefaultComponent", "com.google.android.deskclock/com.android.deskclock.Screensaver"),
        ],
        "required_by": "PrebuiltDeskClockGoogle_76007351",
    },
    "GoogleTalkbackOverlay": {
        "target_pkg": "android",
        "priority": 1000,
        "strings": [("config_defaultAccessibilityService", "com.google.android.marvin.talkback/.TalkBackService")],
        "required_by": "talkback",
    },
    "GoogleMarkupOverlay": {
        "target_pkg": "com.android.systemui",
        "priority": 1000,
        "strings": [
            ("config_screenshotEditor", "com.google.android.markup/com.google.android.markup.AnnotateActivity"),
        ],
        "required_by": "MarkupGoogle_v2",
    },
    "WellbeingPrebuiltOverlay": {
        "target_pkg": "android",
        "priority": 1000,
        "strings": [
            ("config_systemWellbeing", "com.google.android.apps.wellbeing"),
            ("config_defaultWellbeingPackage", "com.google.android.apps.wellbeing"),
        ],
        "required_by": "WellbeingPrebuilt",
    },
}


def synthesize_per_app_overlay(name, spec, overlay_dir_path):
    out = Path(overlay_dir_path) / name
    if out.exists():
        import shutil
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)

    pkg = f"com.axion.overlay.{name.lower()}"
    manifest = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<manifest xmlns:android="http://schemas.android.com/apk/res/android"\n'
        f'    package="{pkg}">\n'
        '    <overlay android:isStatic="true"\n'
        f'        android:priority="{spec["priority"]}"\n'
        f'        android:targetPackage="{spec["target_pkg"]}"/>\n'
        '    <application android:hasCode="false"/>\n'
        '</manifest>\n'
    )
    (out / "AndroidManifest.xml").write_text(manifest)

    res_dir = out / "res" / "values"
    res_dir.mkdir(parents=True, exist_ok=True)
    body = '<?xml version="1.0" encoding="utf-8"?>\n<resources>\n'
    for key, val in spec["strings"]:
        body += f'    <string name="{key}" translatable="false">{val}</string>\n'
    body += '</resources>\n'
    (res_dir / "config.xml").write_text(body)

    bp = (
        'runtime_resource_overlay {\n'
        f'    name: "{name}",\n'
        f'    theme: "{name}",\n'
        '    certificate: "platform",\n'
        '    sdk_version: "current",\n'
        '    product_specific: true,\n'
        '}\n'
    )
    (out / "Android.bp").write_text(bp)


def _replace_or_add_list_property(block: str, property_name: str, values: list[str]) -> str:
    rendered = "".join(f'        "{value}",\n' for value in values)
    prop = f"    {property_name}: [\n{rendered}    ],\n"
    pattern = re.compile(rf"(?ms)^    {re.escape(property_name)}:\s*\[\n.*?^    \],\n")
    if pattern.search(block):
        return pattern.sub(prop, block, count=1)

    lines = block.splitlines(keepends=True)
    insert_at = len(lines) - 1
    for i, line in enumerate(lines):
        if line.startswith("    dex_preopt:"):
            insert_at = i
            break
    lines.insert(insert_at, prop)
    return "".join(lines)


def _find_android_app_import_block(content: str, module_name: str) -> tuple[int, int, str] | None:
    module_marker = f'    name: "{module_name}",\n'
    cursor = 0
    while True:
        block_start = content.find("android_app_import {\n", cursor)
        if block_start == -1:
            return None
        block_end = content.find("\n}\n", block_start)
        if block_end == -1:
            return None
        block_end += len("\n}\n")
        block = content[block_start:block_end]
        if module_marker in block:
            return block_start, block_end, block
        cursor = block_end


def update_required_modules(common_bp_path: Path, per_app_overlays: dict[str, dict[str, object]]):
    if not common_bp_path.exists():
        print(f"Blueprint {common_bp_path} not found; skipping required wiring.")
        return

    print(
        f"[overlay] update_required_modules start: "
        f"path={common_bp_path}, modules={len(per_app_overlays)}"
    )
    content = common_bp_path.read_text(encoding="utf-8")
    for index, (overlay_name, spec) in enumerate(per_app_overlays.items(), start=1):
        module_name = spec["required_by"]
        print(
            f"[overlay] required wiring {index}/{len(per_app_overlays)}: "
            f"overlay={overlay_name}, module={module_name}"
        )
        block_info = _find_android_app_import_block(content, module_name)
        if block_info is None:
            print(f"Module {module_name} not found in {common_bp_path}; skipping required wiring for {overlay_name}.")
            continue

        block_start, block_end, block = block_info
        required_match = re.search(r"(?ms)^    required:\s*\[\n(.*?)^    \],\n", block)
        if required_match:
            required = re.findall(r'"([^"]+)"', required_match.group(1))
            print(f"[overlay] existing required list for {module_name}: {required}")
        else:
            required = []
            print(f"[overlay] no existing required list for {module_name}")
        if overlay_name not in required:
            required.append(overlay_name)
            print(f"[overlay] appended {overlay_name} to {module_name}")
        else:
            print(f"[overlay] {overlay_name} already present in {module_name}")
        updated_block = _replace_or_add_list_property(block, "required", required)
        content = content[:block_start] + updated_block + content[block_end:]

    print(f"[overlay] writing updated required wiring to {common_bp_path}")
    common_bp_path.write_text(content, encoding="utf-8")
    print(f"Updated required overlays in {common_bp_path}")


CLI_OPTIONS_WITH_VALUE = {
    "--download-dir",
    "--download-sha256",
    "--only-name",
    "--section",
    "-s",
}


def _iter_positional_args(argv):
    i = 1
    while i < len(argv):
        arg = argv[i]
        if arg == "--":
            yield from argv[i + 1 :]
            return
        if arg in CLI_OPTIONS_WITH_VALUE:
            i += 2
            continue
        if any(arg.startswith(f"{opt}=") for opt in CLI_OPTIONS_WITH_VALUE if opt.startswith("--")):
            i += 1
            continue
        if arg.startswith("-"):
            i += 1
            continue
        yield arg
        i += 1


def _find_inner_extracted_dir(base: Path, device: str) -> Path | None:
    prefix = f"{device.lower()}-"
    matches = [
        child
        for child in base.iterdir()
        if child.is_dir() and child.name.lower().startswith(prefix) and (child / "product/overlay").is_dir()
    ]
    if not matches:
        matches = [
            child
            for child in base.iterdir()
            if child.is_dir() and (child / "product/overlay").is_dir()
        ]
    if not matches:
        return None
    return max(matches, key=lambda path: path.stat().st_mtime)


def _find_cached_source(device: str) -> Path | None:
    cache_root = Path("/tmp/gms-fetch")
    if not cache_root.exists():
        return None
    matches = []
    for extracted_dir in cache_root.glob("*/extracted"):
        if not extracted_dir.is_dir():
            continue
        inner = _find_inner_extracted_dir(extracted_dir, device)
        if inner is not None:
            matches.append(inner)
    if not matches:
        return None
    return max(matches, key=lambda path: path.stat().st_mtime)


def _resolve_source(argv, device: str) -> str | None:
    positional = list(_iter_positional_args(argv))
    if positional:
        source = Path(positional[-1]).expanduser()
        if source.is_dir():
            if (source / "product/overlay").is_dir():
                return str(source)
            if source.name == "extracted":
                inner = _find_inner_extracted_dir(source, device)
                if inner is not None:
                    print(f"[source] using extracted inner dir: {inner}")
                    return str(inner)
        return str(source)

    cached = _find_cached_source(device)
    if cached is not None:
        print(f"[source] using cached extracted dir: {cached}")
        return str(cached)

    return None


def _env_int(name: str) -> int | None:
    value = os.environ.get(name)
    if not value:
        return None
    try:
        parsed = int(value)
    except ValueError:
        print(f"[overlay] ignoring invalid integer for {name}: {value}")
        return None
    if parsed < 1:
        print(f"[overlay] ignoring non-positive integer for {name}: {value}")
        return None
    return parsed


def _available_threads() -> int:
    try:
        return max(1, len(os.sched_getaffinity(0)))
    except AttributeError:
        return max(1, os.cpu_count() or 1)


def _overlay_parallelism(apk_count: int) -> tuple[int, int]:
    available_threads = _available_threads()
    total_jobs = _env_int("OVERLAY_TOTAL_JOBS") or available_threads
    worker_jobs = _env_int("OVERLAY_FIXUP_JOBS")
    apktool_jobs = _env_int("APKTOOL_JOBS")

    if worker_jobs is None:
        # Keep several APKs in flight without oversubscribing a typical machine.
        worker_jobs = min(apk_count, max(1, total_jobs // 4))
    else:
        worker_jobs = min(apk_count, worker_jobs)

    if apktool_jobs is None:
        apktool_jobs = max(1, total_jobs // max(1, worker_jobs))

    return worker_jobs, apktool_jobs

if __name__ == "__main__":
    parser = ArgumentParser()
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from fetch_factory import fetch_apktool_jar, fetch_latest_bp4a_factory
    if not os.environ.get("APKTOOL_JAR"):
        try:
            os.environ["APKTOOL_JAR"] = fetch_apktool_jar()
        except Exception as e:
            print(f"[fetch] apktool auto-fetch failed ({e}); falling back to system apktool")
    if "--fetch" in sys.argv:
        sys.argv.remove("--fetch")
        sys.argv.append(fetch_latest_bp4a_factory())
    else:
        source = _resolve_source(sys.argv, os.environ.get("FETCH_DEVICE", "caiman"))
        if source is not None and source not in sys.argv[1:]:
            sys.argv.append(source)
    DEVICE = "common"
    VENDOR = "gms/overlays"
    module = ExtractUtilsModule(
        DEVICE,
        VENDOR,
        device_rel_path=f"vendor/{VENDOR}",
        blob_fixups=blob_fixups,
        lib_fixups=lib_fixups,
        extract_fns=extract_fns,
    )
    utils = ExtractUtils.device(module)
    utils.run()
    overlay_dir = Path(f"{DEVICE}/proprietary/product/overlay")
    if overlay_dir.exists():
        apk_paths = sorted(overlay_dir.glob("*.apk"))
        print(f"[overlay] found {len(apk_paths)} extracted overlay APKs in {overlay_dir}")
        worker_jobs, apktool_jobs = _overlay_parallelism(len(apk_paths)) if apk_paths else (1, 1)
        detected_threads = _available_threads()
        print(
            f"[overlay] parallel fixup config: workers={worker_jobs}, "
            f"apktool_jobs={apktool_jobs}, detected_threads={detected_threads}, "
            f"total_cpu_budget={_env_int('OVERLAY_TOTAL_JOBS') or detected_threads}"
        )
        failed_apks = []
        if worker_jobs <= 1 or len(apk_paths) <= 1:
            for index, apk_path in enumerate(apk_paths, start=1):
                print(f"[overlay] fixup {index}/{len(apk_paths)}: {apk_path.name}")
                if not overlay_fixup(str(apk_path), apktool_jobs):
                    failed_apks.append(apk_path.name)
        else:
            with ThreadPoolExecutor(max_workers=worker_jobs) as executor:
                future_to_name = {}
                for index, apk_path in enumerate(apk_paths, start=1):
                    print(f"[overlay] queue fixup {index}/{len(apk_paths)}: {apk_path.name}")
                    future = executor.submit(overlay_fixup, str(apk_path), apktool_jobs)
                    future_to_name[future] = apk_path.name
                completed = 0
                for future in as_completed(future_to_name):
                    completed += 1
                    apk_name = future_to_name[future]
                    ok = future.result()
                    print(f"[overlay] completed fixup {completed}/{len(apk_paths)}: {apk_name} (ok={ok})")
                    if not ok:
                        failed_apks.append(apk_name)
        if failed_apks:
            print(f"[overlay] failed overlay fixups: {', '.join(failed_apks)}")
            sys.exit(1)
        overlay_dir.mkdir(parents=True, exist_ok=True)
        per_app_items = list(PER_APP_OVERLAYS.items())
        print(f"[overlay] synthesizing {len(per_app_items)} per-app overlays")
        for index, (name, spec) in enumerate(per_app_items, start=1):
            print(
                f"[overlay] synthesize {index}/{len(per_app_items)}: "
                f"{name} -> {spec['required_by']}"
            )
            synthesize_per_app_overlay(name, spec, str(overlay_dir))
            print(f"Synthesized per-app overlay: {name} (required_by={spec['required_by']})")
        print(f"[overlay] updating required module wiring in ../{DEVICE}/Android.bp")
        update_required_modules(Path("..") / DEVICE / "Android.bp", PER_APP_OVERLAYS)
    bp_path = Path("Android.bp")
    if bp_path.exists():
        bp_path.unlink()
    product_mk = Path(f"{DEVICE}/{DEVICE}-vendor.mk")
    if not product_mk.exists():
        print(f"Makefiles {product_mk} not found; manual addition may be needed.")
    else:
        overlay_dirs = sorted(
            d.name
            for d in overlay_dir.iterdir()
            if (
                d.is_dir()
                and not d.name.endswith(".apk_decomp")
                and d.name not in PER_APP_OVERLAYS
            )
        )
        print(f"[overlay] preparing makefile update with {len(overlay_dirs)} overlay directories")

        OVERLAY_GATES = {
            "GoogleConfigOverlay": "gms",
        }

        with open(product_mk, "r", encoding="utf-8") as f:
            original = f.read()

        src_lines = original.splitlines()
        cut = None
        for i, line in enumerate(src_lines):
            if line.lstrip().startswith("PRODUCT_PACKAGES +="):
                j = i - 1
                while j >= 0 and not src_lines[j].strip():
                    j -= 1
                if (
                    j >= 0
                    and src_lines[j].lstrip().startswith(("ifneq", "ifeq"))
                    and ("TARGET_CORE_GMS" in src_lines[j] or "TARGET_GAPPS_VARIANT" in src_lines[j])
                ):
                    cut = j
                    print(
                        f"[overlay] found existing gated PRODUCT_PACKAGES block at line {i + 1}, "
                        f"rewinding cut to condition line {j + 1}"
                    )
                else:
                    cut = i
                    print(f"[overlay] found existing PRODUCT_PACKAGES block at line {i + 1}")
                break
        if cut is not None:
            print(f"[overlay] trimming existing generated package section from line {cut + 1}")
            src_lines = src_lines[:cut]
        trimmed_blank_lines = 0
        while src_lines and not src_lines[-1].strip():
            src_lines.pop()
            trimmed_blank_lines += 1
        if trimmed_blank_lines:
            print(f"[overlay] removed {trimmed_blank_lines} trailing blank line(s) before regenerating body")
        head = "\n".join(src_lines)

        if "TARGET_GAPPS_VARIANT" not in head:
            print("[overlay] TARGET_GAPPS_VARIANT block missing, injecting default variant logic")
            head += "\n\nTARGET_GAPPS_VARIANT ?= gms"
            head += "\nifeq ($(strip $(TARGET_CORE_GMS)),true)"
            head += "\nTARGET_GAPPS_VARIANT := core"
            head += "\nendif"

        VARIANT_COND = {
            "pico": "ifeq ($(strip $(TARGET_GAPPS_VARIANT)),pico)",
            "core": "ifneq ($(strip $(TARGET_GAPPS_VARIANT)),pico)",
            "gms": "ifeq ($(strip $(TARGET_GAPPS_VARIANT)),gms)",
        }

        body = ""
        for index, d in enumerate(overlay_dirs, start=1):
            gate = OVERLAY_GATES.get(d)
            gate_label = gate if gate is not None else "always"
            print(f"[overlay] package entry {index}/{len(overlay_dirs)}: {d} (gate={gate_label})")
            if gate is None:
                body += f"\n\nPRODUCT_PACKAGES += {d}"
            else:
                cond = VARIANT_COND[gate]
                body += f"\n\n{cond}\nPRODUCT_PACKAGES += {d}\nendif"

        with open(product_mk, "w", encoding="utf-8") as f:
            f.write(head + body + "\n")

        counts = {"always": 0}
        for d in overlay_dirs:
            counts[OVERLAY_GATES.get(d, "always")] = counts.get(OVERLAY_GATES.get(d, "always"), 0) + 1
        summary = ", ".join(f"{k}={v}" for k, v in counts.items() if v)
        print(f"Updated {product_mk}: {summary}")
