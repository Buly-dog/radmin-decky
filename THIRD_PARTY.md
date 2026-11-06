# External runtime

The installer downloads, verifies and extracts RadminVPN-Linux-x86_64.AppImage
from https://github.com/baptisterajaut/radmin-vpn-linux/releases/tag/v1.1.1.
The AppImage is not included in this plugin bundle.

- Upstream interoperability code: baptisterajaut/radmin-vpn-linux, GPL-3.0.
- Wine: https://www.winehq.org/ (LGPL); upstream's bundled Kron4ek build.
- Radmin VPN: proprietary Famatech application, downloaded by upstream from
  the vendor on initial setup. No Radmin binaries are included here.
- Decky Loader/API/UI: https://github.com/SteamDeckHomebrew.

scripts/patch_runtime.py contains the complete local script adaptations. It
changes signal handling, process scoping, service supervision and privileged
network dispatch. The original scripts can be obtained from upstream v1.1.1.
The unmodified fixtures in tests/upstream retain their GPL-3.0 license,
included at tests/upstream/LICENSE.
The plugin is not affiliated with Famatech or the upstream projects.
