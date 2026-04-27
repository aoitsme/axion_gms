#!/usr/bin/env -S PYTHONPATH=../../tools/extract-utils python3
#
# SPDX-FileCopyrightText: 2025-2026 AxionOS
# SPDX-License-Identifier: Apache-2.0
#

import os
import re
import subprocess
import sys
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

namespace_imports = []

extract_fns: extract_fns_user_type = {
    pixel_factory_image_regex: extract_pixel_factory_image,
    pixel_firmware_regex: extract_pixel_firmware,
}

module = ExtractUtilsModule(
    'common',
    'gms',
    device_rel_path='vendor/gms',
    namespace_imports=namespace_imports,
    extract_fns=extract_fns,
)

GMS_PHONY_BUNDLE_FILE = "propietary-pkgs-bundle.txt"
GMS_VARIANT_BUNDLES = (
    ("pico", "PicoPkgs"),
    ("core", "CorePkgs"),
    (None, "FullPkgs"),
)
GMS_OPTIONAL_BUNDLES = {
    "TelecommPkgs": {
        "flag": "TARGET_INCLUDE_GOOGLE_TELECOMM",
        "defaults": {
            "pico": "false",
            "core": "true",
            "default": "true",
        },
    },
    "PartnerPkgs": {
        "flag": "TARGET_INCLUDE_PARTNER_SETUP",
        "defaults": {
            "pico": "false",
            "core": "false",
            "default": "true",
        },
    },
}


def load_phony_bundles(root_dir: Path) -> dict[str, list[str]]:
    bundle_file = root_dir / GMS_PHONY_BUNDLE_FILE
    bundles: dict[str, list[str]] = {}
    current_bundle: str | None = None

    if not bundle_file.exists():
        return bundles

    for raw_line in bundle_file.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        if line.startswith("[") and line.endswith("]"):
            current_bundle = line[1:-1].strip()
            if current_bundle:
                bundles.setdefault(current_bundle, [])
            continue

        if current_bundle is None:
            continue

        dep = line.split("#", 1)[0].strip()
        if dep:
            bundles[current_bundle].append(dep)

    return {name: deps for name, deps in bundles.items() if deps}


def render_phony_modules(bundles: dict[str, list[str]]) -> str:
    out = []
    for name, deps in bundles.items():
        out.append('phony {')
        out.append(f'    name: "{name}",')
        out.append('    required: [')
        for dep in deps:
            out.append(f'        "{dep}",')
        out.append('    ],')
        out.append('}')
        out.append('')
    return "\n".join(out).rstrip() + "\n"


def sync_phony_modules(bp_path: Path, bundles: dict[str, list[str]]):
    if not bp_path.exists() or not bundles:
        return

    content = bp_path.read_text()
    content = re.sub(r'\n?phony \{\n.*?\n\}\n?', "\n", content, flags=re.DOTALL)
    content = content.rstrip() + "\n\n" + render_phony_modules(bundles)
    bp_path.write_text(content)
    print(f"[gms] synced phony modules from {GMS_PHONY_BUNDLE_FILE} into {bp_path}")


def render_product_package_selection(bundles: dict[str, list[str]]) -> str:
    out = ["TARGET_GAPPS_VARIANT ?= gms", "", "# Map GMS variant to Soong phony modules"]
    optional_bundles = {
        name: config for name, config in GMS_OPTIONAL_BUNDLES.items()
        if name in bundles
    }

    emitted_variant = False
    for variant, package in GMS_VARIANT_BUNDLES:
        if package not in bundles:
            continue

        if variant is None:
            out.append("else")
            default_key = "default"
        else:
            prefix = "ifeq" if not emitted_variant else "else ifeq"
            out.append(f"{prefix} ($(strip $(TARGET_GAPPS_VARIANT)),{variant})")
            default_key = variant
        emitted_variant = True

        out.append(f"    PRODUCT_PACKAGES += {package}")
        for config in optional_bundles.values():
            default_value = config["defaults"].get(default_key)
            if default_value is not None:
                out.append(f"    {config['flag']} ?= {default_value}")

    if emitted_variant:
        out.append("endif")

    for package, config in optional_bundles.items():
        out.extend([
            "",
            f"ifeq ($(strip $({config['flag']})),true)",
            f"    PRODUCT_PACKAGES += {package}",
            "endif",
        ])

    return "\n".join(out) + "\n"


def auto_update_package_mapping(root_dir: Path):
    mapping = {}
    base_dir = root_dir / "common" / "proprietary"
    map_file = root_dir / "proprietary-pkg-map.txt"
    
    if not base_dir.exists():
        return {}

    print(f"[gms] scanning {base_dir} for APKs to update package mapping")
    for apk in base_dir.glob("**/*.apk"):
        mod_name = apk.stem
        try:
            out = subprocess.check_output(["aapt", "dump", "badging", str(apk)], stderr=subprocess.DEVNULL).decode("utf-8")
            for line in out.splitlines():
                if line.startswith("package: name="):
                    m = re.search(r"name='([^']*)'", line)
                    if m:
                        pkg = m.group(1)
                        mapping[mod_name] = pkg
                        break
        except Exception:
            continue

    if mapping:
        current_map = {}
        if map_file.exists():
            for line in map_file.read_text().splitlines():
                if "=" in line:
                    k, v = line.split("=", 1)
                    current_map[k.strip()] = v.strip()
        
        current_map.update(mapping)

        with open(map_file, "w", encoding="utf-8") as f:
            for mod, pkg in sorted(current_map.items()):
                f.write(f"{mod}={pkg}\n")
        print(f"[gms] updated {map_file} with {len(current_map)} entries")
    
    return mapping


def load_required_map(root_dir: Path):
    mapping = {}
    map_file = root_dir / "proprietary-required-map.txt"
    if map_file.exists():
        for line in map_file.read_text().splitlines():
            if line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            mapping[k.strip()] = [i.strip() for i in v.split(",") if i.strip()]
    return mapping


def inject_required_dependencies(bp_path: Path, required_map: dict[str, list[str]]):
    if not bp_path.exists() or not required_map:
        return

    content = bp_path.read_text()
    
    for mod_name, deps in required_map.items():
        block_info = _find_android_app_import_block(content, mod_name)
        if block_info is None:
            continue

        block_start, block_end, block = block_info
        required_match = re.search(r"(?ms)^    required:\s*\[\n(.*?)^    \],\n", block)
        existing_deps = re.findall(r'"([^"]+)"', required_match.group(1)) if required_match else []
        updated_block = _replace_or_add_list_property(
            block,
            "required",
            sorted(set(existing_deps + deps)),
        )
        content = content[:block_start] + updated_block + content[block_end:]
    
    bp_path.write_text(content)
    print(f"[gms] injected dependencies from proprietary-required-map.txt into {bp_path}")


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
        while (
            block_end != -1
            and content.count("{", block_start, block_end + 2)
            != content.count("}", block_start, block_end + 2)
        ):
            block_end = content.find("\n}\n", block_end + 1)
        if block_end == -1:
            return None
        block_end += len("\n}\n")
        block = content[block_start:block_end]
        if module_marker in block:
            return block_start, block_end, block
        cursor = block_end


def prune_required_dependencies(bp_path: Path, extra_allowed: set[str] | None = None):
    if not bp_path.exists():
        return

    content = bp_path.read_text()
    extra_allowed = extra_allowed or set()
    
    defined_modules = set(re.findall(r'name: "([^"]+)"', content))
    
    overlay_root = bp_path.parent / "proprietary" / "product" / "overlay"
    if overlay_root.exists():
        for d in overlay_root.iterdir():
            if d.is_dir():
                defined_modules.add(d.name)

    def prune_block(match):
        prefix = match.group(1)
        items_str = match.group(2)
        suffix = match.group(3)
        
        items = re.findall(r'"([^"]+)"', items_str)
        valid_items = [
            i for i in items
            if i in defined_modules or i in extra_allowed or i.startswith("GmsCore")
        ]
        
        if not valid_items:
            return ""
            
        new_items = "".join(f'        "{i}",\n' for i in sorted(list(set(valid_items))))
        return f'{prefix}\n{new_items}    {suffix}'

    content = re.sub(r'(    required: \[)(.*?)(\],)', prune_block, content, flags=re.DOTALL)
    
    bp_path.write_text(content)
    print(f"[gms] pruned non-existent dependencies from {bp_path}")


def grab_gms_properties(source_path: Path, root_dir: Path):
    if not source_path.exists():
        return

    print(f"[gms] grabbing SetupWizard and GMS properties from {source_path}")
    props = set()
    
    key_patterns = [
        re.compile(r'^ro\.setupwizard\..*'),
        re.compile(r'^setupwizard\..*'),
        re.compile(r'^ro\.com\.google\..*'),
        re.compile(r'^pixel_legal\..*'),
        re.compile(r'^ro\.opa\..*'),
        re.compile(r'^ro\.pixel\..*'),
        re.compile(r'^persist\.google\..*'),
        re.compile(r'^ro\.storage_manager\..*'),
    ]

    GMS_IDENTIFIERS = {
        "com.google.android.gms",
        "com.android.vending",
    }

    EXCLUDE_PROPS = {
        "ro.com.google.ime.height_ratio",
        "ro.com.google.ime.kb_pad_port_b",
        "ro.com.google.clientidbase",
    }

    for p in ["system", "system_ext", "product"]:
        for build_prop in [source_path / p / "build.prop", source_path / p / "etc" / "build.prop"]:
            if not build_prop.exists():
                continue
            with open(build_prop, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key = line.split("=", 1)[0]
                    if key in EXCLUDE_PROPS:
                        continue
                    
                    match = any(pat.match(key) for pat in key_patterns)
                    
                    if not match:
                        match = any(ident in line for ident in GMS_IDENTIFIERS)
                        
                    if match:
                        props.add(line)

    if props:
        out_mk = root_dir / "products" / "gms-props.mk"
        out_mk.parent.mkdir(parents=True, exist_ok=True)
        with open(out_mk, "w", encoding="utf-8") as f:
            f.write("# Automatically generated file. DO NOT MODIFY\n")
            f.write("# Generated by vendor/gms/extract-files.py\n\n")
            f.write("PRODUCT_PRODUCT_PROPERTIES += \\\n")
            sorted_props = sorted(list(props))
            for i, prop in enumerate(sorted_props):
                sep = " \\" if i < len(sorted_props) - 1 else ""
                f.write(f"    {prop}{sep}\n")
        print(f"[gms] synthesized {out_mk} with {len(props)} properties")


def post_regenerate_customizations(source_path: Path | None = None):
    MY_DIR = Path(__file__).parent
    DEVICE_DIR = MY_DIR / 'common'
    COMMON_VENDOR_MK = DEVICE_DIR / 'common-vendor.mk'
    ANDROIDMK = DEVICE_DIR / 'Android.mk'
    ANDROIDBP = DEVICE_DIR / 'Android.bp'

    if not COMMON_VENDOR_MK.exists():
        return

    if ANDROIDMK.exists():
        content = ANDROIDMK.read_text()
        content = re.sub(r'TARGET_DEVICE', 'TARGET_ARCH', content)
        ANDROIDMK.write_text(content)

    phony_bundles = load_phony_bundles(MY_DIR)
    sync_phony_modules(ANDROIDBP, phony_bundles)

    required_map = load_required_map(MY_DIR)
    inject_required_dependencies(ANDROIDBP, required_map)

    auto_update_package_mapping(MY_DIR)

    phony_deps = {dep for deps in phony_bundles.values() for dep in deps}
    prune_required_dependencies(ANDROIDBP, phony_deps)

    if source_path:
        grab_gms_properties(source_path, MY_DIR)

    original_content = COMMON_VENDOR_MK.read_text()
    copy_files = []
    copy_pattern = re.compile(r'PRODUCT_COPY_FILES \+= (.*?)(?=\n\n|\nPRODUCT_PACKAGES)', re.DOTALL)
    match = copy_pattern.search(original_content)
    if match:
        for line in match.group(1).splitlines():
            l = line.strip()
            if l.endswith('\\'): l = l[:-1].strip()
            if l: copy_files.append(l)

    out = '# Automatically generated file. DO NOT MODIFY\n#\n'
    out += '# Generated by vendor/gms/extract-files.py\n\n'
    out += 'PRODUCT_SOONG_NAMESPACES += \\\n    vendor/gms/common\n\n'
    
    if copy_files:
        out += 'PRODUCT_COPY_FILES += \\\n'
        for i, f in enumerate(copy_files):
            sep = ' \\' if i < len(copy_files) - 1 else ''
            out += f'    {f}{sep}\n'
        out += '\n'

    out += render_product_package_selection(phony_bundles)

    COMMON_VENDOR_MK.write_text(out)
    print(f"[gms] updated {COMMON_VENDOR_MK} with clean variant selection logic")


if __name__ == '__main__':
    regenerate_only = '--regenerate_makefiles' in sys.argv
    only_props = '--only-props' in sys.argv

    if regenerate_only:
        MY_DIR = Path(__file__).parent
        DEVICE_DIR = MY_DIR / 'common'
        for f in ['Android.mk', 'Android.bp', 'common-vendor.mk', 'BoardConfig.mk']:
            (DEVICE_DIR / f).unlink(missing_ok=True)

    source = None
    if '--fetch' in sys.argv or only_props:
        idx = sys.argv.index('--fetch') if '--fetch' in sys.argv else -1
        if idx != -1:
            sys.argv.pop(idx)
        
        release = "bp4a"
        if idx != -1 and idx < len(sys.argv) and not sys.argv[idx].startswith("-"):
            release = sys.argv.pop(idx)
        
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from fetch_factory import fetch_latest_factory
        source = fetch_latest_factory(release=release)
        if not only_props:
            sys.argv.append(source)
    else:
        pass

    if only_props:
        if source:
            grab_gms_properties(Path(source), Path(__file__).parent)
        sys.exit(0)

    utils = ExtractUtils.device(module)
    utils.run()
    
    if not source:
        for arg in sys.argv[1:]:
            if not arg.startswith("-") and Path(arg).is_dir():
                source = Path(arg)
                break
    
    post_regenerate_customizations(source_path=Path(source) if source else None)
