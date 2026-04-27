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

GMS_PHONY_MODULES = """
phony {
    name: "GmsCore",
    required: [
        "PrebuiltGmsCoreVic",
        "PrebuiltGmsCoreVic_AdsDynamite",
        "PrebuiltGmsCoreVic_CronetDynamite",
        "PrebuiltGmsCoreVic_DynamiteLoader",
        "PrebuiltGmsCoreVic_DynamiteModulesA",
        "PrebuiltGmsCoreVic_DynamiteModulesC",
        "PrebuiltGmsCoreVic_GoogleCertificates",
        "PrebuiltGmsCoreVic_MapsDynamite",
        "PrebuiltGmsCoreVic_MeasurementDynamite",
        "TfliteDynamitePrebuilt",
        "VisionBarcodePrebuilt",
    ],
}

phony {
    name: "GmsCoreMain",
    required: [
        "AndroidPlatformServices",
        "GmsCore",
        "GoogleExtShared",
        "GoogleFeedback",
        "GoogleServicesFramework",
        "MlkitBarcodeUIPrebuilt",
        "Phonesky",
    ],
}

phony {
    name: "GmsCoreAndroid",
    required: [
        "AccessibilityMenu",
        "AndroidAutoStubPrebuilt",
        "CccDkTimeSyncService",
        "DocumentsUIGoogle",
        "GmsCoreMain",
        "GoogleOneTimeInitializer",
        "GooglePrintRecommendationService",
        "GoogleRestorePrebuilt",
        "LatinIMEGooglePrebuilt",
        "PartnerSetupPrebuilt",
        "SetupWizardPixelPrebuilt_v802960446",
        "SetupWizardPrebuilt_v811313066",
        "TagGoogle",
        "WellbeingPrebuilt",
        "org.carconnectivity.android.digitalkey.timesync",
    ],
}

phony {
    name: "GmsCoreFull",
    required: [
        "CalculatorGooglePrebuilt_85006267",
        "CalendarGooglePrebuilt",
        "GmsCoreAndroid",
        "GoogleContacts",
        "GoogleDialer",
        "MarkupGoogle_v2",
        "PrebuiltBugle",
        "PrebuiltDeskClockGoogle_76007351",
        "Velvet",
        "talkback",
    ],
}
"""

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
        pattern = re.compile(rf'(android_app_import \{{.*?name: "{mod_name}",.*?)(\n\}})', re.DOTALL)
        
        def inject_block(match):
            block_body = match.group(1)
            footer = match.group(2)
            
            req_match = re.search(r'    required: \[(.*?)\],', block_body, re.DOTALL)
            if req_match:
                existing_deps = re.findall(r'"([^"]+)"', req_match.group(1))
                new_deps = sorted(list(set(existing_deps + deps)))
                new_req = "    required: [\n" + "".join(f'        "{d}",\n' for d in new_deps) + "    ],"
                return re.sub(r'    required: \[.*?\],', new_req, block_body, flags=re.DOTALL) + footer
            else:
                new_req = "\n    required: [\n" + "".join(f'        "{d}",\n' for d in deps) + "    ],"
                return block_body + new_req + footer

        content = pattern.sub(inject_block, content)
    
    bp_path.write_text(content)
    print(f"[gms] injected dependencies from proprietary-required-map.txt into {bp_path}")


def prune_required_dependencies(bp_path: Path):
    if not bp_path.exists():
        return

    content = bp_path.read_text()
    
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
        valid_items = [i for i in items if i in defined_modules or i.startswith("GmsCore")]
        
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

    if ANDROIDBP.exists():
        content = ANDROIDBP.read_text()
        if 'name: "GmsCoreMain"' not in content:
            with open(ANDROIDBP, "a") as f:
                f.write(GMS_PHONY_MODULES)
            print(f"[gms] restored phony modules to {ANDROIDBP}")

    required_map = load_required_map(MY_DIR)
    inject_required_dependencies(ANDROIDBP, required_map)

    auto_update_package_mapping(MY_DIR)

    prune_required_dependencies(ANDROIDBP)

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

    out += 'TARGET_GAPPS_VARIANT ?= gms\n'
    out += 'ifeq ($(strip $(TARGET_CORE_GMS)),true)\n'
    out += '    TARGET_GAPPS_VARIANT := core\n'
    out += 'endif\n\n'
    out += '# Map Gapps variant to Soong phony modules\n'
    out += 'ifeq ($(strip $(TARGET_GAPPS_VARIANT)),pico)\n'
    out += '    PRODUCT_PACKAGES += GmsCoreMain\n'
    out += 'else ifeq ($(strip $(TARGET_GAPPS_VARIANT)),core)\n'
    out += '    PRODUCT_PACKAGES += GmsCoreAndroid\n'
    out += 'else\n'
    out += '    PRODUCT_PACKAGES += GmsCoreFull\n'
    out += 'endif\n'

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
