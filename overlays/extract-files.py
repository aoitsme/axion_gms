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

def overlay_fixup(path: str):
    print(f"Applying overlay fixup to {path} (APK file)")
    my_dir = os.path.dirname(os.path.abspath(__file__))
    folder_name = Path(path).stem
    decomp_dir = path + "_decomp"
    package_name = folder_name
    try:
        subprocess.check_call(["apktool", "d", path, "-o", decomp_dir, "-f"])
        print(f"Decompiled to {decomp_dir}")
    except subprocess.CalledProcessError as e:
        print(f"apktool failed: {e}")
        return
    except FileNotFoundError:
        print("apktool not found. Please install apktool.")
        return
    os.unlink(path)
    print(f"Unlinked APK: {path}")
    folder = decomp_dir
    apktool_yml = os.path.join(folder, "apktool.yml")
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
        shutil.copy2(template_path, bp_path)
        with open(bp_path, "r", encoding="utf-8") as f:
            content = f.read()
        content = content.replace("dummy", overlay_pkg)
        with open(bp_path, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"Generated Android.bp for {overlay_pkg}")
    for root, _dirs, files in os.walk(folder):
        for file in files:
            if file == "default_wallpaper.png":
                os.unlink(os.path.join(root, file))
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
    target_dir = path.rsplit(".apk", 1)[0]
    os.rename(decomp_dir, target_dir)
    print(f"Renamed {decomp_dir} to {target_dir} (now a directory)")
    print(f"Overlay fixup completed for {package_name}. Directory ready at {os.path.isdir(target_dir)}")
lib_fixups: lib_fixups_user_type = {}
blob_fixups: blob_fixups_user_type = {}
extract_fns: extract_fns_user_type = {
    pixel_factory_image_regex: extract_pixel_factory_image,
    pixel_firmware_regex: extract_pixel_firmware,
}

if __name__ == "__main__":
    parser = ArgumentParser()
    unknown_args = sys.argv[1:]
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
    sys.argv = [sys.argv[0]] + unknown_args
    utils.run()
    overlay_dir = Path(f"{DEVICE}/proprietary/product/overlay")
    if overlay_dir.exists():
        for apk_path in overlay_dir.glob("*.apk"):
            overlay_fixup(str(apk_path))
    bp_path = Path("Android.bp")
    if bp_path.exists():
        bp_path.unlink()
    product_mk = Path(f"{DEVICE}/{DEVICE}-vendor.mk")
    if product_mk.exists():
        with open(product_mk, "r") as f:
            content = f.read()
        lines = content.splitlines()
        new_lines = []
        in_packages_block = False
        for line in lines:
            if "PRODUCT_PACKAGES +=" in line:
                in_packages_block = True
                continue
            if in_packages_block and line.strip().startswith("\\"):
                continue
            if in_packages_block and not line.strip().startswith(" ") and "=" in line:
                in_packages_block = False
            if not in_packages_block:
                new_lines.append(line)
        content = "\n".join(new_lines)
        overlay_dirs = [d.name for d in overlay_dir.iterdir() if d.is_dir()]
        if overlay_dirs:
            new_block = "\nPRODUCT_PACKAGES +="
            for d in sorted(overlay_dirs):
                new_block += f" \\\n {d}"
            new_block += "\n"
            content += new_block
        with open(product_mk, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"Updated {product_mk} with overlay directories: {', '.join(overlay_dirs)}")
    else:
        print(f"Makefiles {product_mk} not found; manual addition may be needed.")
