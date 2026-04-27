#
# Automatically generated file. DO NOT MODIFY
#

PRODUCT_SOONG_NAMESPACES += \
    vendor/gms/overlays/common

TARGET_GAPPS_VARIANT ?= gms
ifeq ($(strip $(TARGET_CORE_GMS)),true)
TARGET_GAPPS_VARIANT := core
endif

ifeq ($(strip $(TARGET_GAPPS_VARIANT)),gms)
PRODUCT_PACKAGES += GoogleConfigOverlay
endif

PRODUCT_PACKAGES += PearlOverlay2024

PRODUCT_PACKAGES += PixelBatteryHealthOverlay

PRODUCT_PACKAGES += PixelConfigOverlay2018

PRODUCT_PACKAGES += PixelConfigOverlay2019

PRODUCT_PACKAGES += PixelConfigOverlay2019Midyear

PRODUCT_PACKAGES += PixelConfigOverlay2021

PRODUCT_PACKAGES += PixelContactsProviderOverlay

PRODUCT_PACKAGES += PixelFrameworkOverlay

PRODUCT_PACKAGES += PixelSettingsProviderOverlay

PRODUCT_PACKAGES += PixelSetupWizardOverlay2024

PRODUCT_PACKAGES += PixelStorageManagerGoogleOverlay

PRODUCT_PACKAGES += SystemUIGXOverlay
