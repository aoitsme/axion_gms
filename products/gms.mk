#
# Copyright (C) 2020 The LineageOS Project
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

ifeq ($(strip $(WITH_GMS)),true)
PRODUCT_ARTIFACT_PATH_REQUIREMENT_ALLOWED_LIST += \
    system/apex/com.google.android.extservices.apex \
    system/apex/com.google.android.media.swcodec.apex \
    system/apex/com.google.mainline.primary.libs.apex \
    system/apex/com.google.android.resolv.apex \
    system/apex/com.google.android.mediaprovider.apex \
    system/apex/com.google.android.neuralnetworks.apex \
    system/apex/com.google.android.tzdata5.apex \
    system/lib/libRSSupport.so \
    system/lib/libblasV8.so \
    system/lib/librsjni.so \
    system/lib64/libRSSupport.so \
    system/lib64/libblasV8.so \
    system/lib64/librsjni.so

PRODUCT_ARTIFACT_PATH_REQUIREMENT_ALLOWED_LIST += \
    system/framework/arm/%.art \
    system/framework/arm/%.oat \
    system/framework/arm/%.vdex \
    system/framework/arm64/%.art \
    system/framework/arm64/%.oat \
    system/framework/arm64/%.vdex \

PRODUCT_ARTIFACT_PATH_REQUIREMENT_ALLOWED_LIST += \
    system/framework/oat/arm/%.odex \
    system/framework/oat/arm/%.vdex \
    system/framework/oat/arm64/%.odex \
    system/framework/oat/arm64/%.vdex \

# Artifact path requirement allowlist
PRODUCT_ARTIFACT_PATH_REQUIREMENT_ALLOWED_LIST += \
    system/app/GoogleExtShared/GoogleExtShared.apk \
    system/app/GooglePrintRecommendationService/GooglePrintRecommendationService.apk \
    system/etc/permissions/privapp-permissions-google.xml \
    system/priv-app/DocumentsUIGoogle/DocumentsUIGoogle.apk \
    system/priv-app/GooglePackageInstaller/GooglePackageInstaller.apk \
    system/priv-app/TagGoogle/TagGoogle.apk

# SetupWizard Props
PRODUCT_PRODUCT_PROPERTIES += \
    ro.setupwizard.enterprise_mode=1 \
    ro.setupwizard.esim_cid_ignore=00000001 \
    ro.setupwizard.rotation_locked=true \
    setupwizard.feature.baseline_setupwizard_enabled=true \
    setupwizard.feature.day_night_mode_enabled=true \
    setupwizard.feature.default_locale_enhancement_enabled=true \
    setupwizard.feature.portal_notification=true \
    setupwizard.feature.provisioning_profile_mode=true \
    setupwizard.feature.enable_parental_notice_activity=true \
    setupwizard.feature.enable_parental_setup=true \
    setupwizard.feature.enable_quick_start_flow=true \
    setupwizard.feature.enable_restore_anytime=true \
    setupwizard.feature.enable_wifi_tracker=true \
    setupwizard.feature.enhanced_setup_design_metrics=true \
    setupwizard.feature.lifecycle_refactoring=true \
    setupwizard.feature.locale_agnostic_enabled=true \
    setupwizard.feature.notification_refactoring=true \
    setupwizard.personal_safety_suw_enabled=true \
    setupwizard.feature.show_pai_screen_in_main_flow.carrier1839=false \
    setupwizard.feature.show_pixel_tos=true \
    setupwizard.feature.show_support_link_in_deferred_setup=false \
    setupwizard.feature.skip_button_use_mobile_data.carrier1839=true \
    ro.atrace.core.services=com.google.android.gms,com.google.android.gms.ui,com.google.android.gms.persistent \
    ro.com.google.ime.system_lm_dir=/product/usr/share/ime/google/d3_lms \
    ro.com.google.ime.theme_id=5 \
    ro.error.receiver.system.apps=com.google.android.gms \
    ro.opa.eligible_device=true \
    pixel_legal_joint_permission=true \
    pixel_legal_joint_permission_v2=true

$(call inherit-product, vendor/gms/common/common-vendor.mk)
$(call inherit-product, vendor/gms/overlays/common/common-vendor.mk)
endif
