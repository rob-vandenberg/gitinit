"""
gitinit.py (C projects) -- One-time setup of a new C project: git, GitHub repository and release tooling.

Copy this file and release.py into the project folder and run:  python gitinit.py
It creates the missing folders and files (existing files are NEVER overwritten), including
release.bat, release.sh and release.ini, backs up the source, creates the GitHub
repository if needed and pushes the initial commit and tag.
Requires: Python 3, git, the GitHub CLI (gh) logged in (gh auth login), and release.py in the folder.
"""

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

# --- Version ------------------------------------------------------------
__version__ = 'gitinit-c 0.0.4'

def version():
    return __version__

# --- Version history ----------------------------------------------------
# v0.0.4: release.ini gets an empty [publish] section (files for the GitHub source archives), with examples.
# v0.0.3: release.py is no longer written by gitinit. It is its own file: put it in the project folder
#         next to gitinit.py before running. gitinit still writes release.bat, release.sh and release.ini.
# v0.0.2: No license text in this file any more: a missing LICENSE is fetched from GitHub (LICENSE_KEY).
#         If that fails, gitinit warns and adds a manual step. Script is ~650 lines smaller.
# v0.0.1: Initial C-project version, derived from the Home Assistant gitinit.py 0.0.2. Runs when .git
#         exists only after typing "yes"; never overwrites; skips git/GitHub steps that would.
#         Writes release.py/.bat/.sh and release.ini. No publish workflow: release.py creates a
#         draft release, publishing is done by hand on GitHub.

# --- Settings -----------------------------------------------------------
GITHUB_USER = "rob-vandenberg"
AUTHOR = "Rob Vandenberg"
LICENSE_KEY = "agpl-3.0"          # GitHub license key; the text is fetched from GitHub when LICENSE is missing
BASE_TOPICS = ["c"]
INITIAL_VERSION = "0.0.0"
INITIAL_MESSAGE = "Initial scaffold"
FOLDERS = ["backup", "dist", "art"]

# --- Templates ----------------------------------------------------------
# Written exactly as they are here. Tokens @@...@@ are replaced per project.

GITIGNORE = r'''# Folders
__pycache__/
.*/
!.github/
*.bak/
docs/
logs/
backup/
artwork/
screenshot/
release/
github/

# Files
*.bak
*.ai
*.psd
*.bat
*.zip
*.jfif
gitinit*.py
release.py
release.ini
release.sh

# OS generated files
.DS_Store
Thumbs.db

# Build output
*.o
*.obj
*.a
*.so
*.so.*
*.dll
*.exe
*.pdb

# IDE
.vscode/
.idea/
'''

GITATTRIBUTES = r'''* text=auto
*.md text eol=lf
*.c text eol=lf
*.h text eol=lf
*.py text eol=lf
*.sh text eol=lf
Makefile text eol=lf
*.bat text eol=crlf
'''

README_MD = r'''<div align="center">

  [![](https://img.shields.io/badge/License-AGPL_3.0-blue.svg?style=for-the-badge)](https://www.gnu.org/licenses/agpl-3.0)
  [![](https://img.shields.io/github/v/release/rob-vandenberg/@@ID@@?style=for-the-badge&color=brightgreen&label=Version)](https://github.com/rob-vandenberg/@@ID@@/releases)

  <p align="center">
    <strong>@@DESCRIPTION@@</strong>
  </p>

</div>

---

# @@NAME@@

TODO: Write the introduction.

## Requirements

TODO

## Installation

TODO

## Usage

TODO

## License

AGPL-3.0-or-later. See [LICENSE](LICENSE).

## Support

TODO
'''

MAIN_C = r'''/*
 * @@ID@@ - @@DESCRIPTION_C@@
 *
 * Copyright (C) @@YEAR@@ @@AUTHOR@@
 * License: AGPL-3.0-or-later (see LICENSE)
 */

/* Release version (x.y.z). release.py reads this line to create the Git tag. */
#define @@VERSION_ID@@ "@@VERSION@@"

/* --- Version history ---
 * v@@VERSION@@: Initial scaffold.
 */

#include <stdio.h>

int main(void)
{
    printf("@@ID@@ %s\n", @@VERSION_ID@@);
    return 0;
}
'''

MAKEFILE = r'''CC      ?= gcc
CFLAGS  ?= -O2 -g
CFLAGS  += -Wall -Wextra

@@ID@@: @@MAIN@@
@@TAB@@$(CC) $(CFLAGS) -o $@ $<

clean:
@@TAB@@rm -f @@ID@@

.PHONY: clean
'''

RELEASE_INI = r'''# release.ini -- settings for release.py. This file is NOT pushed to GitHub (see .gitignore).
# Paths may be written with / or \. Wildcards (* ? **) are allowed.
# In [backup], [include] and [assets] every line is one path, without a value.
# Comments must be on a line of their own.

[project]
name = @@ID@@
type = c
branch = @@BRANCH@@

# The file that holds the release version, and the name in front of the version in that file
# (the first quoted text after the name is the version).
[version]
file = @@MAIN@@
identifier = @@VERSION_ID@@

# The true source files. One entry without wildcard = that file is copied to backup\.
# Anything else = one zip, named <project>_<version>.zip.
[backup]
@@BACKUP_ENTRIES@@

# New files matching these lines are added to git without asking (a folder includes everything in it).
# Any other new file or folder is asked about first.
[include]

# Files uploaded to the DRAFT release on GitHub (kept out of git). A wildcard that matches
# nothing is fine; a file named in full must exist.
[assets]
dist/*

# Files in the GitHub "Source code" zip and tar.gz of each release. Empty = everything in the repository
# (GitHub's default). Otherwise ONLY the files listed here, and LICENSE*, go into them: release.py keeps a
# block in .gitattributes up to date for this. Examples:
#   released as source:              list the source files and the Makefile
#   released as a binary ([assets]): list the files needed to build it
#   single-file repository:          list that one file
[publish]

# Optional command that builds the project on this machine. Leave empty when nothing is built here.
[build]
command =
'''

RELEASE_BAT = r'''@echo off
setlocal
:: release.bat -- starts release.py. Nothing in this file is project-specific.
:: Usage: release.bat "Your commit message"
cd /d "%~dp0"
where py >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    py -3 release.py %*
) else (
    python release.py %*
)
set "RC=%ERRORLEVEL%"
pause
exit /b %RC%
'''

RELEASE_SH = r'''#!/bin/sh
# release.sh -- starts release.py. Nothing in this file is project-specific.
# Usage: ./release.sh "Your commit message"
cd "$(dirname "$0")" || exit 1
if command -v python3 >/dev/null 2>&1; then PY=python3; else PY=python; fi
"$PY" release.py "$@"
'''


# --- Helpers ------------------------------------------------------------

class InitError(Exception):
    pass


def info(text=""):
    print(text)


def step(number, total, text):
    print(f"\n[{number}/{total}] {text}")


def fail(text):
    raise InitError(text)


def run(args, capture=False, check=True):
    """Runs a command (first element resolved on PATH)."""
    exe = shutil.which(args[0])
    if not exe:
        fail(f"'{args[0]}' was not found on PATH.")
    result = subprocess.run([exe, *args[1:]], text=True, encoding="utf-8", capture_output=capture)
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip() if capture else ""
        fail(f"Command failed: {' '.join(args)}" + (f"\n{detail}" if detail else ""))
    return result


def write_text(path, content, newline="\n"):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline=newline) as f:
        f.write(content)


def ask(prompt, default=None):
    suffix = f" ({default})" if default else ""
    value = input(f"{prompt}{suffix}: ").strip()
    return value or (default or "")


def default_name(identifier):
    return " ".join(w[:1].upper() + w[1:] for w in re.split(r"[-_]", identifier) if w)


def topic_of(identifier):
    return re.sub(r"[^a-z0-9-]+", "-", identifier.lower()).strip("-")


def fill(template, values):
    for key, value in values.items():
        template = template.replace(f"@@{key}@@", value)
    return template


def fetch_license():
    """Asks GitHub for the license text (LICENSE_KEY). Returns the text, or None when that fails."""
    result = run(["gh", "api", f"licenses/{LICENSE_KEY}", "--jq", ".body"], capture=True, check=False)
    text = (result.stdout or "").strip("\r\n")
    if result.returncode != 0 or len(text) < 200:
        return None
    return text + "\n"


def detect_version(main_file):
    """Finds '#define SOMETHING_VERSION "1.2.3"' in an existing main file -> (identifier, version) or None."""
    if not main_file.is_file():
        return None
    text = main_file.read_text(encoding="utf-8", errors="replace")
    m = re.search(r"#\s*define\s+(\w*VERSION\w*)\s+\"(\d+\.\d+\.\d+(?:\.\d+)?)\"", text)
    return (m.group(1), m.group(2)) if m else None


def load_release_module(root):
    spec = importlib.util.spec_from_file_location("release_local", root / "release.py")
    module = importlib.util.module_from_spec(spec)
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True          # do not leave a __pycache__ folder in the project
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    return module


def remove_unused_git(root):
    """Removes the .git folder that THIS run created, but only while it still has no commit."""
    if (root / ".git").exists() and subprocess.run(["git", "rev-parse", "--verify", "-q", "HEAD"], cwd=root,
                                                   capture_output=True).returncode != 0:
        def make_writable(func, path, _):
            os.chmod(path, 0o700)
            func(path)
        shutil.rmtree(root / ".git", onerror=make_writable)
        return True
    return False


def via_release(module, func, *args):
    """Calls a function of release.py and turns its errors into InitError."""
    try:
        return getattr(module, func)(*args)
    except module.ReleaseError as err:
        fail(str(err))


# --- Main ---------------------------------------------------------------

def main():
    root = Path.cwd()
    total = 7
    info(f"{__version__} -- new C project in: {root}")

    # --- Requirements ---------------------------------------------------
    step(1, total, "Checking requirements...")
    for tool in ("git", "gh"):
        if not shutil.which(tool):
            fail(f"'{tool}' was not found on PATH. Install it first.")
    if run(["gh", "auth", "status"], capture=True, check=False).returncode != 0:
        fail("The GitHub CLI is not logged in. Run: gh auth login")
    if not (root / "release.py").is_file():
        fail("release.py was not found in this folder. Copy release.py next to gitinit.py first: gitinit uses it.")
    git_exists = (root / ".git").exists()
    if git_exists:
        info("\n !! WARNING: this folder already contains a git repository (.git).")
        info("    All git commands are skipped. Only missing files and folders are created;")
        info("    existing files are never overwritten.")
        if ask("Type yes to continue").lower() != "yes":
            info("Aborted. Nothing was changed.")
            return 1

    # --- Project details ------------------------------------------------
    step(2, total, "Project details")
    identifier = ask("Project identifier", root.name).lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]*", identifier):
        fail("The identifier may only contain lowercase letters, digits, '.', '_' and '-'.")
    name = ask("Project name", default_name(identifier))
    description = ""
    while not description:
        description = ask("Description")
    main_name = ask("Main source file (holds the version)", identifier.replace("-", "_").replace(".", "_") + ".c")
    main_name = re.sub(r"^(\./)+", "", main_name.replace("\\", "/"))
    if not main_name or ".." in main_name.split("/") or re.match(r"^[A-Za-z]:", main_name):
        fail("The main source file must be a relative path inside the project folder.")
    main_file = root / main_name

    found = detect_version(main_file)
    default_version_id = found[0] if found else re.sub(r"\W", "_", Path(main_name).stem).upper() + "_VERSION"
    version_id = ask("Name of the version macro in that file", default_version_id)
    version = found[1] if found and found[0] == version_id else INITIAL_VERSION
    if main_file.is_file() and not (found and found[0] == version_id):
        info(f"  WARNING: {main_name} exists but has no '#define {version_id} \"x.y.z\"' line.")
        info("           Add it before the first release, or release.py will refuse to run.")

    repo = f"{GITHUB_USER}/{identifier}"
    remote_url = f"https://github.com/{repo}.git"
    topics = BASE_TOPICS + ([topic_of(identifier)] if topic_of(identifier) not in BASE_TOPICS else [])

    # --- GitHub repository state ----------------------------------------
    view = run(["gh", "repo", "view", repo, "--json", "isEmpty,defaultBranchRef"], capture=True, check=False)
    repo_exists = view.returncode == 0
    repo_empty, default_branch = True, "main"
    if repo_exists:
        data = json.loads(view.stdout)
        repo_empty = bool(data.get("isEmpty", False))
        default_branch = ((data.get("defaultBranchRef") or {}).get("name")) or "main"
    branch = "main" if repo_empty else default_branch

    backup_entries = "\n".join([main_name, "Makefile"])
    values = {
        "ID": identifier, "NAME": name, "DESCRIPTION": description,
        "DESCRIPTION_C": description.replace("*/", "* /"), "YEAR": str(date.today().year),
        "AUTHOR": AUTHOR, "VERSION_ID": version_id, "VERSION": version, "MAIN": main_name,
        "BRANCH": branch, "BACKUP_ENTRIES": backup_entries, "TAB": "\t",
    }
    generated = {
        root / ".gitignore": (GITIGNORE, "\n"),
        root / ".gitattributes": (GITATTRIBUTES, "\n"),
        root / "README.md": (fill(README_MD, values), "\n"),
        main_file: (fill(MAIN_C, values), "\n"),
        root / "Makefile": (fill(MAKEFILE, values), "\n"),
        root / "release.ini": (fill(RELEASE_INI, values), "\n"),
        root / "release.bat": (RELEASE_BAT, "\r\n"),
        root / "release.sh": (RELEASE_SH, "\n"),
    }

    if git_exists:
        git_plan = "skipped (.git exists)"
    elif repo_exists and not repo_empty:
        git_plan = f"link to the existing remote history (init, fetch, mixed reset to origin/{default_branch}); no commit, no push"
    else:
        git_plan = f"init, commit, tag {version} and push"
    repo_plan = ("will be created, public" if not repo_exists
                 else "exists, empty: description and topics will be set" if repo_empty
                 else "exists with commits: left untouched")

    # --- Confirmation ---------------------------------------------------
    info("\n=====================================================================")
    info(f" Identifier:   {identifier}")
    info(f" Name:         {name}")
    info(f" Description:  {description}")
    info(f" Main file:    {main_name}   (version macro {version_id}, version {version})")
    info(f" Repository:   {repo} ({repo_plan})")
    info(f" Topics:       {', '.join(topics)}")
    info(f" Git:          {git_plan}")
    license_path = root / "LICENSE"
    info(f" LICENSE:      " + ("already present, will be skipped" if license_path.exists()
                               else f"will be fetched from GitHub ({LICENSE_KEY})"))
    existing = [str(p.relative_to(root)) for p in generated if p.exists()]
    if existing:
        info(" Already present, will be skipped: " + ", ".join(existing))
    info("=====================================================================")
    if ask("Continue? (Y/N)").upper() != "Y":
        info("Aborted. Nothing was changed.")
        return 1

    # --- Folders and files ----------------------------------------------
    step(3, total, "Creating folders and files...")
    for folder in FOLDERS:
        path = root / folder
        if path.exists():
            info(f"  skipped folder  {folder}")
        else:
            path.mkdir()
            info(f"  created folder  {folder}")
    for path, (content, newline) in generated.items():
        rel = path.relative_to(root)
        if path.exists():
            info(f"  skipped file    {rel}")
            continue
        write_text(path, content, newline)
        if path.name == "release.sh" and os.name != "nt":
            os.chmod(path, 0o755)
        info(f"  created file    {rel}")

    license_missing = False
    if license_path.exists():
        info("  skipped file    LICENSE")
    else:
        text = fetch_license()
        if text is None:
            license_missing = True
            info(f"  !! could not fetch the {LICENSE_KEY} license from GitHub: LICENSE not created")
        else:
            write_text(license_path, text)
            info(f"  created file    LICENSE (fetched from GitHub: {LICENSE_KEY})")

    # --- Backup ---------------------------------------------------------
    step(4, total, "Creating backup...")
    release = load_release_module(root)
    cfg = via_release(release, "load_config", root)
    backup = via_release(release, "make_backup", cfg, version)
    info(f"  {backup.relative_to(root).as_posix()} (read-only)")

    # --- GitHub repository ----------------------------------------------
    step(5, total, "Setting up the GitHub repository...")
    if not repo_exists:
        run(["gh", "repo", "create", repo, "--public", "--description", description])
        run(["gh", "repo", "edit", repo, "--add-topic", ",".join(topics)])
        info(f"  created {repo}, topics: {', '.join(topics)}")
    elif repo_empty:
        run(["gh", "repo", "edit", repo, "--description", description])
        run(["gh", "repo", "edit", repo, "--add-topic", ",".join(topics)])
        info(f"  using existing empty repository {repo}, topics: {', '.join(topics)}")
    else:
        info(f"  repository {repo} exists with commits: creation, description and topics skipped")

    # --- Git ------------------------------------------------------------
    step(6, total, "Git...")
    adopted = False
    if git_exists:
        info("  skipped: .git exists")
    elif repo_exists and not repo_empty:
        try:
            run(["git", "init", "-b", default_branch])
            run(["git", "remote", "add", "origin", remote_url])
            run(["git", "fetch", "origin", "--tags"])
            run(["git", "reset", "-q", f"origin/{default_branch}"])
            run(["git", "branch", "--set-upstream-to", f"origin/{default_branch}"])
        except InitError as err:
            if remove_unused_git(root):
                fail(f"{err}\n(The empty .git created by this run was removed, so gitinit can be run again.)")
            raise
        adopted = True
        info(f"  linked to origin/{default_branch}; your files were not touched")
    else:
        try:
            run(["git", "init", "-b", "main"])
            run(["git", "remote", "add", "origin", remote_url])
            info("  New files are checked first (nothing is added without your answer):")
            via_release(release, "review_new_files", cfg)
            run(["git", "add", "-A"])
            run(["git", "commit", "-m", INITIAL_MESSAGE])
        except InitError as err:
            if remove_unused_git(root):
                fail(f"{err}\n(The empty .git created by this run was removed, so gitinit can be run again.)")
            raise
        run(["git", "tag", "-a", version, "-m", INITIAL_MESSAGE])
        run(["git", "push", "-u", "origin", "main"])
        run(["git", "push", "origin", version])
        info(f"  committed, tagged {version} and pushed")

    # --- Done -----------------------------------------------------------
    step(7, total, "Done.")
    info("\n=====================================================================")
    info(f" SUCCESS! {identifier} is set up.")
    info(f"   https://github.com/{repo}")
    info("=====================================================================")
    todo = []
    if license_missing:
        todo.append("Add a LICENSE file to the project folder (GitHub needs one): it could not be fetched.")
    todo.append("Check release.ini: [backup] lists the true source files, [assets] the files for the release.")
    todo.append("Finish README.md (and put any images it uses in the art folder).")
    if adopted:
        todo.append("Run release.bat (Windows) or ./release.sh (Linux): it shows how your files differ from GitHub.")
    else:
        todo.append('To release: raise the version in the main file, then run release.bat "message" (or ./release.sh).')
    todo.append("release.py only creates a DRAFT release. Publish it yourself on GitHub.")
    info("\n Still to do by hand:")
    for number, text in enumerate(todo, 1):
        info(f"   {number}. {text}")
    info("\n Do not run gitinit.py again for this project.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except InitError as err:
        print(f"\n!! ERROR: {err}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nAborted.")
        sys.exit(1)
