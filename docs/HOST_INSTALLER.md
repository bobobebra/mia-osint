# Host installer

`install.sh` installs the MIA Core and delegates optional third-party packages to
`mia pkg`. It supports apt, dnf, pacman, zypper, apk, Homebrew Linux, and manual
prerequisite mode.

## Examples

```console
./install.sh                         # MIA + core tools
./install.sh --mia-only              # MIA only
./install.sh --with username         # core + username group
./install.sh --tool ghunt            # core + GHunt
./install.sh --all-tools             # all local/passive tools
./install.sh --all-tools --include-mixed
./install.sh --dry-run --yes
```

The installer is a convenience front end. After MIA exists, use the package
manager directly:

```console
mia pkg groups
mia pkg install --group domain --include-mixed
mia pkg uninstall dnstwist
mia pkg update --all
```

Detailed behavior, paths, distro caveats, and uninstallation are documented in
[`INSTALLATION.md`](INSTALLATION.md) and
[`PACKAGE_MANAGER.md`](PACKAGE_MANAGER.md).


## Self-extracting release installer

`scripts/build_linux_installer.sh` packages the source tree and `install.sh` into
a single `MIA-Linux-Installer.run` file. Running it with `bash` extracts to a
temporary directory and delegates every option to the normal installer. The
embedded project is removed when installation exits.

The release also publishes `install-mia.sh`, which downloads the latest `.run`
asset and verifies it against `SHA256SUMS.txt` when available.
