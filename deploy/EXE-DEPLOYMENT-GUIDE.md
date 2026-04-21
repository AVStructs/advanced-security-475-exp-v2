# Guide: getting the Windows `.exe` files onto the target SSD

This walkthrough assumes you **build** the executables on a Windows machine with Python, then **transfer** them to the lab Windows PC (e.g. Windows 8) using a **USB stick that boots Linux**, mounting the **Windows SSD** and copying files onto the partition Windows boots from.

### Topology you are using

| System | Role |
|--------|--------|
| **Linux VM** | Runs **`listener.py`** (operator). Allow **inbound TCP 47001**; put the VM hostname/IP in **`operator_host`** on the target. |
| **Windows 8** | Runs **`ControlChannelTarget.exe`** + media. Files are copied onto its SSD (often using **Linux on a USB stick** to mount NTFS and copy). |
| **Linux on USB** | **File transfer only** — mount the Windows 8 SSD and copy the bundle; it is **not** the operator (the VM is). |

---

## Part 1 — Build the executables (Windows build PC)

1. Clone or copy the project to the build PC (same repo you use in class).
2. Install **Python 3.x** (use **3.8** if the target is very old Windows; see README notes).
3. Open **PowerShell** and go to the repo root, for example:

   ```powershell
   cd "C:\path\to\Advanced security 475 exp v2"
   ```

4. Run the packager (optional but keeps `deploy/client` in sync):

   ```powershell
   .\deploy\pack-deploy.ps1
   ```

5. Build the two one-file programs:

   ```powershell
   .\deploy\client\build-exe.ps1
   ```

   For a **visible console** on the connector (easier first-time debugging on the target):

   ```powershell
   .\deploy\client\build-exe.ps1 -Console
   ```

6. When the script finishes, open:

   **`deploy\client\target-exe-bundle\`**

   You should see at least:

   - `ControlChannelTarget.exe`
   - `cv2_hack.exe`
   - `target.ini` (already adjusted for a **flat** folder: `project_root = .`)

7. Add **media** into that same folder (same names as in `target.ini`, or edit the INI):

   - Example: `giraffe_clipped.mp4`, `giraffe_clipped_audio.mp3`

8. Edit **`target.ini`** on the build PC (or wait until after copy on the target):

   - **`operator_host`** = your operator VM hostname or IP (e.g. course server).
   - **`operator_port`** = `47001` unless you changed the listener.
   - **`client_name`** = any short label you want in operator logs.

9. **Stage for USB** — Copy the **entire** `target-exe-bundle` folder to the USB stick’s **data partition** (FAT32/exFAT/NTFS) from Windows **or** copy it later from Linux after you put the tree on the stick from another machine.

You are done on the build PC once that folder is complete and on removable media (or ready to copy from a network share inside Linux).

---

## Part 2 — Boot Linux from the USB

1. Insert the USB stick into the **target** computer (the one whose **SSD** runs Windows).
2. Reboot and open the **boot menu** (vendor key: often F12, F10, Esc, etc.).
3. Choose the USB drive so the machine boots **Linux** (live environment), not Windows yet.

You will use Linux only as a **disk tool** to write onto the Windows partition.

---

## Part 3 — Mount the Windows SSD and copy files (Linux)

Exact steps depend on your Linux distro (Ubuntu live, Kali, etc.). The idea is always: **find the Windows NTFS partition → mount it → copy the bundle → sync → unmount**.

### 3.1 Identify the Windows partition

In a terminal (often you need **root** for mount):

```bash
sudo fdisk -l
# or
lsblk -f
```

Look for a large **NTFS** partition on the internal SSD (not the USB stick’s own small system partition). Note the device node, e.g. `/dev/sda2` or `/dev/nvme0n1p3`.

### 3.2 Create a mount point and mount read-write

```bash
sudo mkdir -p /mnt/windows
sudo mount -t ntfs-3g /dev/sdXY /mnt/windows
```

Replace **`/dev/sdXY`** with your real partition. If **BitLocker** encrypts the Windows volume, you must unlock it first (recovery key / password); plain NTFS is simpler for lab images.

### 3.3 Copy the bundle onto the Windows `C:` tree

Pick a path that will appear under Windows as something like **`C:\ControlChannel\`**. On the mounted volume, `C:\` is usually the **root** of the mount, e.g.:

```bash
sudo mkdir -p /mnt/windows/ControlChannel
sudo cp -a /path/on/usb/target-exe-bundle/. /mnt/windows/ControlChannel/
```

Adjust `/path/on/usb/...` to where the folder actually is on the USB (e.g. `/media/ubuntu/USBDRIVE/target-exe-bundle/`).

Verify:

```bash
ls -la /mnt/windows/ControlChannel/
```

You should see both `.exe` files, `target.ini`, and your media files.

### 3.4 Flush and unmount

```bash
sync
sudo umount /mnt/windows
```

Power off or reboot and **remove the USB** if you are done.

---

## Part 4 — Boot Windows and finish setup

1. Boot the PC **from the SSD** into Windows.
2. Open **`C:\ControlChannel\`** (or whatever path you used). Confirm all files are present.
3. **Unblock** (if needed): right‑click each **`.exe`** → **Properties** → if you see **Unblock**, check it → **OK**.
4. **Startup shortcut** (per user):

   - Press **Win+R**, run: `shell:startup`
   - Right‑click → **New** → **Shortcut**
   - Target: `C:\ControlChannel\ControlChannelTarget.exe` (use your real path)
   - Optional: set “Start in” to `C:\ControlChannel\`

5. **Network**: ensure this Windows machine can reach **`operator_host:47001`** (firewall, DNS, campus network rules).

6. **Test**: reboot once and confirm the connector runs (Task Manager → **Details** may show `ControlChannelTarget.exe`). On the operator VM, run **`list`** and confirm a session appears; **`ping`** → **`PONG`**.

---

## Part 5 — If something fails

| Symptom | Things to check |
|--------|-------------------|
| Exe never appears on disk | Mount point was wrong partition; `cp` source path wrong; run `sync` before unmount. |
| Windows “cannot run” / SmartScreen | Unblock properties; build with `-Console` to see errors; try older Python/PyInstaller for Win8. |
| No session on operator | `operator_host` / port; Windows firewall outbound; VM inbound **47001**; DNS. |
| **PLAY** returns error | Media filenames match `target.ini`; same folder as exes; codecs readable by OpenCV. |
| Hotkeys on server do nothing | Listener needs **GUI / X11** for `pynput`; use CLI `play` / `stop` or `--no-hotkeys`. |

---

## Project status: what is done vs what you might still add

### Already integrated (lab‑usable path)

- **Operator (server):** TCP listen, session registry, HELLO, line protocol, CLI (`list`, `use`, `send`, `play`, `stop`, `broadcast`, `kick`), optional **Ctrl+Alt+T** / **Ctrl+Alt+Q** hotkeys (`pynput`).
- **Target (client):** Outbound connect, reconnect with backoff, **PING / STATUS / PLAY / STOP**, subprocess media, cleanup on disconnect and Ctrl+C.
- **Media:** `cv2_hack` fullscreen loop, pygame audio, pycaw volume, optional **keyboard** lock on the player, PyInstaller path for **`cv2_hack.exe`** beside **`ControlChannelTarget.exe`**.
- **Deploy:** `deploy/server`, `deploy/client`, `pack-deploy.ps1`, `build-exe.ps1`, main **`deploy/README.md`**.

### Optional / not in repo (common “next steps” for a course or production)

| Item | Notes |
|------|--------|
| **TLS / authentication** | Protocol is plain TCP + text; no encryption or token in repo. |
| **Auto‑start operator on Linux** | No `systemd` unit in repo; you’d add a service file on the VM. |
| **Hardening** | `allowed_subnets` in `operator.ini`, firewall rules, least privilege. |
| **Codec / media** | Re‑encode video if OpenCV fails on target GPU/driver. |
| **Telemetry / logging** | Remote log shipping, Windows Event Log registration for the exe. |
| **Code signing** | Reduces SmartScreen warnings for unknown exes. |
| **Single “installer”** | MSI/Inno Setup to lay down files + Startup shortcut automatically. |
| **Automated tests** | CI that runs listener + connector against localhost. |

For a **typical class demo** (operator on VM, one Windows target, USB deploy, PLAY/STOP), the **core integration is already in place**; remaining work is mostly **polish, security hardening, and environment-specific** (BitLocker, old OS Python version, network ACLs).
