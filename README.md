# vendor_gms

## Basic usage

- If you just wanna use this repository, then you just need to include `products/gms.mk`
- This is as simple as: `$(call inherit-product-if-exists, vendor/gms/products/gms.mk)`

## Advanced usage

### Initial setup
- Install `xmlstarlet`
  - `sudo apt install xmlstarlet`, `sudo pacman -S xmlstarlet`, etc. depending on your distribution.
- Install `apktool`, make sure its available in PATH
  - https://ibotpeaches.github.io/Apktool/install/
  - Run `apktool if framework-res.apk` to install framework for apktool this is necessary for proper extracting
    (generally found in /system/framework/)

### Extracting / updating extracted overlays

Basically the same as regular extract-files

Ensure you are in the vendor/gms directory

```sh
./extract-files.py /path/to/a/dump
```

If you need to also extract updated overlays

```sh
cd ./overlays
```

```sh
./extract-files.py /path/to/a/dump
```

We also have a simplified script to assist with updating the existing blobs names in the script and prop list with newer names example : arcore-1.42.apk to arcore-1.48.apk

From gms directory

```sh
./update-list.py /path/to/a/dump
```

### Removing certain overlays

- If certain overlays are not required, you can simply add them to `exclude-tag.txt`, those will be removed from the extracted overlays.

### Miscellaneous information

- The main changes here are the addition of `apktool` and `xmlstarlet`, to allow us to extract the necessary overlays from some RROs.
- Since the process does take a while, to speed it up, all extraction is done in the background. This might not be suitable for weaker systems if there is a very high number of overlays to be extracted.
