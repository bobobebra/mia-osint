# Releasing MIA

## Repository setup

1. Create a public GitHub repository.
2. Upload this tree to the repository root.
3. Replace or add `[project.urls]` in `pyproject.toml` after the final repository
   URL is known.
4. Enable GitHub private vulnerability reporting.
5. Enable branch protection for `main` and require the CI workflow.
6. Enable Dependabot and secret scanning where available.

## Release checklist

1. Update `src/mia/__init__.py`, `pyproject.toml`, the frontend package files,
   and the Tauri package/configuration to the same release version.
2. Update `CHANGELOG.md` and compatibility notes.
3. Run:

   ```console
   npm --prefix frontend-workbench ci
   npm --prefix frontend-workbench run build
   npm --prefix frontend-workbench run lint
   npm --prefix frontend-discover ci
   npm --prefix frontend-discover run build
   npm --prefix frontend-discover run lint
   python -m pip install -e '.[dev]'
   ruff check .
   ruff format --check .
   pytest
   bash -n install.sh uninstall.sh
   python -m build
   python -m twine check dist/*
   ```

4. Test installer dry runs and representative `mia pkg install ... --dry-run` selections.
5. Test a clean `--mia-only` install and package catalog/doctor commands in a temporary home directory.
6. Inspect the source archive for reports, databases, caches, tokens, and local
   paths.
7. Commit, create an annotated tag such as `v4.1.0-alpha.1`, and push it.
8. Let `.github/workflows/release.yml` build the Python, Linux, source, and
   Windows release assets. The workflow must not publish until all jobs and the
   final expected-asset/checksum gate pass.
9. Confirm that the Windows job passed both sidecar health checks and its silent
   install/uninstall test.
10. Publish known limitations in the release notes.

Do not claim a distro is supported solely because its package manager is
recognized. Record the exact distribution release and architecture actually
tested.


## Easy-install release assets

Build the self-extracting Linux installer after the packaged frontend assets are
current:

```console
bash scripts/build_linux_installer.sh dist/MIA-Linux-Installer.run
cp install-mia.sh dist/install-mia.sh
(cd dist && sha256sum * > SHA256SUMS.txt)
```

The release workflow performs these steps automatically. Smoke-test the exact
`.run` asset with a temporary `HOME`, `--mia-only`, and
`--skip-system-packages` before publishing. Confirm that `mia --version`,
`mia repair --no-desktop`, and both packaged `/api/health` endpoints work.
