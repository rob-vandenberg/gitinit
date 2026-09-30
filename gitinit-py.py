"""
gitinit-py.py (Python projects and Home Assistant integrations) -- One-time setup of a new project:
git, GitHub repository and release tooling.

Copy this file into the project folder and run:  python gitinit-py.py
It creates the missing folders and files (existing files are NEVER overwritten), including
release.bat, release.sh and release.ini, backs up the source, creates the GitHub
repository if needed and pushes the initial commit and tag.
Requires: Python 3, git and the GitHub CLI (gh) logged in (gh auth login). release.py is downloaded from
the latest release of rob-vandenberg/gitinit when the folder does not have it yet (an existing copy is never replaced).
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
__version__ = 'gitinit-py 0.0.5'

def version():
    return __version__

# --- Version history ----------------------------------------------------
# v0.0.5: The initial tag is no longer pushed: it stays local, and GitHub creates the tag when the release is published.
# v0.0.4: The new-file check no longer asks about the files this run just created (they are approved).
# v0.0.3: A missing release.py is downloaded from the latest release of rob-vandenberg/gitinit (never overwritten);
#         an existing one must be at least release 0.0.6.
# v0.0.2: release.ini gets an empty [publish] section (files for the GitHub source archives), with examples.
# v0.0.1: Initial Python version, derived from gitinit-c 0.0.3. Two kinds of project: a normal Python
#         project (<identifier>.py) and a Home Assistant integration (custom_components/<domain>/ with
#         manifest.json, hacs.json, brand folder and the hassfest + HACS workflow). release.py reads the
#         version from __version__ (normal) or from the 'version' key of manifest.json (integration, tag 'v').

# --- Settings -----------------------------------------------------------
GITHUB_USER = "rob-vandenberg"
AUTHOR = "Rob Vandenberg"
LICENSE_KEY = "agpl-3.0"          # GitHub license key; the text is fetched from GitHub when LICENSE is missing
INITIAL_VERSION = "0.0.0"
RELEASE_REPO = "rob-vandenberg/gitinit"     # its releases carry release.py
MIN_RELEASE = "0.0.6"                       # oldest release.py this gitinit works with
INITIAL_MESSAGE = "Initial scaffold"
FOLDERS = ["backup", "dist", "art"]
HA_PREFIX = "\U0001F535 HOME ASSISTANT - "       # in front of the GitHub repository description only
HA_TAG_PREFIX = "v"
HA_IOT_CLASS = "local_push"                      # placeholder: check it (see the manual steps)
KIND_TOPICS = {"py": ["python"], "ha": ["python", "home-assistant", "integration"]}

# --- Templates ----------------------------------------------------------
# Written exactly as they are here. Tokens @@...@@ are replaced per project.

GITIGNORE = r'''# Folders
__pycache__/
.*/
!.github/
*.egg-info/
venv/
*.bak/
docs/
logs/
backup/
artwork/
screenshot/
release/
github/

# Files
*.pyc
*.pyo
*.pyd
*.bak
*.ai
*.psd
*.bat
*.zip
*.log
*.jfif
gitinit*.py
release.py
release.ini
release.sh

# OS generated files
.DS_Store
Thumbs.db

# IDE
.vscode/
.idea/
'''

GITATTRIBUTES = r'''# Auto-detect text files and normalize line endings
* text=auto

# Python and shell files - LF
*.py text eol=lf
*.sh text eol=lf

# JSON and YAML - LF
*.json text eol=lf
*.yaml text eol=lf
*.yml text eol=lf

# Markdown - LF
*.md text eol=lf

# Windows batch files - CRLF
*.bat text eol=crlf

# Binary files
*.png binary
*.jpg binary
*.jpeg binary
*.gif binary
*.svg binary
*.zip binary
'''

README_PY = r'''<div align="center">

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

Python 3.

## Installation

TODO

## Usage

TODO

## License

AGPL-3.0-or-later. See [LICENSE](LICENSE).

## Support

TODO
'''

README_HA = r'''<div align="center">

  [![](https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge)](https://github.com/hacs/integration)
  [![](https://img.shields.io/badge/License-AGPL_3.0-blue.svg?style=for-the-badge)](https://www.gnu.org/licenses/agpl-3.0)
  [![](https://img.shields.io/github/v/release/rob-vandenberg/@@ID@@?style=for-the-badge&color=brightgreen&label=Version)](https://github.com/rob-vandenberg/@@ID@@/releases)

  <img src="art/header.svg" width="800" alt="@@NAME@@ Banner">

  <img src="art/banner.png" width="800" alt="@@NAME@@ Banner">

  @@DESCRIPTION@@

</div>

---

## Installation

### HACS (recommended)

Add this repository as a custom repository in HACS, then install **@@NAME@@** from the integrations section.

### Manual

Copy `custom_components/@@DOMAIN@@/` into your Home Assistant `config/custom_components/` folder and restart Home Assistant.

---

## Configuration

After installation, go to **Settings → Devices & Services → Add Integration** and search for **@@NAME@@**.

---

## License

AGPL-3.0-or-later. See [LICENSE](LICENSE).
'''

# A normal Python project: the main file.
MAIN_PY = r'''import os
import sys

# Release version (x.y.z). release.py reads this line to create the Git tag.
__version__ = '@@VERSION_NAME@@ @@VERSION@@'

def version():
    return __version__

# --- Version history ----------------------------------------------------
# v@@VERSION@@: @@MESSAGE@@


def main():
    sys.exit(0)


if __name__ == '__main__':
    main()
'''

# A Home Assistant integration: custom_components/<domain>/__init__.py (no main(): Home Assistant imports it).
INIT_PY = r'''import os

# Release version of this file. The release version of the integration is in manifest.json.
__version__ = '@@VERSION_NAME@@ @@VERSION@@'

def version():
    return __version__

# --- Version history ----------------------------------------------------
# v@@VERSION@@: @@MESSAGE@@

DOMAIN = "@@DOMAIN@@"
'''

MANIFEST_JSON = r'''{
  "domain": "@@DOMAIN@@",
  "name": "@@NAME_JSON@@",
  "codeowners": ["@@@GITHUB_USER@@"],
  "documentation": "https://github.com/@@GITHUB_USER@@/@@ID@@",
  "iot_class": "@@IOT_CLASS@@",
  "issue_tracker": "https://github.com/@@GITHUB_USER@@/@@ID@@/issues",
  "requirements": [],
  "version": "@@VERSION@@"
}
'''

HACS_JSON = r'''{
  "name": "@@NAME_JSON@@",
  "render_readme": true
}
'''

WORKFLOW_YML = r'''name: "Validate: hassfest + HACS"

on:
  push:
    branches:
      - main
    paths:
      - 'custom_components/**'
      - 'hacs.json'
  workflow_dispatch:
  schedule:
    - cron: "0 0 * * *"

jobs:
  validate:
    runs-on: "ubuntu-latest"
    steps:
      - uses: actions/checkout@v6

      - name: Validate with hassfest
        uses: home-assistant/actions/hassfest@master

      - name: HACS Action
        uses: "hacs/action@main"
        with:
          category: "integration"
'''

RELEASE_INI = r'''# release.ini -- settings for release.py. This file is NOT pushed to GitHub (see .gitignore).
# Paths may be written with / or \. Wildcards (* ? **) are allowed.
# In [backup], [include] and [assets] every line is one path, without a value.
# Comments must be on a line of their own.

[project]
name = @@RELEASE_NAME@@
type = @@TYPE@@
branch = @@BRANCH@@
@@TAG_PREFIX_LINE@@
# The file that holds the release version. A text file: 'identifier' is the name in front of the version
# (the last word of the first quoted text after the name is the version). A .json file: 'key' is the
# top-level key that holds the version.
[version]
file = @@VERSION_FILE@@
@@VERSION_LINE@@

# The true source files. One entry without wildcard = that file is copied to backup\.
# Anything else (also a single folder) = one zip, named <project>_<version>.zip.
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


VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(\.\d+)?$")


def detect_py_version(main_file):
    """Finds __version__ = 'name 1.2.3' in an existing Python file -> version or None."""
    if not main_file.is_file():
        return None
    text = main_file.read_text(encoding="utf-8-sig", errors="replace")
    m = re.search(r"^__version__\s*=\s*(['\"])(.*?)\1", text, re.MULTILINE)
    words = m.group(2).split() if m else []
    return words[-1] if words and VERSION_RE.match(words[-1]) else None


def detect_manifest_version(manifest):
    """Reads the 'version' key of an existing manifest.json -> version or None."""
    if not manifest.is_file():
        return None
    try:
        data = json.loads(manifest.read_text(encoding="utf-8-sig"))
    except ValueError:
        return None
    value = data.get("version") if isinstance(data, dict) else None
    return value if isinstance(value, str) and VERSION_RE.match(value) else None


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


def ensure_release_py(root):
    """Downloads release.py from the latest release of RELEASE_REPO when the folder has none."""
    if (root / "release.py").is_file():
        return
    info(f"  release.py not found here: downloading it from the latest release of {RELEASE_REPO} ...")
    result = run(["gh", "release", "download", "--repo", RELEASE_REPO, "--pattern", "release.py",
                  "--dir", str(root)], capture=True, check=False)
    if result.returncode != 0 or not (root / "release.py").is_file():
        detail = (result.stderr or result.stdout or "").strip()
        fail("release.py was not found in this folder and could not be downloaded.\n"
             + (detail + "\n" if detail else "")
             + f"Download it yourself: gh release download --repo {RELEASE_REPO} --pattern release.py")


def check_release_version(module):
    """Stops when release.py is older than MIN_RELEASE (copies older than 0.0.5 have no version())."""
    func = getattr(module, "version", None)
    found = func().split()[-1] if callable(func) else "0.0.0"
    if tuple(int(x) for x in found.split(".")) < tuple(int(x) for x in MIN_RELEASE.split(".")):
        fail(f"release.py {found} in this folder is older than {MIN_RELEASE}, which this gitinit needs.\n"
             f"Replace it: gh release download --repo {RELEASE_REPO} --pattern release.py --clobber")


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
    info(f"{__version__} -- new Python project in: {root}")

    # --- Requirements ---------------------------------------------------
    step(1, total, "Checking requirements...")
    for tool in ("git", "gh"):
        if not shutil.which(tool):
            fail(f"'{tool}' was not found on PATH. Install it first.")
    if run(["gh", "auth", "status"], capture=True, check=False).returncode != 0:
        fail("The GitHub CLI is not logged in. Run: gh auth login")
    ensure_release_py(root)
    release = load_release_module(root)
    check_release_version(release)
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
    kind = ""
    while kind not in ("1", "2"):
        kind = ask("Project kind: 1 = Python project, 2 = Home Assistant integration", "1")
    kind = "py" if kind == "1" else "ha"
    identifier = ask("Project identifier", root.name).lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]*", identifier):
        fail("The identifier may only contain lowercase letters, digits, '.', '_' and '-'.")
    name = ask("Project name", default_name(identifier))
    description = ""
    while not description:
        description = ask("Description")

    domain = re.sub(r"[-.]", "_", identifier)
    if kind == "ha":
        if not re.fullmatch(r"[a-z][a-z0-9_]*", domain):
            fail("The integration domain (the identifier with '-' and '.' replaced by '_') must start with a letter.")
        component = f"custom_components/{domain}"
        main_name = f"{component}/__init__.py"
        version_file = f"{component}/manifest.json"
        found = detect_manifest_version(root / version_file)
        version_name = "__init__.py"
        version_line = "key = version"
        release_name = domain
        tag_prefix = HA_TAG_PREFIX
        backup_entries = "custom_components"
        project_type = "ha-integration"
    else:
        main_name = ask("Main source file (holds the version)", identifier + ".py")
        main_name = re.sub(r"^(\./)+", "", main_name.replace("\\", "/"))
        if not main_name or ".." in main_name.split("/") or re.match(r"^[A-Za-z]:", main_name):
            fail("The main source file must be a relative path inside the project folder.")
        version_file = main_name
        found = detect_py_version(root / main_name)
        version_name = identifier
        version_line = "identifier = __version__"
        release_name = identifier
        tag_prefix = ""
        backup_entries = main_name
        project_type = "python"
    main_file = root / main_name
    version = found or INITIAL_VERSION
    if (root / version_file).is_file() and not found:
        info(f"  WARNING: {version_file} exists but holds no version like 1.2.3 in "
             + ("the 'version' key." if kind == "ha" else "a '__version__ = ...' line."))
        info("           Fix it before the first release, or release.py will refuse to run.")
    tag = tag_prefix + version

    repo = f"{GITHUB_USER}/{identifier}"
    remote_url = f"https://github.com/{repo}.git"
    topics = list(KIND_TOPICS[kind])
    if topic_of(identifier) not in topics:
        topics.append(topic_of(identifier))
    repo_description = (HA_PREFIX if kind == "ha" else "") + description

    # --- GitHub repository state ----------------------------------------
    view = run(["gh", "repo", "view", repo, "--json", "isEmpty,defaultBranchRef"], capture=True, check=False)
    repo_exists = view.returncode == 0
    repo_empty, default_branch = True, "main"
    if repo_exists:
        data = json.loads(view.stdout)
        repo_empty = bool(data.get("isEmpty", False))
        default_branch = ((data.get("defaultBranchRef") or {}).get("name")) or "main"
    branch = "main" if repo_empty else default_branch

    values = {
        "ID": identifier, "NAME": name, "NAME_JSON": json.dumps(name)[1:-1], "DESCRIPTION": description,
        "DOMAIN": domain, "GITHUB_USER": GITHUB_USER, "IOT_CLASS": HA_IOT_CLASS, "MESSAGE": INITIAL_MESSAGE,
        "VERSION_NAME": version_name, "VERSION": version, "TYPE": project_type, "BRANCH": branch,
        "RELEASE_NAME": release_name, "VERSION_FILE": version_file, "VERSION_LINE": version_line,
        "BACKUP_ENTRIES": backup_entries,
        "TAG_PREFIX_LINE": f"tag_prefix = {tag_prefix}\n" if tag_prefix else "",
    }
    folders = list(FOLDERS)
    generated = {
        root / ".gitignore": (GITIGNORE, "\n"),
        root / ".gitattributes": (GITATTRIBUTES, "\n"),
    }
    if kind == "ha":
        folders.append(f"{component}/brand")
        generated[root / "README.md"] = (fill(README_HA, values), "\n")
        generated[main_file] = (fill(INIT_PY, values), "\n")
        generated[root / version_file] = (fill(MANIFEST_JSON, values), "\n")
        generated[root / "hacs.json"] = (fill(HACS_JSON, values), "\n")
        generated[root / ".github/workflows/validate_hassfest_hacs.yml"] = (WORKFLOW_YML, "\n")
    else:
        generated[root / "README.md"] = (fill(README_PY, values), "\n")
        generated[main_file] = (fill(MAIN_PY, values), "\n")
    generated[root / "release.ini"] = (fill(RELEASE_INI, values), "\n")
    generated[root / "release.bat"] = (RELEASE_BAT, "\r\n")
    generated[root / "release.sh"] = (RELEASE_SH, "\n")

    if git_exists:
        git_plan = "skipped (.git exists)"
    elif repo_exists and not repo_empty:
        git_plan = f"link to the existing remote history (init, fetch, mixed reset to origin/{default_branch}); no commit, no push"
    else:
        git_plan = f"init, commit, push, and tag {tag} locally (not pushed)"
    repo_plan = ("will be created, public" if not repo_exists
                 else "exists, empty: description and topics will be set" if repo_empty
                 else "exists with commits: left untouched")

    # --- Confirmation ---------------------------------------------------
    info("\n=====================================================================")
    info(f" Kind:         " + ("Home Assistant integration" if kind == "ha" else "Python project"))
    info(f" Identifier:   {identifier}")
    info(f" Name:         {name}")
    info(f" Description:  {repo_description}")
    if kind == "ha":
        info(f" Domain:       {domain}   (folder {component})")
        info(f" Version:      {version} in {version_file}   (tag {tag})")
    else:
        info(f" Main file:    {main_name}   (__version__, version {version}, tag {tag})")
    info(f" Repository:   {repo} ({repo_plan})")
    info(f" Topics:       {', '.join(topics)}")
    info(f" Git:          {git_plan}")
    license_path = root / "LICENSE"
    info(f" LICENSE:      " + ("already present, will be skipped" if license_path.exists()
                               else f"will be fetched from GitHub ({LICENSE_KEY})"))
    existing = [str(p.relative_to(root).as_posix()) for p in generated if p.exists()]
    if existing:
        info(" Already present, will be skipped: " + ", ".join(existing))
    info("=====================================================================")
    if ask("Continue? (Y/N)").upper() != "Y":
        info("Aborted. Nothing was changed.")
        return 1

    # --- Folders and files ----------------------------------------------
    step(3, total, "Creating folders and files...")
    before = {p.name for p in root.iterdir()}      # what was in the folder before this run
    for folder in folders:
        path = root / folder
        if path.exists():
            info(f"  skipped folder  {folder}")
        else:
            path.mkdir(parents=True)
            info(f"  created folder  {folder}")
    created = []          # files written by this run: the new-file check does not ask about them
    for path, (content, newline) in generated.items():
        rel = path.relative_to(root).as_posix()
        if path.exists():
            info(f"  skipped file    {rel}")
            continue
        write_text(path, content, newline)
        if path.name == "release.sh" and os.name != "nt":
            os.chmod(path, 0o755)
        top = rel.split("/")[0]
        created.append(rel if top in before else top)    # a folder made by this run is approved as a whole
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
            created.append("LICENSE")
            info(f"  created file    LICENSE (fetched from GitHub: {LICENSE_KEY})")

    # --- Backup ---------------------------------------------------------
    step(4, total, "Creating backup...")
    cfg = via_release(release, "load_config", root)
    backup = via_release(release, "make_backup", cfg, version)
    info(f"  {backup.relative_to(root).as_posix()} (read-only)")

    # --- GitHub repository ----------------------------------------------
    step(5, total, "Setting up the GitHub repository...")
    if not repo_exists:
        run(["gh", "repo", "create", repo, "--public", "--description", repo_description])
        run(["gh", "repo", "edit", repo, "--add-topic", ",".join(topics)])
        info(f"  created {repo}, topics: {', '.join(topics)}")
    elif repo_empty:
        run(["gh", "repo", "edit", repo, "--description", repo_description])
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
            cfg.include = list(cfg.include) + created      # what gitinit just wrote is approved
            via_release(release, "review_new_files", cfg)
            run(["git", "add", "-A"])
            run(["git", "commit", "-m", INITIAL_MESSAGE])
        except InitError as err:
            if remove_unused_git(root):
                fail(f"{err}\n(The empty .git created by this run was removed, so gitinit can be run again.)")
            raise
        run(["git", "tag", "-a", tag, "-m", INITIAL_MESSAGE])
        run(["git", "push", "-u", "origin", "main"])
        info(f"  committed and pushed; tagged {tag} locally only (GitHub creates the tag when you publish the release)")

    # --- Done -----------------------------------------------------------
    step(7, total, "Done.")
    info("\n=====================================================================")
    info(f" SUCCESS! {identifier} is set up.")
    info(f"   https://github.com/{repo}")
    info("=====================================================================")
    todo = []
    if license_missing:
        todo.append("Add a LICENSE file to the project folder (GitHub needs one): it could not be fetched.")
    if kind == "ha":
        todo.append(f"Check iot_class in {version_file}: it is a placeholder ({HA_IOT_CLASS}). Valid values: "
                    "assumed_state, calculated, cloud_polling, cloud_push, local_polling, local_push. "
                    "Add config_flow and requirements there when the integration needs them.")
        todo.append(f"Put icon.png and logo.png in {component}/brand, and header.svg and banner.png in art "
                    "(the README uses them).")
    todo.append("Check release.ini: [backup] lists the true source files, [assets] the files for the release.")
    todo.append("Finish README.md (and put any images it uses in the art folder).")
    if adopted:
        todo.append("Run release.bat (Windows) or ./release.sh (Linux): it shows how your files differ from GitHub.")
    elif kind == "ha":
        todo.append('To release: raise "version" in manifest.json, then run release.bat "message" (or ./release.sh).')
    else:
        todo.append('To release: raise the version in the main file, then run release.bat "message" (or ./release.sh).')
    todo.append("release.py only creates a DRAFT release. Publish it yourself on GitHub.")
    info("\n Still to do by hand:")
    for number, text in enumerate(todo, 1):
        info(f"   {number}. {text}")
    info("\n Do not run gitinit-py.py again for this project.")
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
