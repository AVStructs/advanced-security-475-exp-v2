# Deploy packs (server and client)

**Full checklist (VM + USB + Windows 8 in order):** **[START-TO-FINISH.md](START-TO-FINISH.md)**.

Step-by-step for building the Windows **`.exe`** bundle and copying it with a **Linux USB** onto the target SSD: see **[EXE-DEPLOYMENT-GUIDE.md](EXE-DEPLOYMENT-GUIDE.md)**.

### Your lab topology (as described)

| Machine | OS | Role |
|--------|-----|------|
| **Operator** | **Linux VM** | Runs **`listener.py`** (TCP server). SSH or desktop session on the VM; CLI and optional **Ctrl+Alt+T** / **Ctrl+Alt+Q** (needs GUI + `pynput` on Linux). |
| **Target laptop** | **Windows 8** | Runs **`ControlChannelTarget.exe`** (or Python connector). Connects **out** to the Linux VM. Media plays here on **PLAY**. |
| **USB stick** | **Linux live** | Only used to **mount the Windows 8 SSD** and **copy** the exe bundle onto the internal disk — it is **not** the operator (the VM is). |

Set **`operator_host`** in **`target/target.ini`** (or next to your exes) to the **Linux VM’s hostname or IP** (reachable from the Windows 8 network).

This folder holds **two bundles** you can copy to machines independently:

| Folder | Role | Typical host |
|--------|------|----------------|
| **`server/`** | Operator TCP listener + CLI + optional global hotkeys | **Linux VM** (course server, cloud VM, etc.) |
| **`client/`** | Target connector + fullscreen player + Windows bootstrap | **Windows 8** target laptop |

Canonical sources live at the repo root (`operator/`, `target/`, `cv2_hack.py`, etc.). **Refresh the bundles** whenever you change code:

```powershell
cd path\to\Advanced security 475 exp v2
.\deploy\pack-deploy.ps1
```

Then zip **`deploy/server`** and **`deploy/client`** separately if you need to move them.

---

## Server bundle (`deploy/server`)

### Contents

- **`listener.py`** — binds TCP, accepts target connections, CLI, Ctrl+Alt+T / Ctrl+Alt+Q hotkeys (needs `pynput`).
- **`operator.ini`** — bind address/port (`0.0.0.0:47001` by default), optional `allowed_subnets`, command timeout.
- **`requirements.txt`** — `pynput` for global hotkeys (optional; listener runs without it if you use `--no-hotkeys`).

### Deploy operator on Linux (VM)

1. Copy the **`server`** folder to the VM (e.g. `~/control-channel-server/`).
2. Install **Python 3.9+** if needed.
3. Create a venv (recommended):

   ```bash
   cd ~/control-channel-server
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

4. Open the VM firewall / security group for **TCP inbound 47001** (or whatever port is in `operator.ini`).
5. Run the listener (leave this session open):

   ```bash
   python listener.py
   ```

6. Optional: global hotkeys need a **desktop session** and `pynput` on Linux. Over **SSH without X11**, use:

   ```bash
   python listener.py --no-hotkeys
   ```

   and use the text CLI (`play`, `stop`, `broadcast`, etc.).

### Deploy operator on Windows (optional)

If you ever run the operator on a Windows PC instead: copy **`server/`**, use **`python -m venv venv`**, **`pip install -r requirements.txt`**, allow **inbound TCP 47001** in Windows Firewall, then **`python listener.py`**.

### Hotkeys (operator machine with GUI)

- **Ctrl+Alt+T** — broadcast **`PLAY`** to every connected target (uses each target’s `default_video` in `target.ini`).
- **Ctrl+Alt+Q** — broadcast **`STOP`** to every connected target.

---

## Client bundle (`deploy/client`)

### Layout

```
client/
  target/
    connector.py   # control channel client
    target.ini     # operator_host, media defaults
    launch.vbs     # hidden restart loop (optional)
  cv2_hack.py      # fullscreen player (spawned on PLAY)
  requirements.txt
  install-target.ps1   # optional HKCU Run persistence
  script.bat            # local venv + test playback
  silent_run.vbs
```

`target.ini` uses **`[media] project_root = ..`**: media files and `cv2_hack.py` live in **`client/`** (parent of `target/`). Put **`giraffe_clipped.mp4`** and **`giraffe_clipped_audio.mp3`** (or your own assets) in the **repo root**, then run **`.\deploy\pack-deploy.ps1`** — it copies **`*.mp3`**, **`*.mp4`**, **`*.mkv`**, **`*.wav`** from the repo root into **`deploy/client/`** when those files exist. If you add media only on one PC, copy them by hand into **`deploy/client/`** next to **`cv2_hack.py`**. You can also change **`default_video`** / **`default_audio`** in **`target.ini`** to match whatever filenames you use.

### Deploy on Windows

1. Copy the **`client`** folder to the PC (e.g. `C:\control-channel-client\`).
2. Edit **`client\target\target.ini`**:
   - **`operator_host`** — hostname or IP of the **Linux VM** running `listener.py` (must be reachable from the Windows 8 network; VM firewall allows **47001**).
   - **`client_name`** — optional label shown in operator logs.
3. Open **PowerShell** in `client\`:

   ```powershell
   cd C:\control-channel-client
   python -m venv venv
   .\venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```

4. Run the connector (console, good for debugging):

   ```powershell
   python .\target\connector.py
   ```

   Or hidden loop (after venv exists):

   ```powershell
   wscript.exe .\target\launch.vbs
   ```

5. Optional persistence (current user only):

   ```powershell
   .\install-target.ps1
   ```

   Default **`-TargetDir`** is `.\target` next to the script; from `client\` root that points at `client\target\`. Remove with **`.\install-target.ps1 -Remove`**.

### Test video only (no operator)

From `client\`:

```powershell
.\script.bat
```

(Ensure `giraffe_clipped.mp4` / `.mp3` paths match `script.bat` or edit the batch file.)

---

## Windows target: `.exe` bundle (Startup folder, no Python install)

There was **no** standalone `.exe` in the repo before; you build it with PyInstaller.

### Build (on a Windows dev machine)

From the repo root:

```powershell
.\deploy\client\build-exe.ps1
```

Optional: **`.\deploy\client\build-exe.ps1 -Console`** so `ControlChannelTarget.exe` shows a console for debugging.

Output folder: **`deploy/client/target-exe-bundle/`**

| File | Role |
|------|------|
| **`ControlChannelTarget.exe`** | Connector (windowed by default = no console). |
| **`cv2_hack.exe`** | Fullscreen player started on **PLAY**. |
| **`target.ini`** | Copied from `target/target.ini` with **`project_root = .`** so video/audio can sit **in the same folder as the exes**. |

Copy your **`giraffe_clipped.mp4`** / **`giraffe_clipped_audio.mp3`** (or other media) into that folder and edit **`target.ini`** (`operator_host`, `default_video` / `default_audio` names).

### Install on Windows 8 (current user Startup)

1. Copy the **whole** `target-exe-bundle` folder to the PC, e.g. `C:\ControlChannel\`.
2. Edit **`target.ini`** inside that folder (`operator_host`, etc.).
3. Open the **Startup** folder for the logged-in user (Run dialog, `shell:startup`), or browse to:

   `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup`

4. Create a **shortcut** to **`ControlChannelTarget.exe`** in that Startup folder (recommended: shortcut, not the exe alone, so you can set “Start in” to `C:\ControlChannel\` if needed).

On logon, Windows starts the connector; it connects outbound to the operator and waits for **PLAY** / **STOP**.

### USB stick (portable copy)

Copying from a USB drive is normal: put the **entire** `target-exe-bundle` folder (or the full `deploy/client` tree if you use Python instead of exes) on the stick, then on the Windows PC paste it to a fixed path such as **`C:\ControlChannel\`**. Keep **all** of these **in the same folder** on the hard drive: `ControlChannelTarget.exe`, `cv2_hack.exe`, `target.ini`, and your video/audio files. Edit **`target.ini`** on the PC (or on the stick before the last copy) so **`operator_host`** is correct.

**Linux on the USB (live system):** That is fine. Boot the stick, **mount the Windows SSD partition** (the volume that holds `C:\` when Windows runs — often NTFS), and copy the bundle **onto that partition** (e.g. `.../Users/Public/ControlChannel/` or `.../ControlChannel/` depending on mount path). You are only using Linux as a file manager; Windows will still see the same files on its SSD after reboot. Mount read‑write only if you need to write; double‑check you are writing to the **Windows data partition**, not the live USB’s own filesystem.

After paste, if Windows blocks execution, right‑click each **`.exe`** → **Properties** → check **Unblock** if shown. Then add the **Startup** shortcut pointing at **`ControlChannelTarget.exe`** on the **SSD path** (e.g. `C:\ControlChannel\...`), not a path that only exists while the Linux USB is mounted.

### Windows 8 / old OS note

Official Python builds after **3.8** may **not** support Windows 8.x. If the `.exe` will not run on your target, build on **Python 3.8 (32-bit or 64-bit to match the OS)** and an older PyInstaller that still supports that Python/OS pair.

---

## End-to-end check

1. **Linux VM:** `python listener.py` in **`server/`**, firewall allows **47001**, note hostname/IP (`hostname -I` or your course DNS name).
2. **Windows 8:** `operator_host` in **`target.ini`** matches that host; run **`ControlChannelTarget.exe`** or `python target\connector.py`.
3. On the **VM** operator console, **`list`** → **`use <sid>`** → **`ping`** should show **`PONG`**.
4. **`play`** or **Ctrl+Alt+T** starts fullscreen playback on the **Windows 8** laptop; **`stop`** or **Ctrl+Alt+Q** stops it.

---

## Protocol reminder

- The **target** opens an **outbound TCP** connection to the **operator** (reverse direction of a typical “download” mental model).
- Commands and replies are **one line each**, UTF-8, newline-terminated, on the **same** socket.
