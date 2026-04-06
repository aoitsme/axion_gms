#
# Automatically generated file. DO NOT MODIFY
#

TARGET_CORE_GMS ?= false

PRODUCT_SOONG_NAMESPACES += \
    vendor/gms/overlays/common

PRODUCT_PACKAGES += \
 AccessibilityMenuCaiman \
 AvatarPickerPixelOverlay \
 GlanceableHubConfigOverlay \
 GlanceableHubSettingsConfigOverlay \
 GlanceableHubSysuiConfigOverlay \
 GoogleWebViewOverlay \
 ManagedProvisioningPixelOverlay \
 PearlOverlay2024 \
 PixelBatteryHealthOverlay \
 PixelConfigOverlay2018 \
 PixelConfigOverlay2019 \
 PixelConfigOverlay2019Midyear \
 PixelConfigOverlay2021 \
 PixelConfigOverlayCommon \
 PixelContactsProviderOverlay \
 PixelFrameworkOverlay \
 PixelPrintServiceOverlay \
 PixelSettingsGoogleOverlay \
 PixelSettingsProviderOverlay \
 PixelSetupWizardOverlay2024 \
 PixelStorageManagerGoogleOverlay \
 PixelSystemUIGoogleOverlay \
 SystemUIGXOverlay \
 WildlifeSettingsVpnOverlay2022 \
 WildlifeSysuiVpnOverlay2022

ifneq ($(strip $(TARGET_CORE_GMS)),true)
PRODUCT_PACKAGES += \
 GoogleConfigOverlay
endif
