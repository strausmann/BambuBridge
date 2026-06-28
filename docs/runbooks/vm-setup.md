# Runbook — Dev-VM-Setup (BambuBridge)

Reproduzierbare Einrichtung der Entwicklungs-VM für BambuBridge. **Keine Secrets** in diesem
Dokument — Tokens/Passwörter werden nur als Platzhalter genannt und liegen ausschließlich auf der
VM bzw. im Passwortmanager.

> Prinzip: Auf dem Host nur das Nötige (Docker, Node, Python, Remote-Desktop). Sonstige
> Dev-Tools laufen in **Containern**, nicht auf dem Host.

## 0. Eckdaten
- OS: **Ubuntu 26.04 LTS** (x86_64), GNOME 50 (Wayland), Boot: **UEFI**.
- Hostname/VM: `BambuStudio` (Proxmox/QEMU).
- Projektpfad: `~/Repos/BambuBridge` (User `strausmann`).

## 1. Benutzer & Zugriff
- **Passwortloses sudo** für `strausmann`:
  ```bash
  echo 'strausmann ALL=(ALL) NOPASSWD:ALL' | sudo tee /etc/sudoers.d/strausmann-nopasswd
  sudo chmod 440 /etc/sudoers.d/strausmann-nopasswd
  sudo visudo -c -f /etc/sudoers.d/strausmann-nopasswd
  ```
- **GitHub-Token** (Scopes inkl. `repo`, `workflow`, `read:org`): in `~/.bashrc`/`~/.profile` als
  `GH_TOKEN`/`GITHUB_TOKEN` exportiert; `gh auth login --with-token`; `gh auth setup-git` für
  git-over-https. **Token nie committen.** Bei Leak: auf GitHub widerrufen.

## 2. Docker + Dev-Netzwerk
```bash
sudo apt-get install -y docker.io docker-compose-v2 docker-buildx
sudo systemctl enable --now docker
sudo usermod -aG docker strausmann      # neu einloggen für Gruppenwirkung
# Gemeinsames Netz für Container, die via Pangolin/Newt publiziert werden — NATIV (kein Stack):
docker network create traefik-public
```
Container, die über Pangolin erreichbar sein sollen, an `traefik-public` hängen.

## 3. Node.js
```bash
# NodeSource 22.x (für semantic-release, prettier, commitlint)
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo bash -
sudo apt-get install -y nodejs
```

## 4. Pangolin-Anbindung: Newt (systemd)
Site-Credentials in Pangolin unter **Sites → Add Site → Newt Tunnel** erzeugen (ID + Secret werden
**einmalig** angezeigt).
```bash
curl -fsSL https://static.pangolin.net/get-newt.sh | sudo bash    # -> /usr/local/bin/newt
sudo install -d -m 0755 /etc/newt
sudo tee /etc/newt/newt.env >/dev/null <<'EOF'
NEWT_ID=<aus Pangolin>
NEWT_SECRET=<aus Pangolin>
PANGOLIN_ENDPOINT=https://connect.strausmann.cloud
EOF
sudo chmod 600 /etc/newt/newt.env
# systemd-Unit /etc/systemd/system/newt.service (EnvironmentFile=/etc/newt/newt.env,
# ExecStart=/usr/local/bin/newt, Restart=always)
sudo systemctl daemon-reload && sudo systemctl enable --now newt
sudo systemctl status newt        # "Tunnel connection established / Ready to accept connections"
```

## 5. Remote-Desktop
Hintergrund: GNOME 50 ist **Wayland-only** → echtes GNOME geht nur per **RDP**; VNC liefert einen
separaten X11/XFCE-Desktop. Beides ist eingerichtet.

### 5a. VNC (TigerVNC, XFCE) → Pangolin-VNC-Ressource
- Konsole belegt `:0` (Xwayland) und `:1`; daher VNC-Display **`:2`**, aber **RFB-Port fest 5900**.
- `systemd`-Unit `bambustudio-vnc.service` (User `strausmann`):
  `ExecStart=/usr/bin/tigervncserver :2 -rfbport 5900 -localhost yes -SecurityTypes None -geometry 1600x900 -fg`
- `~/.vnc/xstartup` startet XFCE und erzwingt X11 (`unset WAYLAND_DISPLAY`, `GDK_BACKEND=x11`).
- Localhost-only; die Auth macht Pangolin → im Pangolin-VNC-Client **Passwort leer lassen**.
- Pangolin-VNC-Ressource: Ziel `127.0.0.1`, Port `5900`.

### 5b. RDP (gnome-remote-desktop, „Desktop Sharing") → Pangolin-RDP-Ressource
- Teilt die **laufende GNOME-Session**; lauscht auf `3389`, TLS self-signed.
- **Credentials MÜSSEN in der grafischen User-Session gesetzt werden** (Keyring), sonst
  persistieren sie nicht → irreführender „CredSSP/MIC"-Fehler:
  ```bash
  # im eigenen GNOME-Terminal (nicht via ssh/sudo/runuser):
  grdctl rdp set-credentials <user> '<wunsch-passwort>'
  grdctl rdp enable
  grdctl rdp disable-view-only
  systemctl --user restart gnome-remote-desktop
  ```
- Pangolin-RDP-Ressource: Ziel `127.0.0.1`, Port `3389`.
- **Native Clients** (Windows `mstsc`, Remmina, FreeRDP) funktionieren — bei `mstsc` Benutzer als
  `.\\<user>` (leere Domäne, reines NTLM) eingeben.
- **Browser-RDP von Pangolin ist aktuell blockiert** (IronRDP „Deactivate All"-Bug, gefixt auf
  IronRDP-`master`, aber noch nicht im gebündelten WASM) → siehe fosrl/pangolin#3272. Bis dahin:
  nativer RDP-Client oder VNC.

## 6. Energieverwaltung
Damit die VM nicht versehentlich schläft (relevant bei langem Idle):
```bash
sudo systemctl mask sleep.target suspend.target hibernate.target suspend-then-hibernate.target
```
(`logind` `IdleAction=ignore` ist Default; Maskierung schließt versehentliches Auslösen aus.)

## 7. Python-Dev (Projekt)
```bash
sudo apt-get install -y python3.14-venv
cd ~/Repos/BambuBridge && python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
python -m pytest -q
```

## 8. Stolpersteine (siehe auch docs/learnings/lessons-learned.md)
- `grdctl set-credentials` nur **in** der grafischen Session ausführen (Keyring).
- VNC-Display vor Belegung prüfen (`:0`/`:1` sind durch GNOME belegt → `:2`).
- `apt autoremove` vor Bestätigung prüfen (kann boot-nahe Pakete mitnehmen; auf UEFI sind
  BIOS-Grub-Pakete funktionslos).
