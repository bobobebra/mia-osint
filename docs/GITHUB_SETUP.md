# Publishing the repository on GitHub

This tree is prepared for a public repository but does not assume the owner's
GitHub username or final repository name.

## Create the repository

With the GitHub CLI:

```console
git init
git branch -M main
git add .
git commit -m "Initial public alpha release"
gh repo create mia --public --source=. --remote=origin --push
```

Or create an empty public repository in the GitHub web interface, then run the
commands GitHub displays for an existing local repository.

## Recommended repository settings

- Suggested description: “A local-first app for finding, organizing, and reviewing public information.”
- Suggested topics: `osint`, `open-source-intelligence`, `python`, `local-first`,
  `research-tools`, `privacy`, `tauri`, and `investigation`.
- Enable Issues and, optionally, Discussions.
- Enable private vulnerability reporting.
- Enable Dependabot alerts, secret scanning, and push protection where
  available.
- Protect `main` and require the `CI` workflow before merging.
- Disable force pushes and branch deletion on `main`.
- Require pull-request review when more maintainers join.

## Add repository URLs to package metadata

The public repository URLs are recorded in `pyproject.toml`:

```toml
[project.urls]
Documentation = "https://github.com/bobobebra/mia-osint/tree/main/docs"
Issues = "https://github.com/bobobebra/mia-osint/issues"
Source = "https://github.com/bobobebra/mia-osint"
```

Do not publish placeholder URLs.

## First tag and release

```console
git tag -a v4.2.0-alpha.11 -m "MIA 4.2.0 alpha 11"
git push origin v4.2.0-alpha.11
```

The release workflow builds the Windows x64 setup, self-extracting Linux
installer, Linux bootstrapper, wheel, source distribution, repository ZIP, and
complete SHA-256 file. It creates the prerelease only after both the Windows and
portable jobs succeed.

Before tagging, follow `RELEASING.md` and confirm that the release notes repeat
the alpha, vibe-coding, no-audit, and false-positive warnings.
