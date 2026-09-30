<div align="center">

  [![](https://img.shields.io/badge/License-AGPL_3.0-blue.svg?style=for-the-badge)](https://www.gnu.org/licenses/agpl-3.0)
  [![](https://img.shields.io/github/v/release/rob-vandenberg/gitinit?style=for-the-badge&color=brightgreen&label=Version)](https://github.com/rob-vandenberg/gitinit/releases)

  <p align="center">
    <strong>Sets up a new project folder with git, a GitHub repository and release tooling.</strong>
  </p>

</div>

---

# gitinit

One initializer per project type, plus one shared `release.py`:

| File | What it does |
| --- | --- |
| `gitinit-c.py` | Sets up a new C project. |
| `gitinit-py.py` | Sets up a new Python project or Home Assistant integration. |
| `release.py` | Backs up, commits, tags, pushes and creates the GitHub release. Used by every project. |

Each script keeps its own `__version__`; the version of this repository is the `version` key of `gitinit.json`.

## Requirements

Python 3, git and the GitHub CLI (`gh`), logged in with `gh auth login`.

## Getting the files

Download only the scripts of the latest release into your new project folder:

```
gh release download --repo rob-vandenberg/gitinit --pattern gitinit-py.py --pattern release.py
```

Use `--pattern gitinit-c.py` instead of `gitinit-py.py` for a C project.

## Usage

Run the initializer once in the new project folder:

```
python gitinit-py.py
```

Afterwards, release with `release.bat "message"` (Windows) or `./release.sh "message"`.

## License

AGPL-3.0-or-later. See [LICENSE](LICENSE).
