#!/usr/bin/env python3
"""
release.py -- release script for C projects (written by gitinit.py, do not edit per project).

Usage:  python release.py "Commit message"
        python release.py --update            install the latest release.py
        python release.py --update=0.0.6      install that release.py version (an older one too)
        python release.py --update=list       show the versions that can be installed

  A new version (the version in the source file has no git tag yet) needs a message.
  If the tag already exists, the last commit is amended and the tag is moved (UPDATE mode);
  no message is needed then.

All project-specific settings live in release.ini, next to this file.
Requires: Python 3, git and the GitHub CLI (gh) logged in (gh auth login).
"""

import configparser
import fnmatch
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from types import SimpleNamespace

# --- Version ------------------------------------------------------------
__version__ = 'release 0.0.7'

def version():
    return __version__

# --- Version history ----------------------------------------------------
# v0.0.7: release.py --update installs the latest release.py from the releases of the gitinit repository;
#         --update=<version> installs that exact release.py version (also older ones), --update=list shows
#         the available versions. The current copy is saved in backup\ first. Every normal run prints a
#         notice when a newer release.py exists (silent when offline; never blocks a release).
# v0.0.6: New [publish] section: the files that go into the GitHub 'Source code' zip/tar.gz of a release
#         (LICENSE* always). release.py keeps a marked block in .gitattributes (export-ignore) up to date.
#         Empty section = GitHub default (everything); the block is removed again.
# v0.0.5: Added version(), which returns __version__ (as in the other Python projects).
# v0.0.4: The git tag is no longer pushed for a new version. The DRAFT release points at the pushed commit,
#         and GitHub creates the tag only when the draft is published, so nobody sees a tag before the
#         release. RELEASE mode refuses a version that already has a remote tag or a published release.
#         UPDATE mode is unchanged; it pushes the (moved) tag only when that tag is already public.
#         The draft is found by its title and handled with the GitHub REST API (list, create, update).
# v0.0.3: [version] can name a 'key' to read from a .json file (manifest.json); [project] tag_prefix
#         (e.g. 'v') is put in front of the version for the git tag and the GitHub release.
# v0.0.2: The version text may contain the project name in front of the number ('project-name 1.2.3').
# v0.0.1: Initial version, replacing release.bat logic. Reads release.ini; backup of one file or a
#         zip; asks about new files before git add; commit/tag/push; creates a DRAFT GitHub release
#         with the files from [assets]. Publishing is always done by hand on GitHub.

# --- Settings -----------------------------------------------------------
ROOT = Path(__file__).resolve().parent
INI_NAME = "release.ini"
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(\.\d+)?$")
GLOB_CHARS = "*?["
SKIP_TOP = (".git", "backup")      # never picked up by wildcard expansion

# --- Output -------------------------------------------------------------
if os.name == "nt":
    os.system("")                  # enables ANSI colors in the Windows console
RESET, WHITE, BLUE, GREEN, RED, YELLOW = "\033[0m", "\033[97m", "\033[94m", "\033[92m", "\033[91m", "\033[93m"


class ReleaseError(Exception):
    pass


def fail(text):
    raise ReleaseError(text)


def step(number, total, text):
    print(f"\n{BLUE}[STEP {number}/{total}]{WHITE} {text}{RESET}")


def ok(text):
    print(f"{GREEN}{text}{RESET}")


def warn(text):
    print(f"{YELLOW}{text}{RESET}")


# --- Paths --------------------------------------------------------------

def norm(path):
    """Accepts / or \\ in ini values; always returns forward slashes."""
    p = path.strip().replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    return p


def has_glob(path):
    return any(c in path for c in GLOB_CHARS)


def _check_relative(pattern):
    p = norm(pattern)
    if p.startswith("/") or re.match(r"^[A-Za-z]:", p) or ".." in p.split("/"):
        fail(f"Paths in {INI_NAME} must be relative to the project folder and stay inside it: {pattern}")
    return p


def _walk(folder):
    for f in sorted(folder.rglob("*")):
        if f.is_file():
            yield f


def expand(patterns, root=ROOT):
    """Resolves literal paths, folders and wildcards to a list of files (posix paths relative to root).
    Returns (files, missing) where 'missing' holds literal (non-wildcard) paths that do not exist.
    A wildcard that matches nothing is not an error."""
    files, missing, seen = [], [], set()

    def add(f):
        rel = f.relative_to(root).as_posix()
        if rel.split("/")[0] in SKIP_TOP or rel in seen:
            return
        seen.add(rel)
        files.append(rel)

    for pattern in patterns:
        p = _check_relative(pattern)
        if has_glob(p):
            for m in sorted(root.glob(p)):
                if m.is_file():
                    add(m)
                elif m.is_dir():
                    for f in _walk(m):
                        add(f)
        else:
            target = root / p
            if target.is_file():
                add(target)
            elif target.is_dir():
                for f in _walk(target):
                    add(f)
            else:
                missing.append(p)
    return files, missing


# --- Config -------------------------------------------------------------

def load_config(root=ROOT):
    ini = root / INI_NAME
    if not ini.is_file():
        fail(f"{INI_NAME} not found in {root}. It is created by gitinit.py.")
    cp = configparser.ConfigParser(allow_no_value=True, delimiters=("=",), comment_prefixes=("#", ";"),
                                   inline_comment_prefixes=None, interpolation=None, strict=True)
    cp.optionxform = str           # keep the case of file names
    try:
        cp.read(ini, encoding="utf-8")
    except configparser.Error as err:
        fail(f"Cannot read {INI_NAME}: {err}")

    def value(section, key):
        if not cp.has_section(section) or not cp.has_option(section, key):
            fail(f"{INI_NAME}: missing '{key}' in section [{section}].")
        v = (cp.get(section, key) or "").strip()
        if not v:
            fail(f"{INI_NAME}: '{key}' in section [{section}] is empty.")
        return v

    def optional(section, key):
        if not cp.has_section(section) or not cp.has_option(section, key):
            return ""
        return (cp.get(section, key) or "").strip()

    def entries(section):
        return [norm(k) for k in cp[section]] if cp.has_section(section) else []

    cfg = SimpleNamespace(
        root=root,
        name=value("project", "name"),
        branch=value("project", "branch"),
        version_file=norm(value("version", "file")),
        version_identifier=optional("version", "identifier"),   # text files: the name in front of the version
        version_key=optional("version", "key"),                 # .json files: the key that holds the version
        tag_prefix=optional("project", "tag_prefix"),           # e.g. 'v' gives tag v1.2.3 (default: none)
        backup=entries("backup"),
        include=entries("include"),
        assets=entries("assets"),
        publish=entries("publish"),
        build=((cp.get("build", "command", fallback="") or "").strip() if cp.has_section("build") else ""),
    )
    return cfg


def read_version(cfg):
    path = cfg.root / _check_relative(cfg.version_file)
    if not path.is_file():
        fail(f"Version file not found: {cfg.version_file}")
    if path.suffix.lower() == ".json":
        if not cfg.version_key:
            fail(f"{INI_NAME}: [version] needs a 'key' for the .json file {cfg.version_file}.")
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except ValueError as err:
            fail(f"Cannot read {cfg.version_file}: {err}")
        value = data.get(cfg.version_key) if isinstance(data, dict) else None
        words = value.split() if isinstance(value, str) else []
        if words and VERSION_RE.match(words[-1]):
            return words[-1]
        fail(f"No version like 1.2.3 found in key '{cfg.version_key}' of {cfg.version_file}.")
    if not cfg.version_identifier:
        fail(f"{INI_NAME}: [version] needs an 'identifier' for the file {cfg.version_file}.")
    text = path.read_text(encoding="utf-8", errors="replace")
    pattern = r"\b" + re.escape(cfg.version_identifier) + r"\b[^\r\n\"']*[\"']([^\"'\r\n]*)[\"']"
    for m in re.finditer(pattern, text):
        words = m.group(1).split()                  # '1.2.3' or 'project-name 1.2.3': the version is the last word
        if words and VERSION_RE.match(words[-1]):
            return words[-1]
    fail(f"No version like 1.2.3 found after '{cfg.version_identifier}' in {cfg.version_file}.")


# --- Commands -----------------------------------------------------------

def _exe(name):
    exe = shutil.which(name)
    if not exe:
        fail(f"'{name}' was not found on PATH.")
    return exe


def git(*args, check=True):
    r = subprocess.run([_exe("git"), *args], cwd=ROOT, text=True, encoding="utf-8", capture_output=True)
    if check and r.returncode != 0:
        fail(f"git {' '.join(args)} failed:\n{(r.stderr or r.stdout).strip()}")
    return r


def git_visible(*args):
    """Runs git with its output shown (used for add, commit and push)."""
    r = subprocess.run([_exe("git"), *args], cwd=ROOT)
    if r.returncode != 0:
        fail(f"git {' '.join(args)} failed.")


def gh(*args, check=True, timeout=None):
    try:
        r = subprocess.run([_exe("gh"), *args], cwd=ROOT, text=True, encoding="utf-8", capture_output=True,
                           timeout=timeout)
    except subprocess.TimeoutExpired:
        r = subprocess.CompletedProcess(args, 1, "", "timed out")
    if check and r.returncode != 0:
        fail(f"gh {' '.join(args)} failed:\n{(r.stderr or r.stdout).strip()}")
    return r


# --- Backup -------------------------------------------------------------

def _remove(path):
    if path.exists():
        os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
        path.unlink()


def make_backup(cfg, version):
    """One entry without wildcard -> that file is copied as <file>_<version>.<ext>.
    Anything else -> zip named <project>_<version>.zip. Result is read-only. Returns the backup path."""
    if not cfg.backup:
        fail(f"{INI_NAME}: the [backup] section is empty. A backup is mandatory.")
    folder = cfg.root / "backup"
    folder.mkdir(exist_ok=True)

    single = len(cfg.backup) == 1 and not has_glob(cfg.backup[0])
    if single and (cfg.root / _check_relative(cfg.backup[0])).is_dir():
        single = False                 # a single folder is zipped, not copied
    if single:
        src = cfg.root / _check_relative(cfg.backup[0])
        if not src.is_file():
            fail(f"Backup file not found: {cfg.backup[0]}")
        dest = folder / f"{src.stem}_{version}{src.suffix}"
        _remove(dest)
        shutil.copyfile(src, dest)
    else:
        files, missing = expand(cfg.backup, cfg.root)
        if missing:
            fail("Backup entries not found: " + ", ".join(missing))
        if not files:
            fail("The [backup] entries match no files.")
        dest = folder / f"{cfg.name}_{version}.zip"
        _remove(dest)
        with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
            for rel in files:
                z.write(cfg.root / rel, arcname=rel)
    os.chmod(dest, stat.S_IREAD)
    return dest


# --- New file review ----------------------------------------------------

def is_included(path, include):
    """True if 'path' (a file or folder, posix, no trailing slash) matches an [include] pattern,
    or lies inside a folder that does."""
    parts = path.split("/")
    ancestors = ["/".join(parts[:i]) for i in range(1, len(parts) + 1)]
    for pat in include:
        p = pat.rstrip("/")
        if any(fnmatch.fnmatchcase(a, p) for a in ancestors):
            return True
        if fnmatch.fnmatchcase(path + "/x", p):      # folder as a whole matches e.g. 'art/*'
            return True
    return False


def list_untracked(*paths, collapse=True):
    args = ["ls-files", "--others", "--exclude-standard", "-z"]
    if collapse:
        args += ["--directory", "--no-empty-directory"]
    if paths:
        args += ["--", *paths]
    return [e for e in git(*args).stdout.split("\0") if e]


def _ignore_escape(path):
    out = path.replace("\\", "\\\\")
    for ch in "*?[":
        out = out.replace(ch, "\\" + ch)
    if out[:1] in ("#", "!"):
        out = "\\" + out
    if out.endswith(" "):
        out = out[:-1] + "\\ "
    return out


def append_ignore(lines, root=ROOT):
    """Appends lines to .gitignore (keeps its line endings, skips lines that are already there)."""
    path = root / ".gitignore"
    data = path.read_bytes() if path.exists() else b""
    eol = b"\r\n" if b"\r\n" in data else b"\n"
    existing = set(data.decode("utf-8", errors="replace").splitlines())
    new = [l for l in lines if l not in existing]
    if not new:
        return
    if data and not data.endswith(b"\n"):
        data += eol
    data += b"".join(l.encode("utf-8") + eol for l in new)
    path.write_bytes(data)


def ask_choice(question, options):
    while True:
        try:
            answer = input(f"{question} [{'/'.join(options)}]: ").strip().lower()[:1]
        except EOFError:
            fail("This step needs an interactive terminal (a new file or folder needs an answer).")
        if answer in options:
            return answer
        print(f"  Please answer with one of: {', '.join(options)}")


def review_new_files(cfg):
    """Every untracked, not-ignored file or folder is either approved by [include], or asked about.
    'n' writes it to .gitignore. Afterwards 'git add -A' can only add what was approved."""
    entries = list_untracked()
    if not entries:
        print(" No new files.")
        return
    to_ignore = []

    def handle_file(path):
        if is_included(path, cfg.include):
            print(f" + {path}   (approved by [include])")
            return
        if ask_choice(f" New file: {path}  -- add to git?", ("y", "n")) == "n":
            to_ignore.append("/" + _ignore_escape(path))

    for entry in entries:
        path = entry.rstrip("/")
        if not entry.endswith("/"):
            handle_file(path)
            continue
        if is_included(path, cfg.include):
            print(f" + {path}/   (approved by [include])")
            continue
        answer = ask_choice(f" New folder: {path}/  -- (y)es add all, (n)o ignore it, (a)sk per file?", ("y", "n", "a"))
        if answer == "n":
            to_ignore.append("/" + _ignore_escape(path) + "/")
        elif answer == "a":
            for f in list_untracked(path, collapse=False):
                handle_file(f)
    if to_ignore:
        append_ignore(to_ignore, cfg.root)
        for line in to_ignore:
            print(f" .gitignore += {line}")


# --- Files in the GitHub source archives --------------------------------

GA_BEGIN = "# BEGIN release.py [publish]"
GA_END = "# END release.py [publish]"


def publish_block(entries, root):
    """The lines of the managed .gitattributes block: everything is export-ignore (left out of the GitHub
    source archives) except LICENSE* and the [publish] entries."""
    lines = [GA_BEGIN,
             "# Generated by release.py from the [publish] section of release.ini.",
             "# Do not make edits below this line: everything down to the END line is overwritten.",
             "* export-ignore",
             "/LICENSE* -export-ignore"]
    for entry in entries:
        p = _check_relative(entry).rstrip("/")
        lines.append(f"/{p} -export-ignore")
        if has_glob(p) or (root / p).is_dir():
            lines.append(f"/{p}/** -export-ignore")       # the contents of a folder
    lines.append(GA_END)
    return lines


def update_gitattributes(cfg):
    """Makes the marked block in .gitattributes match [publish]. Lines outside the block are never touched."""
    path = cfg.root / ".gitattributes"
    data = path.read_bytes() if path.exists() else b""
    eol = "\r\n" if b"\r\n" in data else "\n"
    old_text = data.decode("utf-8", errors="replace")
    kept, skipping = [], False
    for line in old_text.splitlines():
        if line.strip() == GA_BEGIN:
            skipping = True
        elif skipping:
            skipping = line.strip() != GA_END
        else:
            kept.append(line)
    if skipping:
        fail(f".gitattributes has the line '{GA_BEGIN}' but no '{GA_END}' line. Fix or remove that block.")
    while kept and not kept[-1].strip():
        kept.pop()
    if cfg.publish:
        if kept:
            kept.append("")
        kept += publish_block(cfg.publish, cfg.root)
    new_text = "".join(line + eol for line in kept)
    if new_text == old_text or (not path.exists() and not new_text):
        print(" .gitattributes: [publish] block already up to date." if cfg.publish
              else " [publish] is empty: GitHub source archives contain everything.")
        return
    path.write_bytes(new_text.encode("utf-8"))
    print(" .gitattributes: [publish] block " + ("updated." if cfg.publish else "removed."))


# --- GitHub draft release -----------------------------------------------

def find_releases(tag):
    """Returns (draft, published) for this tag: dicts with 'id', or None. A draft without a git tag is
    found by its title (the tag name), because GitHub shows its tag as 'untagged-...'."""
    r = gh("api", "repos/{owner}/{repo}/releases", "--paginate", "--jq",
           ".[] | [.id, .draft, .name, .tag_name] | @json")
    draft = published = None
    for line in (r.stdout or "").splitlines():
        line = line.strip()
        if not line:
            continue
        rid, is_draft, name, tag_name = json.loads(line)
        if name != tag and tag_name != tag:
            continue
        if is_draft:
            draft = draft or {"id": rid}
        else:
            published = published or {"id": rid}
    return draft, published


def remote_tag_exists(tag):
    r = git("ls-remote", "--tags", "origin", f"refs/tags/{tag}", check=False)
    return r.returncode == 0 and bool((r.stdout or "").strip())


def draft_release(cfg, tag, notes, assets, sha):
    """Creates (or updates) a DRAFT release that points at commit 'sha'. Never publishes.
    For a tag that is not on GitHub yet, GitHub creates it when the draft is published."""
    draft, published = find_releases(tag)
    if published is not None:
        warn(f"[DRAFT] Release {tag} is already PUBLISHED and was left untouched.")
        return ""

    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8", newline="\n") as f:
        f.write(notes)
        notes_file = f.name
    fields = ["-f", f"tag_name={tag}", "-f", f"target_commitish={sha}", "-f", f"name={tag}",
              "-F", f"body=@{notes_file}"]
    try:
        if draft is None:
            r = gh("api", "-X", "POST", "repos/{owner}/{repo}/releases", *fields, "-F", "draft=true",
                   "--jq", ".html_url")
            url = (r.stdout.strip().splitlines() or [""])[-1]
            if assets:
                gh("release", "upload", tag, *assets, "--clobber")
            ok(f"[DRAFT] Created draft release {tag} with {len(assets)} asset file(s).")
        else:
            gh("api", "-X", "PATCH", f"repos/{{owner}}/{{repo}}/releases/{draft['id']}", *fields,
               "-F", "draft=true")
            if assets:
                gh("release", "upload", tag, *assets, "--clobber")
            url = ""
            ok(f"[DRAFT] Updated draft release {tag} ({len(assets)} asset file(s) replaced).")
    finally:
        os.unlink(notes_file)
    return url


# --- Updating release.py itself -----------------------------------------

UPDATE_REPO = "rob-vandenberg/gitinit"     # the repository whose releases carry release.py
UPDATE_ASSET = "release.py"
SELF = Path(__file__).resolve()


def version_of(source):
    """'release 0.0.6' in the __version__ line of a release.py source text -> '0.0.6', or None."""
    m = re.search(r"^__version__\s*=\s*(['\"])(.*?)\1", source, re.MULTILINE)
    words = m.group(2).split() if m else []
    return words[-1] if words and VERSION_RE.match(words[-1]) else None


def version_key(version):
    return tuple(int(x) for x in version.split("."))


def fetch_copy(tag, folder, timeout=None):
    """Downloads release.py of a release (tag None = the latest release) into folder.
    Returns (version, path), or (None, None) when that fails."""
    args = ["release", "download"] + ([tag] if tag else []) + [
        "--repo", UPDATE_REPO, "--pattern", UPDATE_ASSET, "--dir", str(folder), "--clobber"]
    r = gh(*args, check=False, timeout=timeout)
    path = Path(folder) / UPDATE_ASSET
    if r.returncode != 0 or not path.is_file():
        return None, None
    return version_of(path.read_text(encoding="utf-8", errors="replace")), path


def release_copies():
    """[[version, [release tags]], ...] for every published release that carries release.py, the highest
    version first. One small download per release."""
    r = gh("api", f"repos/{UPDATE_REPO}/releases", "--paginate", "--jq",
           f'.[] | select(.draft | not) | select(any(.assets[]; .name == "{UPDATE_ASSET}")) | .tag_name')
    tags = [t.strip() for t in r.stdout.splitlines() if t.strip()]
    found = []
    with tempfile.TemporaryDirectory() as tmp:
        for i, tag in enumerate(tags):
            version, _ = fetch_copy(tag, Path(tmp) / str(i))
            if version is None:
                continue
            for entry in found:
                if entry[0] == version:
                    entry[1].append(tag)
                    break
            else:
                found.append([version, [tag]])
    return sorted(found, key=lambda e: version_key(e[0]), reverse=True)


def current_version():
    return __version__.split()[-1]


def newer_version_notice():
    """Prints a notice when the latest release carries a newer release.py. Silent on any problem."""
    try:
        with tempfile.TemporaryDirectory() as tmp:
            latest, _ = fetch_copy(None, tmp, timeout=20)
        if latest and version_key(latest) > version_key(current_version()):
            warn(f" release.py {latest} is available (this is {current_version()}). "
                 f"To install it run: release.bat --update")
    except Exception:
        pass


def update_self(wanted):
    """--update (latest), --update=<version> or --update=list."""
    if wanted == "list":
        copies = release_copies()
        if not copies:
            fail(f"No release.py was found in the releases of {UPDATE_REPO}.")
        print(f" release.py versions in the releases of {UPDATE_REPO} (this copy is {current_version()}):")
        for version, tags in copies:
            print(f"   release.py {version}   (release {', '.join(tags)})")
        return 0
    if wanted is not None and not VERSION_RE.match(wanted):
        fail(f"'{wanted}' is not a version like 0.0.6. Use --update, --update=<version> or --update=list.")
    with tempfile.TemporaryDirectory() as tmp:
        if wanted is None:
            version, path = fetch_copy(None, Path(tmp))
        else:
            copies = release_copies()
            tag = next((tags[0] for version, tags in copies if version == wanted), None)
            if tag is None:
                fail(f"release.py {wanted} is not in any release of {UPDATE_REPO}. Available: "
                     + (", ".join(v for v, _ in copies) or "none"))
            version, path = fetch_copy(tag, Path(tmp))
        if version is None:
            fail(f"Could not download release.py from {UPDATE_REPO}. Nothing was changed.")
        data = path.read_bytes()
        try:
            compile(data.decode("utf-8"), UPDATE_ASSET, "exec")
        except (SyntaxError, UnicodeDecodeError, ValueError) as err:
            fail(f"The downloaded release.py {version} is not valid Python ({err}). Nothing was changed.")
        if version == current_version():
            print(f" release.py is already version {version}. Nothing was changed.")
            return 0
        old = current_version()
        folder = ROOT / "backup"
        folder.mkdir(exist_ok=True)
        saved = folder / f"release_{old}.py"
        _remove(saved)
        saved.write_bytes(SELF.read_bytes())
        os.chmod(saved, stat.S_IREAD)
        SELF.write_bytes(data)
    ok(f"[UPDATE] release.py {old} -> {version}")
    print(f" The previous copy was saved as backup/{saved.name}")
    return 0


# --- Main ---------------------------------------------------------------

def main(argv):
    total = 9
    os.chdir(ROOT)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    if len(argv) > 1 and argv[1] in ("-h", "--help", "/?"):
        print(__doc__)
        return 0
    print(f"{__version__}")
    if len(argv) > 1:
        m = re.fullmatch(r"--?update(?:=(.*))?", argv[1], re.IGNORECASE)
        if m:
            return update_self((m.group(1) or "").strip() or None)
    message = " ".join(argv[1:]).strip()
    newer_version_notice()

    step(1, total, "Reading release.ini and the version from the source file...")
    cfg = load_config()
    version = read_version(cfg)
    tag = cfg.tag_prefix + version
    print(f" PROJECT: {cfg.name}\n VERSION: {version}   (from {cfg.version_file})")
    if cfg.tag_prefix:
        print(f" TAG:     {tag}")

    step(2, total, "Checking git and GitHub...")
    if not (ROOT / ".git").exists():
        fail("This folder is not a git repository. Run gitinit.py first.")
    if git("rev-parse", "--verify", "-q", "HEAD", check=False).returncode != 0:
        fail("The repository has no commits yet.")
    branch = git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    if branch != cfg.branch:
        fail(f"You are on branch '{branch}', but release.ini says '{cfg.branch}'.")
    if git("remote", "get-url", "origin", check=False).returncode != 0:
        fail("The repository has no 'origin' remote.")
    if gh("auth", "status", check=False).returncode != 0:
        fail("The GitHub CLI is not logged in. Run: gh auth login")
    assets, missing = expand(cfg.assets, cfg.root)
    if missing:
        fail("Files listed in [assets] were not found: " + ", ".join(missing))
    print(f" Branch: {branch}   Asset files: {len(assets)}")

    step(3, total, "Determining release mode...")
    exists = git("rev-parse", "-q", "--verify", f"refs/tags/{tag}", check=False).returncode == 0
    mode = "UPDATE" if exists else "RELEASE"
    print(f" MODE: {mode}")
    if mode == "RELEASE":
        if not message:
            fail(f'A message is REQUIRED for a new version.  Usage: release.bat "Your commit message"')
        print(f" MESSAGE: {message}")
        if remote_tag_exists(tag) or find_releases(tag)[1] is not None:
            fail(f"Version {tag} is already released on GitHub.\n"
                 f"Raise the version in {cfg.version_file} for a new release.")
    else:
        tag_commit = git("rev-list", "-n", "1", tag).stdout.strip()
        head = git("rev-parse", "HEAD").stdout.strip()
        if tag_commit != head:
            fail(f"Tag {tag} exists but is not on the latest commit, so the commit cannot be amended.\n"
                 f"Raise the version in {cfg.version_file} for a new release.")
        print(" MESSAGE: N/A - UPDATE mode")

    step(4, total, "Creating backup...")
    backup = make_backup(cfg, version)
    ok(f"[BACKUP] {backup.relative_to(ROOT).as_posix()} (read-only)")

    step(5, total, "Building...")
    if cfg.build:
        r = subprocess.run(cfg.build, shell=True, cwd=ROOT)
        if r.returncode != 0:
            fail("Build failed.")
        ok("[BUILD] done")
    else:
        print(" No build command in release.ini, skipped.")

    step(6, total, "Checking for new files...")
    review_new_files(cfg)
    # Assets are re-resolved: the build may have created them.
    assets, missing = expand(cfg.assets, cfg.root)
    if missing:
        fail("Files listed in [assets] were not found: " + ", ".join(missing))

    step(7, total, "Staging, committing and tagging...")
    update_gitattributes(cfg)
    git_visible("add", "-A", "-v")
    if mode == "UPDATE":
        git_visible("commit", "--amend", "--no-edit")
        notes = git("log", "-1", "--format=%B").stdout.strip()
        git_visible("tag", "-f", "-a", tag, "-m", notes)
    else:
        git_visible("commit", "-m", message)
        notes = message
        git_visible("tag", "-a", tag, "-m", notes)

    step(8, total, "Pushing to GitHub...")
    tag_is_public = mode == "UPDATE" and remote_tag_exists(tag)
    if mode == "UPDATE":
        git_visible("push", "--force-with-lease", "-u", "origin", branch)
    else:
        git_visible("push", "-u", "origin", branch)
    if tag_is_public:
        git_visible("push", "--force", "origin", tag)       # keeps an already public tag on the amended commit
    else:
        print(f" Tag {tag} is NOT pushed: GitHub creates it when the draft release is published.")

    step(9, total, "Creating the draft release on GitHub...")
    sha = git("rev-parse", "HEAD").stdout.strip()
    url = draft_release(cfg, tag, notes, assets, sha)

    print()
    ok("===========================================")
    ok(f" SUCCESS! {mode} complete for {tag}")
    ok("===========================================")
    print(" The release is a DRAFT. Publish it yourself on GitHub" + (f":\n   {url}" if url else ".")
          + ("" if tag_is_public else f"\n The tag {tag} becomes visible only when you publish."))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv))
    except ReleaseError as err:
        print(f"\n{RED}!! ERROR: {err}{RESET}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nAborted.")
        sys.exit(1)
