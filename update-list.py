#!/usr/bin/env python3
#
# SPDX-FileCopyrightText: 2025 AxionAOSP
# SPDX-License-Identifier: Apache-2.0
#

import os
import re
import sys
from pathlib import Path

def extract_base_and_version(app_dir_name):
    match = re.match(r'^([A-Za-z]+)([_-][\dv\w\.-].*)$', app_dir_name)
    if match:
        return match.group(1), match.group(2)
    return app_dir_name, ''

def main():
    if len(sys.argv) != 2:
        print("Usage: ./update-list.py <path-to-extracted-img-folder>")
        sys.exit(1)

    source_dump = Path(sys.argv[1]).resolve()
    if not source_dump.is_dir():
        print(f"Error: {source_dump} is not a valid directory")
        sys.exit(1)

    prop_file = Path("proprietary-files.txt")
    extract_file = Path("extract-files.py")

    if not prop_file.exists():
        print(f"Error: {prop_file} not found")
        sys.exit(1)
    if not extract_file.exists():
        print(f"Error: {extract_file} not found")
        sys.exit(1)

    with open(prop_file, 'r') as f:
        prop_lines = f.readlines()

    new_prop_lines = []
    prop_updated = False

    print("Phase 1: Scanning dump for updated app versions...\n")

    for line in prop_lines:
        stripped = line.strip()
        if not stripped or stripped.startswith('#'):
            new_prop_lines.append(line)
            continue

        parts = stripped.split(';')
        path_part = parts[0]
        options = ';'.join(parts[1:]) if len(parts) > 1 else ''

        has_negate = path_part.startswith('-')
        path_no_neg = path_part[1:] if has_negate else path_part

        source_path = path_no_neg.split(':')[0] if ':' in path_no_neg else path_no_neg

        full_source = source_dump / source_path
        if full_source.exists() or not source_path.endswith('.apk'):
            new_prop_lines.append(line)
            continue

        path_parts = source_path.split('/')
        if len(path_parts) != 4 or path_parts[1] not in ('app', 'priv-app') or path_parts[3] != f"{path_parts[2]}.apk":
            new_prop_lines.append(line)
            continue

        partition, category, old_app_dir = path_parts[0], path_parts[1], path_parts[2]
        base_name, _ = extract_base_and_version(old_app_dir)

        search_dir = source_dump / partition / category
        if not search_dir.is_dir():
            new_prop_lines.append(line)
            continue

        candidates = []
        for dir_name in os.listdir(search_dir):
            dir_path = search_dir / dir_name
            if dir_path.is_dir() and extract_base_and_version(dir_name)[0] == base_name:
                apk_path = dir_path / f"{dir_name}.apk"
                if apk_path.exists():
                    candidates.append(dir_name)

        if len(candidates) == 1:
            new_app_dir = candidates[0]
            new_source = f"{partition}/{category}/{new_app_dir}/{new_app_dir}.apk"
            if has_negate:
                new_source = '-' + new_source
            new_path_part = f"{new_source}:{path_no_neg.split(':')[1]}" if ':' in path_no_neg else new_source

            if options:
                new_opts = []
                for opt in options.split(';'):
                    if opt.startswith("OVERRIDES=") and old_app_dir in opt:
                        new_opts.append(f"OVERRIDES={new_app_dir}")
                    else:
                        new_opts.append(opt)
                options = ';'.join(new_opts)

            new_line = new_path_part + (';' + options if options else '') + '\n'
            new_prop_lines.append(new_line)
            print(f"Updated proprietary-files.txt: {old_app_dir} → {new_app_dir}")
            prop_updated = True
        else:
            if len(candidates) > 1:
                print(f"Warning: Multiple candidates for {old_app_dir}: {candidates}")
            new_prop_lines.append(line)

    if prop_updated:
        with open(prop_file, 'w') as f:
            f.writelines(new_prop_lines)
        print("\nproprietary-files.txt has been updated.\n")
    else:
        print("\nNo updates needed in proprietary-files.txt.\n")

    print("Phase 2: Syncing outdated versioned app names in extract-files.py...\n")

    current_full_names = set()
    for line in new_prop_lines:
        stripped = line.strip()
        if not stripped or stripped.startswith('#'):
            continue
        path_part = stripped.split(';')[0].lstrip('-')
        source_path = path_part.split(':')[0] if ':' in path_part else path_part
        if source_path.endswith('.apk'):
            app_dir = source_path.split('/')[-2]
            if re.search(r'[_-][\dv\w\.-]', app_dir):
                current_full_names.add(app_dir)

    if not current_full_names:
        print("No versioned prebuilt apps found.")
        return

    with open(extract_file, 'r') as f:
        content = f.read()
    lines = content.splitlines()
    new_lines = lines[:]
    updated = False

    potential_pattern = re.compile(r'\b([A-Za-z]+[_-][\dv\w\.-]+)\b')
    all_mentions_in_extract = set()
    for line in lines:
        all_mentions_in_extract.update(potential_pattern.findall(line))

    for old_full in all_mentions_in_extract:
        if old_full in current_full_names:
            continue

        base, _ = extract_base_and_version(old_full)
        new_full = None
        for curr in current_full_names:
            if extract_base_and_version(curr)[0] == base:
                new_full = curr
                break

        if new_full and new_full != old_full:
            print(f"Updating extract-files.py: {old_full} → {new_full}")
            for i in range(len(new_lines)):
                new_lines[i] = re.sub(rf'\b{re.escape(old_full)}\b', new_full, new_lines[i])
            updated = True

    if updated:
        with open(extract_file, 'w') as f:
            f.write('\n'.join(new_lines) + '\n')
        print("\nextract-files.py has been successfully updated.")
    else:
        print("\nextract-files.py is already in sync — no changes needed.")

if __name__ == '__main__':
    main()
