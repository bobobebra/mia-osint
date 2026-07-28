# Third-party tool catalog

MIA manages and may invoke separate third-party tools. Their source code is not
vendored into the MIA Python package, and MIA's MIT License does not replace
or override their licenses. Catalog inclusion is not endorsement, audit,
certification, or a guarantee that installation remains compatible.

Always review the current upstream repository, release, dependencies, license,
terms, data sources, maintenance status, and legal requirements before use.

## Current catalog

| ID | Project | License | Integration | Risk |
|---|---|---|---|---|
| `amass` | [OWASP Amass](https://github.com/owasp-amass/amass) | Apache-2.0 | `managed-only` | `mixed` |
| `asnmap` | [asnmap](https://github.com/projectdiscovery/asnmap) | MIT | `managed-only` | `passive` |
| `assetfinder` | [Assetfinder](https://github.com/tomnomnom/assetfinder) | MIT | `full` | `passive` |
| `blackbird` | [Blackbird](https://github.com/p1ngul1n0/blackbird) | unknown | `raw` | `passive` |
| `censys` | [Censys CLI](https://github.com/censys/censys-python) | Apache-2.0 | `managed-only` | `passive` |
| `chaos-client` | [Chaos Client](https://github.com/projectdiscovery/chaos-client) | MIT | `managed-only` | `passive` |
| `cloud-enum` | [cloud_enum](https://github.com/initstring/cloud_enum) | MIT | `managed-only` | `mixed` |
| `dnsrecon` | [DNSRecon](https://github.com/darkoperator/dnsrecon) | GPL-2.0+ | `managed-only` | `mixed` |
| `dnstwist` | [dnstwist](https://github.com/elceef/dnstwist) | Apache-2.0 | `full` | `mixed` |
| `dnsx` | [dnsx](https://github.com/projectdiscovery/dnsx) | MIT | `managed-only` | `mixed` |
| `exiftool` | [ExifTool](https://exiftool.org/) | Artistic-1.0 OR GPL-1.0+ | `full` | `local` |
| `findomain` | [Findomain](https://github.com/Findomain/Findomain) | GPL-3.0 | `raw` | `passive` |
| `gau` | [gau](https://github.com/lc/gau) | MIT | `full` | `passive` |
| `ghunt` | [GHunt](https://github.com/mxrch/GHunt) | AGPL-3.0 | `managed-only` | `passive` |
| `github-subdomains` | [github-subdomains](https://github.com/gwen001/github-subdomains) | MIT | `managed-only` | `passive` |
| `h8mail` | [h8mail](https://github.com/khast3x/h8mail) | MIT | `managed-only` | `passive` |
| `holehe` | [Holehe](https://github.com/megadose/holehe) | GPL-3.0 | `full` | `passive` |
| `httpx` | [httpx](https://github.com/projectdiscovery/httpx) | MIT | `full` | `mixed` |
| `maigret` | [Maigret](https://github.com/soxoj/maigret) | MIT | `full` | `passive` |
| `mosint` | [Mosint](https://github.com/alpkeskin/mosint) | MIT | `managed-only` | `passive` |
| `oletools` | [oletools](https://github.com/decalage2/oletools) | BSD-2-Clause | `managed-only` | `local` |
| `osrframework` | [OSRFramework](https://github.com/i3visio/osrframework) | AGPL-3.0+ | `managed-only` | `passive` |
| `pdfinfo` | [pdfinfo](https://poppler.freedesktop.org/) | GPL-2.0+ | `managed-only` | `local` |
| `phoneinfoga` | [PhoneInfoga](https://github.com/sundowndev/phoneinfoga) | GPL-3.0 | `raw` | `passive` |
| `recon-ng` | [Recon-ng](https://github.com/lanmaster53/recon-ng) | GPL-3.0 | `managed-only` | `mixed` |
| `sherlock` | [Sherlock](https://github.com/sherlock-project/sherlock) | MIT | `full` | `passive` |
| `shodan` | [Shodan CLI](https://github.com/achillean/shodan-python) | MIT | `managed-only` | `passive` |
| `social-analyzer` | [Social Analyzer](https://github.com/qeeqbox/social-analyzer) | AGPL-3.0 | `raw` | `passive` |
| `spiderfoot` | [SpiderFoot](https://github.com/smicallef/spiderfoot) | MIT | `full` | `passive` |
| `strings` | [GNU strings](https://www.gnu.org/software/binutils/) | GPL-3.0+ | `managed-only` | `local` |
| `subfinder` | [Subfinder](https://github.com/projectdiscovery/subfinder) | MIT | `full` | `passive` |
| `theharvester` | [theHarvester](https://github.com/laramies/theHarvester) | GPL-2.0 | `raw` | `passive` |
| `tlsx` | [tlsx](https://github.com/projectdiscovery/tlsx) | MIT | `managed-only` | `mixed` |
| `uncover` | [uncover](https://github.com/projectdiscovery/uncover) | MIT | `managed-only` | `passive` |
| `vt-cli` | [VirusTotal CLI](https://github.com/VirusTotal/vt-cli) | Apache-2.0 | `managed-only` | `passive` |
| `wafw00f` | [WAFW00F](https://github.com/EnableSecurity/wafw00f) | BSD-3-Clause | `managed-only` | `mixed` |
| `waybackurls` | [waybackurls](https://github.com/tomnomnom/waybackurls) | MIT | `managed-only` | `passive` |
| `waymore` | [waymore](https://github.com/xnl-h4ck3r/waymore) | MIT | `managed-only` | `passive` |
| `whatweb` | [WhatWeb](https://github.com/urbanadventurer/WhatWeb) | GPL-2.0 | `managed-only` | `mixed` |
| `whois` | [WHOIS](https://github.com/rfc1036/whois) | GPL-2.0+ | `full` | `passive` |

License values are catalog metadata and may become stale or incomplete. The
upstream project is authoritative. `unknown` must be treated as requiring
manual license review before redistribution.

## Install channels

The package manager supports reviewed recipe types rather than arbitrary shell
commands: isolated Python environments, uv source projects, Go modules, Cargo
crates, selected Git repositories with wrappers, distribution/Homebrew
packages, and dedicated Holehe/SpiderFoot compatibility recipes.

Some recipes use moving package versions or `@latest`. The resolved code can
change without a MIA release. Controlled deployments should pin reviewed
versions or commits in a fork, verify upstream hashes/signatures where
available, and retain an exact installed inventory.

## API-backed tools

MIA does not provide accounts or API access. Some tools require user-supplied
credentials and may impose fees, quotas, contracts, or platform terms. MIA does
not store secrets; follow upstream setup documentation and never publish
tokens in issues or reports.

## Maintenance warnings

Tools marked `unmaintained` reflect an upstream warning or apparent dormant
status at catalog review time. They are optional, may be insecure or broken,
and should receive additional review before installation.

## Optional AI assistant providers

MIA can send bounded normalized case evidence to user-configured
OpenAI-compatible endpoints, Google Gemini, or Ollama. These services and local
model runtimes are not bundled with MIA and are governed by their own licenses,
privacy policies, account terms, regional availability, quotas, and model
licenses. Local Ollama can operate without an API key, but the selected model's
license still applies. Review provider and model terms before processing case
data.
