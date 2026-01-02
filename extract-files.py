#!/usr/bin/env -S PYTHONPATH=../../tools/extract-utils python3
#
# SPDX-FileCopyrightText: 2025 LineageOS
# SPDX-FileCopyrightText: 2025 AxionAOSP
# SPDX-License-Identifier: Apache-2.0
#

from extract_utils.main import (
    ExtractUtils,
    ExtractUtilsModule,
)

namespace_imports = []

module = ExtractUtilsModule(
    'common',
    'gms',
    device_rel_path='vendor/gms',
    namespace_imports=namespace_imports,
)

def post_regenerate_customizations():
    import os
    import re
    from pathlib import Path

    MY_DIR = Path(__file__).parent
    DEVICE_DIR = MY_DIR / 'common'
    COMMON_VENDOR_MK = DEVICE_DIR / 'common-vendor.mk'
    ANDROIDMK = DEVICE_DIR / 'Android.mk'
    PRODUCTMK = DEVICE_DIR / 'common-vendor.mk'
    ANDROIDBP = DEVICE_DIR / 'Android.bp'
    BOARDMK = DEVICE_DIR / 'BoardConfig.mk'

    if not COMMON_VENDOR_MK.exists():
        raise FileNotFoundError(f"{COMMON_VENDOR_MK} not generated; run extraction first?")

    if ANDROIDMK.exists():
        with open(ANDROIDMK, 'r') as f:
            content = f.read()
        content = re.sub(r'TARGET_DEVICE', 'TARGET_ARCH', content)
        with open(ANDROIDMK, 'w') as f:
            f.write(content)

    if PRODUCTMK.exists():
        with open(PRODUCTMK, 'r') as f:
            content = f.read()
        content = re.sub(r'vendor/gms/common{2,}/', 'vendor/gms/common/', content)
        content = re.sub(r'(vendor/gms/)(?!common)', r'\1common/', content)
        with open(PRODUCTMK, 'w') as f:
            f.write(content)

    for mk_file in [ANDROIDBP, ANDROIDMK, BOARDMK, PRODUCTMK]:
        if mk_file.exists():
            with open(mk_file, 'r') as f:
                content = f.read()
            content = re.sub(r'device/gms//setup-makefiles\.sh', 'vendor/gms/setup-makefiles.sh', content)
            with open(mk_file, 'w') as f:
                f.write(content)

    with open(COMMON_VENDOR_MK, 'r') as f:
        content = f.read()

    def extract_lists(content):
        copy_lines = []
        pkg_lines = []
        copy_start = content.find('PRODUCT_COPY_FILES += ')
        if copy_start != -1:
            copy_end = content.find('PRODUCT_PACKAGES += ', copy_start)
            if copy_end == -1:
                copy_end = len(content)
            copy_text = content[copy_start:copy_end]
            for line in copy_text.splitlines()[1:]:
                l = line.strip()
                if l.endswith('\\'):
                    l = l[:-1].strip()
                if l and l.startswith('vendor/gms/common/proprietary/'):
                    copy_lines.append(l)

        pkg_start = content.find('PRODUCT_PACKAGES += ')
        if pkg_start != -1:
            pkg_text = content[pkg_start:]
            for line in pkg_text.splitlines()[1:]:
                l = line.strip()
                if l.endswith('\\'):
                    l = l[:-1].strip()
                if l and not l.startswith('#') and l:
                    pkg_lines.append(l)
        return copy_lines, pkg_lines

    copy_lines, pkg_lines = extract_lists(content)

    extras_to_remove = [
        'AdaptiveVPNPrebuilt-10435', 'WallpaperAIPrebuilt_10000372', 'AvatarPickerGoogle',
        'Chrome-Stub', 'CreativeAssistant', 'DreamlinerDreamsPrebuilt_100894',
        'DreamlinerPrebuilt_22000020', 'DreamlinerUpdater', 'Drive', 'Maps', 'MeetPrebuilt_20250518',
        'Photos', 'PixelAIPrebuilt', 'PixelSupportPrebuilt', 'PixelWallpapers2024',
        'PrebuiltGmail', 'RecorderPrebuilt_725581069', 'SatelliteClient', 'PixelSatelliteGatewayPrebuilt',
        'TipsPrebuilt_v6.0.0.734377952', 'TrichromeLibrary-Stub',
        'VendorSatelliteService', 'WebViewGoogle-Stub', 'YouTube'
    ]

    core_copy_list = [
        'vendor/gms/common/proprietary/product/etc/default-permissions/default-permissions.xml:$(TARGET_COPY_OUT_PRODUCT)/etc/default-permissions/default-permissions.xml',
        'vendor/gms/common/proprietary/product/etc/permissions/com.google.android.dialer.support.xml:$(TARGET_COPY_OUT_PRODUCT)/etc/permissions/com.google.android.dialer.support.xml',
        'vendor/gms/common/proprietary/product/etc/permissions/privapp-permissions-google-p.xml:$(TARGET_COPY_OUT_PRODUCT)/etc/permissions/privapp-permissions-google-p.xml',
        'vendor/gms/common/proprietary/product/etc/permissions/split-permissions-google.xml:$(TARGET_COPY_OUT_PRODUCT)/etc/permissions/split-permissions-google.xml',
        'vendor/gms/common/proprietary/product/etc/security/fsverity/gms_fsverity_cert.der:$(TARGET_COPY_OUT_PRODUCT)/etc/security/fsverity/gms_fsverity_cert.der',
        'vendor/gms/common/proprietary/product/etc/security/fsverity/play_store_fsi_cert.der:$(TARGET_COPY_OUT_PRODUCT)/etc/security/fsverity/play_store_fsi_cert.der',
        'vendor/gms/common/proprietary/product/etc/sysconfig/adaptivecharging.xml:$(TARGET_COPY_OUT_PRODUCT)/etc/sysconfig/adaptivecharging.xml',
        'vendor/gms/common/proprietary/product/etc/sysconfig/contextual_search.xml:$(TARGET_COPY_OUT_PRODUCT)/etc/sysconfig/contextual_search.xml',
        'vendor/gms/common/proprietary/product/etc/sysconfig/google.xml:$(TARGET_COPY_OUT_PRODUCT)/etc/sysconfig/google.xml',
        'vendor/gms/common/proprietary/product/etc/sysconfig/google_build.xml:$(TARGET_COPY_OUT_PRODUCT)/etc/sysconfig/google_build.xml',
        'vendor/gms/common/proprietary/product/etc/sysconfig/google-hiddenapi-package-whitelist.xml:$(TARGET_COPY_OUT_PRODUCT)/etc/sysconfig/google-hiddenapi-package-whitelist.xml',
        'vendor/gms/common/proprietary/product/etc/sysconfig/google-initial-package-stopped-states.xml:$(TARGET_COPY_OUT_PRODUCT)/etc/sysconfig/google-initial-package-stopped-states.xml',
        'vendor/gms/common/proprietary/product/etc/sysconfig/google-install-constraints-package-allowlist.xml:$(TARGET_COPY_OUT_PRODUCT)/etc/sysconfig/google-install-constraints-package-allowlist.xml',
        'vendor/gms/common/proprietary/product/etc/sysconfig/google-staged-installer-whitelist.xml:$(TARGET_COPY_OUT_PRODUCT)/etc/sysconfig/google-staged-installer-whitelist.xml',
        'vendor/gms/common/proprietary/product/etc/sysconfig/nexus.xml:$(TARGET_COPY_OUT_PRODUCT)/etc/sysconfig/nexus.xml',
        'vendor/gms/common/proprietary/product/etc/sysconfig/nga.xml:$(TARGET_COPY_OUT_PRODUCT)/etc/sysconfig/nga.xml',
        'vendor/gms/common/proprietary/product/etc/sysconfig/pixel_experience_2017.xml:$(TARGET_COPY_OUT_PRODUCT)/etc/sysconfig/pixel_experience_2017.xml',
        'vendor/gms/common/proprietary/product/etc/sysconfig/pixel_experience_2018.xml:$(TARGET_COPY_OUT_PRODUCT)/etc/sysconfig/pixel_experience_2018.xml',
        'vendor/gms/common/proprietary/product/etc/sysconfig/pixel_experience_2019.xml:$(TARGET_COPY_OUT_PRODUCT)/etc/sysconfig/pixel_experience_2019.xml',
        'vendor/gms/common/proprietary/product/etc/sysconfig/pixel_experience_2019_midyear.xml:$(TARGET_COPY_OUT_PRODUCT)/etc/sysconfig/pixel_experience_2019_midyear.xml',
        'vendor/gms/common/proprietary/product/etc/sysconfig/pixel_experience_2020.xml:$(TARGET_COPY_OUT_PRODUCT)/etc/sysconfig/pixel_experience_2020.xml',
        'vendor/gms/common/proprietary/product/etc/sysconfig/pixel_experience_2020_midyear.xml:$(TARGET_COPY_OUT_PRODUCT)/etc/sysconfig/pixel_experience_2020_midyear.xml',
        'vendor/gms/common/proprietary/product/etc/sysconfig/preinstalled-packages-product-pixel-2017-and-newer.xml:$(TARGET_COPY_OUT_PRODUCT)/etc/sysconfig/preinstalled-packages-product-pixel-2017-and-newer.xml',
        'vendor/gms/common/proprietary/system/etc/permissions/privapp-permissions-google.xml:$(TARGET_COPY_OUT_SYSTEM)/etc/permissions/privapp-permissions-google.xml',
        'vendor/gms/common/proprietary/system_ext/etc/permissions/privapp-permissions-google-se.xml:$(TARGET_COPY_OUT_SYSTEM_EXT)/etc/permissions/privapp-permissions-google-se.xml'
    ]

    core_pkg_list = [
        'AndroidPlatformServices',
        'ConfigUpdater',
        'GoogleRestorePrebuilt-v766453',
        'GoogleServicesFramework',
        'MlkitBarcodeUIPrebuilt',
        'Phonesky',
        'PlayAutoInstallConfig',
        'PrebuiltGmsCoreVic',
        'PrebuiltGmsCoreVic_AdsDynamite',
        'PrebuiltGmsCoreVic_CronetDynamite',
        'PrebuiltGmsCoreVic_DynamiteLoader',
        'PrebuiltGmsCoreVic_DynamiteModulesA',
        'PrebuiltGmsCoreVic_DynamiteModulesC',
        'PrebuiltGmsCoreVic_GoogleCertificates',
        'PrebuiltGmsCoreVic_MapsDynamite',
        'PrebuiltGmsCoreVic_MeasurementDynamite',
        'SettingsIntelligenceGooglePrebuilt',
        'TfliteDynamitePrebuilt',
        'VisionBarcodePrebuilt'
    ]

    conditional_exclude = ['GoogleCamera', 'NexusLauncherRelease', 'HealthIntelligencePrebuilt']
    base_pkg = [p for p in pkg_lines if p not in extras_to_remove and p not in conditional_exclude]

    def format_list(prefix, lines):
        if not lines:
            return ''
        s = f'{prefix} += \\\n'
        for i, item in enumerate(lines):
            indented = f'    {item}'
            if i == len(lines) - 1:
                s += f'{indented}\n'
            else:
                s += f'{indented} \\\n'
        s += '\n'
        return s

    gms_str = '# Automatically generated file. DO NOT MODIFY\n#\n'
    gms_str += '# This file is generated by vendor/gms/setup-makefiles.py\n\n'
    gms_str += 'PRODUCT_SOONG_NAMESPACES += \\\n'
    gms_str += '    vendor/gms/common\n\n'
    gms_str += 'TARGET_CORE_GMS ?= false\n'
    gms_str += 'ifeq ($(strip $(TARGET_CORE_GMS)),true)\n'
    gms_str += format_list('PRODUCT_COPY_FILES', core_copy_list)
    gms_str += format_list('PRODUCT_PACKAGES', core_pkg_list)
    gms_str += '    ifeq ($(strip $(TARGET_CORE_GMS_EXTRAS)),true)\n'
    gms_str += '    PRODUCT_PACKAGES += \\\n'
    gms_str += '        Velvet \\\n'
    gms_str += '        Photos\n'
    gms_str += '    endif\n'
    gms_str += 'else\n'
    gms_str += format_list('PRODUCT_COPY_FILES', copy_lines)
    gms_str += format_list('PRODUCT_PACKAGES', base_pkg)
    gms_str += 'TARGET_PREBUILT_GOOGLE_CAMERA ?= false\n'
    gms_str += 'ifeq ($(strip $(TARGET_PREBUILT_GOOGLE_CAMERA)),true)\n'
    gms_str += 'PRODUCT_PACKAGES += \\\n'
    gms_str += '    GoogleCamera\n'
    gms_str += 'endif\n\n'
    gms_str += 'TARGET_DEFAULT_PIXEL_LAUNCHER ?= false\n'
    gms_str += 'ifeq ($(strip $(TARGET_DEFAULT_PIXEL_LAUNCHER)),true)\n'
    gms_str += 'PRODUCT_PACKAGES += \\\n'
    gms_str += '    NexusLauncherRelease\n'
    gms_str += 'endif\n\n'
    gms_str += 'CURRENT_DEVICE := $(shell echo "$(TARGET_PRODUCT)" | cut -d\'_\' -f 2,3)\n'
    gms_str += 'ifneq ($(filter $(CURRENT_DEVICE), husky shiba akita caiman komodo tangorpro tokay),)\n'
    gms_str += 'PRODUCT_PACKAGES += \\\n'
    gms_str += '    HealthIntelligencePrebuilt\n'
    gms_str += 'endif\n\n'
    gms_str += 'TARGET_GMS_EXTRAS ?= false\n'
    gms_str += 'ifeq ($(strip $(TARGET_GMS_EXTRAS)),true)\n'
    gms_str += 'PRODUCT_PACKAGES += \\\n'
    gms_str += '    AdaptiveVPNPrebuilt-10435 \\\n'
    gms_str += '    WallpaperAIPrebuilt_10000372 \\\n'
    gms_str += '    AvatarPickerGoogle \\\n'
    gms_str += '    Chrome-Stub \\\n'
    gms_str += '    CreativeAssistant \\\n'
    gms_str += '    DreamlinerDreamsPrebuilt_100894 \\\n'
    gms_str += '    DreamlinerPrebuilt_22000020 \\\n'
    gms_str += '    DreamlinerUpdater \\\n'
    gms_str += '    Drive \\\n'
    gms_str += '    Maps \\\n'
    gms_str += '    MeetPrebuilt_20250518 \\\n'
    gms_str += '    Photos \\\n'
    gms_str += '    PixelAIPrebuilt \\\n'
    gms_str += '    PixelSupportPrebuilt \\\n'
    gms_str += '    PixelWallpapers2024 \\\n'
    gms_str += '    PrebuiltGmail \\\n'
    gms_str += '    RecorderPrebuilt_725581069 \\\n'
    gms_str += '    SatelliteClient \\\n'
    gms_str += '    PixelSatelliteGatewayPrebuilt \\\n'
    gms_str += '    TipsPrebuilt_v6.0.0.734377952 \\\n'
    gms_str += '    TrichromeLibrary-Stub \\\n'
    gms_str += '    VendorSatelliteService \\\n'
    gms_str += '    WebViewGoogle-Stub \\\n'
    gms_str += '    YouTube\n'
    gms_str += 'endif\n'
    gms_str += 'TARGET_GMS_EXTRAS_MINIMAL ?= false\n'
    gms_str += 'ifeq ($(strip $(TARGET_GMS_EXTRAS_MINIMAL)),true)\n'
    gms_str += 'PRODUCT_PACKAGES += \\\n'
    gms_str += '    WallpaperAIPrebuilt_10000372 \\\n'
    gms_str += '    AvatarPickerGoogle \\\n'
    gms_str += '    CreativeAssistant \\\n'
    gms_str += '    PixelAIPrebuilt \\\n'
    gms_str += '    PixelSupportPrebuilt \\\n'
    gms_str += '    SatelliteClient \\\n'
    gms_str += '    PixelSatelliteGatewayPrebuilt \\\n'
    gms_str += '    VendorSatelliteService\n'
    gms_str += 'endif\n'
    gms_str += 'endif\n'

    with open(COMMON_VENDOR_MK, 'w') as f:
        f.write(gms_str)

    if ANDROIDBP.exists():
        with open(ANDROIDBP, 'r') as f:
            content = f.read()
        content = re.sub(
            r'(name: "MeetPrebuilt_20250518"[\s\S]*?product_specific: true,)([\s\S]*?\n})',
            r'\1\n    skip_preprocessed_apk_checks: true,\2',
            content
        )
        with open(ANDROIDBP, 'w') as f:
            f.write(content)

    print("Custom makefile generations complete.")


if __name__ == '__main__':
    import sys
    from pathlib import Path

    regenerate_only = '--regenerate_makefiles' in sys.argv

    if regenerate_only:
        MY_DIR = Path(__file__).parent
        DEVICE_DIR = MY_DIR / 'common'
        for file in ['Android.mk', 'Android.bp', 'common-vendor.mk', 'BoardConfig.mk']:
            (DEVICE_DIR / file).unlink(missing_ok=True)

    utils = ExtractUtils.device(module)
    utils.run()
    post_regenerate_customizations()
