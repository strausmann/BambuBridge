<!--
SPDX-FileCopyrightText: 2026 Björn Strausmann and BambuBridge contributors
SPDX-License-Identifier: AGPL-3.0-or-later
-->

# Examples

Three compose files, each with the app and Postgres 18:

| File | Use it when |
|---|---|
| `compose.standalone.yml` | the app is reached directly on a trusted LAN |
| `compose.pangolin.yml` | Pangolin (Newt) is in front and does the sign-in |
| `compose.traefik.yml` | Traefik is in front |

The container reads exactly five start variables:

| Variable | Meaning |
|---|---|
| `BAMBUBRIDGE_DATABASE_URL` | Postgres 18 connection URL (`postgresql+asyncpg://...`) |
| `BAMBUBRIDGE_SECRET_KEY` | 32 random bytes, base64url: `openssl rand -base64 32 \| tr '+/' '-_'` |
| `BAMBUBRIDGE_PUBLIC_URL` | the URL users open, used for links and the cookie scope |
| `BAMBUBRIDGE_BOOTSTRAP_ADMIN_KEY` | one-time key (32+ characters) for the first sign-in; empty disables it |
| `FORWARDED_ALLOW_IPS` | exactly one address: the reverse proxy (never `*`, no range, no list) |

Everything else is set in the web UI. Data lives in bind mounts under `/docker/stacks/bambubridge/`
(no named volumes), so a backup of that directory is a backup of the installation.

Verify the image signature before you run it. cosign 3 or newer is required: the images are signed
with cosign 3, whose bundle format cosign 2 cannot verify.

```sh
cosign verify --key cosign.pub ghcr.io/strausmann/bambubridge:0.2.0
```
