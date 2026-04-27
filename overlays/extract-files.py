#!/usr/bin/env -S PYTHONPATH=../../../tools/extract-utils python3
#
# SPDX-FileCopyrightText: 2025-2026 AxionOS
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

from extract_utils.main import (
    ExtractUtils,
    ExtractUtilsModule,
)

SHARED_OVERLAY_REQUIRED_BY = {
    "GoogleConfigOverlay": "PrebuiltGmsCoreVic",
}

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

extract_fns: extract_fns_user_type = {
    pixel_factory_image_regex: extract_pixel_factory_image,
    pixel_firmware_regex: extract_pixel_firmware,
}


def load_package_mapping():
    mapping = {}
    map_file = Path(__file__).parent.parent / "proprietary-pkg-map.txt"
    if map_file.exists():
        for line in map_file.read_text().splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                mapping[k.strip()] = v.strip()
    return mapping


def load_target_redirection_map():
    mapping = {}
    map_file = Path(__file__).parent.parent / "proprietary-target-map.txt"
    if map_file.exists():
        for line in map_file.read_text().splitlines():
            if line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            mapping[k.strip()] = v.strip()
    return mapping


def get_dynamic_overlay_specs(mapping: dict[str, str]) -> dict[str, dict[str, object]]:
    TARGET_PKG_OVERRIDES = {
        "MarkupGoogle_v2": "com.android.systemui",
    }

    FALLBACK_TEMPLATES = {
        "GoogleDialer": [("config_defaultDialer", "{pkg}")],
        "PrebuiltBugle": [("config_defaultSms", "{pkg}")],
        "GoogleContacts": [("config_systemContacts", "{pkg}")],
        "Velvet": [("config_defaultAssistant", "{pkg}")],
        "talkback": [("config_defaultAccessibilityService", "{pkg}/.TalkBackService")],
        "MarkupGoogle_v2": [("config_screenshotEditor", "{pkg}/com.google.android.markup.AnnotateActivity")],
        "WellbeingPrebuilt": [("config_systemWellbeing", "{pkg}")],
        "PrebuiltDeskClockGoogle_76007351": [
            ("widget_default_package_name", "{pkg}"),
            ("widget_default_class_name", "com.android.alarmclock.DigitalAppWidgetProvider"),
            ("config_dreamsDefaultComponent", "{pkg}/com.android.deskclock.Screensaver"),
        ],
    }

    RESOURCE_NAME_OVERRIDES = {
        "PrebuiltDeskClockGoogle_76007351": {"widget_default_class_name"},
    }

    specs = {}
    
    gms_markers = [
        mapping.get("PrebuiltGmsCoreVic", "com.google.android.gms"),
        mapping.get("Phonesky", "com.android.vending"),
    ]

    for mod, pkg in mapping.items():
        overlay_name = f"{mod}Overlay"
        
        spec = {
            "priority": 1000,
            "required_by": mod,
            "package_markers": [pkg],
        }
        
        if mod in FALLBACK_TEMPLATES:
            spec["fallback_strings"] = [
                (k, v.format(pkg=pkg)) for k, v in FALLBACK_TEMPLATES[mod]
            ]
        
        if mod in RESOURCE_NAME_OVERRIDES:
            spec["resource_names"] = RESOURCE_NAME_OVERRIDES[mod]
            
        specs[overlay_name] = spec

    specs["GmsAndroidOverlay"] = {
        "target_pkg": "android",
        "priority": 1000,
        "required_by": "PrebuiltGmsCoreVic",
        "package_markers": gms_markers,
    }
    
    return specs

GMS_PACKAGE_MAPPING = load_package_mapping()
TARGET_REDIRECTION_MAP = load_target_redirection_map()
DYNAMIC_PER_APP_OVERLAYS = get_dynamic_overlay_specs(GMS_PACKAGE_MAPPING)

def _write_xml_resources(path: Path, elements: list[ET.Element]):
    root = ET.Element("resources")
    for element in elements:
        root.append(element)
    tree = ET.ElementTree(root)
    try:
        ET.indent(tree, space="    ")
    except AttributeError:
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    tree.write(path, encoding="utf-8", xml_declaration=True)


def synthesize_overlay_module(name, target_pkg, priority, overlay_dir_path):
    out = Path(overlay_dir_path) / name
    out.mkdir(parents=True, exist_ok=True)

    pkg = f"com.axion.overlay.{name.lower().replace('_', '')}"
    manifest = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<manifest xmlns:android="http://schemas.android.com/apk/res/android"\n'
        f'    package="{pkg}">\n'
        '    <overlay android:isStatic="true"\n'
        f'        android:priority="{priority}"\n'
        f'        android:targetPackage="{target_pkg}"/>\n'
        '    <application android:hasCode="false"/>\n'
        '</manifest>\n'
    )
    (out / "AndroidManifest.xml").write_text(manifest)

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
    return out


def _write_fallback_string_resources(out: Path, fallback_strings: list[tuple[str, str]]):
    resources = []
    for key, value in fallback_strings:
        element = ET.Element("string", {"name": key, "translatable": "false"})
        element.text = value
        resources.append(element)
    _write_xml_resources(out / "res" / "values" / "config.xml", resources)


def _merge_resource_elements(existing: ET.Element, new: ET.Element):
    if existing.tag != new.tag:
        return existing

    if existing.tag == "string":
        val1 = (existing.text or "").strip()
        val2 = (new.text or "").strip()
        if not val2: return existing
        if not val1:
            existing.text = val2
            return existing

        delim = None
        for d in [";", ":", ","]:
            if d in val1 or d in val2:
                delim = d
                break
        
        if delim:
            parts1 = [p.strip() for p in val1.split(delim) if p.strip()]
            parts2 = [p.strip() for p in val2.split(delim) if p.strip()]
            combined = parts1 + [p for p in parts2 if p not in parts1]
            prefix = delim if val1.startswith(delim) or val2.startswith(delim) else ""
            suffix = delim if val1.endswith(delim) or val2.endswith(delim) else ""
            existing.text = prefix + delim.join(combined) + suffix
    
    elif "array" in existing.tag:
        items1 = [i.text for i in existing.findall("item") if i.text]
        items2 = [i.text for i in new.findall("item") if i.text]
        for val in items2:
            if val not in items1:
                item = ET.SubElement(existing, "item")
                item.text = val
                items1.append(val)
                
    return existing


def _overlay_scalar_owner(name: str, element: ET.Element, overlay_specs: dict[str, dict[str, object]]) -> str | None:
    text = "".join(element.itertext())
    is_array = "array" in element.tag
    item_count = len(element.findall("item")) if is_array else 1
    
    matches = []
    for overlay_name, spec in overlay_specs.items():
        if overlay_name == "GmsAndroidOverlay":
            continue
        if name in spec.get("resource_names", set()):
            matches.append(overlay_name)
            continue
        for marker in spec.get("package_markers", []):
            if marker in text:
                matches.append(overlay_name)
                break
    matches = list(dict.fromkeys(matches))

    is_collective = False
    if len(matches) > 1:
        is_collective = True
    elif len(matches) == 1:
        if any(d in text for d in [":", ";", ","]):
            is_collective = True
        elif is_array and item_count > 1:
            is_collective = True
        elif any(name.endswith(s) for s in ["Packages", "Components", "Apps", "Services"]):
            is_collective = True

    if is_collective:
        return "GmsAndroidOverlay"

    if len(matches) == 1:
        return matches[0]

    gms_markers = DYNAMIC_PER_APP_OVERLAYS["GmsAndroidOverlay"]["package_markers"]
    if any(m in text for m in gms_markers):
        return "GmsAndroidOverlay"

    return None


def discover_source_overlays(source_path: Path) -> list[Path]:
    overlay_apks = []
    for p in ["product/overlay", "vendor/overlay", "system/overlay", "system_ext/overlay"]:
        dir_path = source_path / p
        if dir_path.is_dir():
            overlay_apks.extend(dir_path.glob("*.apk"))
    return sorted(overlay_apks)


def grab_dynamic_overlays(source_path: Path, output_dir: Path, overlay_specs: dict[str, dict[str, object]]):
    source_overlays = discover_source_overlays(source_path)
    if not source_overlays:
        print(f"[grabber] no source overlays found in {source_path}")
        return []

    print(f"[grabber] discovered {len(source_overlays)} source overlays to grabber")
    
    grabbed: dict[tuple[str, str], dict[Path, dict[str, ET.Element]]] = {}
    
    for spec in overlay_specs.values():
        spec.setdefault("resource_names", set())

    with ThreadPoolExecutor(max_workers=8) as executor:
        temp_root = Path("/tmp/gms-grabber")
        if temp_root.exists():
            shutil.rmtree(temp_root)
        temp_root.mkdir(parents=True)
        
        futures = []
        for apk in source_overlays:
            decomp_dir = temp_root / apk.name
            futures.append(executor.submit(
                subprocess.check_call,
                _apktool_cmd(4)[0] + ["d", str(apk), "-o", str(decomp_dir), "-f"]
            ))
            
        for future in as_completed(futures):
            future.result()

        print(f"[grabber] decompiled all source overlays; scanning for resources")
        
        for decomp_dir in sorted(temp_root.iterdir()):
            default_values_dir = decomp_dir / "res" / "values"
            if not default_values_dir.exists():
                continue
            for xml_path in sorted(default_values_dir.glob("*.xml")):
                tree = ET.parse(xml_path)
                for child in tree.getroot():
                    name = child.attrib.get("name")
                    if not name:
                        continue
                    owner = _overlay_scalar_owner(name, child, overlay_specs)
                    if owner is not None:
                        overlay_specs[owner]["resource_names"].add(name)

        for decomp_dir in sorted(temp_root.iterdir()):
            manifest_path = decomp_dir / "AndroidManifest.xml"
            target_pkg = "android"
            if manifest_path.exists():
                tree = ET.parse(manifest_path)
                overlay_elem = tree.getroot().find('overlay')
                if overlay_elem is not None:
                    target_pkg = overlay_elem.get('{http://schemas.android.com/apk/res/android}targetPackage', "android")

            target_pkg = TARGET_REDIRECTION_MAP.get(target_pkg, target_pkg)

            res_dir = decomp_dir / "res"
            if not res_dir.exists():
                continue
            for xml_path in sorted(res_dir.glob("values/*.xml")):
                if xml_path.name == "public.xml":
                    continue
                tree = ET.parse(xml_path)
                rel_path = xml_path.relative_to(decomp_dir)
                for child in list(tree.getroot()):
                    name = child.attrib.get("name")
                    if not name:
                        continue
                    owner = _overlay_scalar_owner(name, child, overlay_specs)
                    if owner is not None:
                        key = (owner, target_pkg)
                        target_bucket = grabbed.setdefault(key, {})
                        file_bucket = target_bucket.setdefault(rel_path, {})
                        new_el = ET.fromstring(ET.tostring(child, encoding="unicode"))
                        if owner == "GmsAndroidOverlay" and name in file_bucket:
                            _merge_resource_elements(file_bucket[name], new_el)
                        elif name not in file_bucket:
                            file_bucket[name] = new_el

        shutil.rmtree(temp_root)

    generated_map: dict[str, list[str]] = {}
    
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    for (owner, target_pkg), resource_map in grabbed.items():
        required_by = overlay_specs[owner]["required_by"]
        
        if target_pkg == "android":
            overlay_name = owner
        else:
            suffix = target_pkg.split(".")[-1].capitalize()
            overlay_name = f"{owner}{suffix}"
            
        out = synthesize_overlay_module(overlay_name, target_pkg, 1000, output_dir)
        for rel_path, elements_dict in resource_map.items():
            _write_xml_resources(out / rel_path, list(elements_dict.values()))
            
        generated_map.setdefault(required_by, []).append(overlay_name)
        print(f"[grabber] synthesized {overlay_name} targeting {target_pkg} (files={len(resource_map)})")

    for owner, spec in overlay_specs.items():
        required_by = spec["required_by"]
        if required_by not in generated_map and spec.get("fallback_strings"):
            out = synthesize_overlay_module(owner, "android", 1000, output_dir)
            _write_fallback_string_resources(out, spec["fallback_strings"])
            generated_map.setdefault(required_by, []).append(owner)
            print(f"[grabber] used fallbacks for {owner}")
            
    return generated_map


def required_overlay_specs(per_app_overlay_specs: dict[str, dict[str, object]]) -> dict[str, dict[str, object]]:
    specs = {
        overlay_name: {"required_by": required_by}
        for overlay_name, required_by in SHARED_OVERLAY_REQUIRED_BY.items()
    }
    for overlay_name, spec in per_app_overlay_specs.items():
        specs[overlay_name] = {"required_by": spec["required_by"]}
    return specs


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


def update_required_modules(common_bp_path: Path, generated_map: dict[str, list[str]]):
    if not common_bp_path.exists():
        print(f"Blueprint {common_bp_path} not found; skipping required wiring.")
        return

    print(f"[overlay] update_required_modules path={common_bp_path}")
    content = common_bp_path.read_text(encoding="utf-8")
    
    all_known_overlays = set()
    for overlays in generated_map.values():
        all_known_overlays.update(overlays)
    
    for module_name, overlay_names in generated_map.items():
        block_info = _find_android_app_import_block(content, module_name)
        if block_info is None:
            continue

        block_start, block_end, block = block_info
        required_match = re.search(r"(?ms)^    required:\s*\[\n(.*?)^    \],\n", block)
        if required_match:
            required = re.findall(r'"([^"]+)"', required_match.group(1))
        else:
            required = []
            
        required = [r for r in required if not (r.endswith("Overlay") and (r in all_known_overlays or r == module_name + "Overlay"))]
        
        for name in overlay_names:
            if name not in required:
                required.append(name)
                
        updated_block = _replace_or_add_list_property(block, "required", sorted(list(set(required))))
        content = content[:block_start] + updated_block + content[block_end:]

    common_bp_path.write_text(content, encoding="utf-8")


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
                    return str(inner)
        return str(source)

    cached = _find_cached_source(device)
    if cached is not None:
        return str(cached)

    return None


if __name__ == "__main__":
    parser = ArgumentParser()
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from fetch_factory import fetch_apktool_jar, fetch_latest_factory
    if not os.environ.get("APKTOOL_JAR"):
        try:
            os.environ["APKTOOL_JAR"] = fetch_apktool_jar()
        except Exception as e:
            print(f"[fetch] apktool auto-fetch failed ({e}); falling back to system apktool")

    source = None
    if "--fetch" in sys.argv:
        idx = sys.argv.index("--fetch")
        sys.argv.pop(idx)
        release = "bp4a"
        if idx < len(sys.argv) and not sys.argv[idx].startswith("-"):
            release = sys.argv.pop(idx)
        source = fetch_latest_factory(release=release)
    else:
        source = _resolve_source(sys.argv, os.environ.get("FETCH_DEVICE", "caiman"))

    if source is not None and source not in sys.argv:
        sys.argv.append(source)

    DEVICE = "common"
    VENDOR = "gms/overlays"
    module = ExtractUtilsModule(
        DEVICE,
        VENDOR,
        device_rel_path=f"vendor/{VENDOR}",
        blob_fixups={},
        lib_fixups={},
        extract_fns=extract_fns,
    )
    utils = ExtractUtils.device(module)
    utils.run()

    for stale in ["common/common-vendor.mk", "common/Android.mk", "common/Android.bp", "common/BoardConfigVendor.mk"]:
        stale_path = Path(stale)
        if stale_path.exists():
            stale_path.unlink()
    stale_dir = Path("common")
    if stale_dir.exists() and not any(stale_dir.iterdir()):
        stale_dir.rmdir()

    overlay_dir = Path(f"{DEVICE}/proprietary/product/overlay")
    overlay_dir.mkdir(parents=True, exist_ok=True)
    
    source_path = Path(source) if source else None
    if source_path:
        generated_map = grab_dynamic_overlays(source_path, overlay_dir, DYNAMIC_PER_APP_OVERLAYS)
        update_required_modules(
            Path("..") / DEVICE / "Android.bp",
            generated_map,
        )

    for stray_apk in overlay_dir.glob("*.apk"):
        print(f"[cleanup] removing stray APK: {stray_apk.name}")
        stray_apk.unlink()

    bp_path = Path("Android.bp")
    if bp_path.exists():
        bp_path.unlink()
