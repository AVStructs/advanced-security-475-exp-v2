# Start to finish: Linux VM + USB + Windows 8

Use this as a single checklist. Times and paths are examples—adjust to your course VM name, drive letters, and folders.

---

## Phase A — Prepare on your main Windows PC (build / pack)

1. **Clone or open** the project repo on a Windows machine with Python (used to build the `.exe` and to hold copies of `server/` and client files).

2. **Refresh deploy folders** (optional but keeps copies current):

   ```powershell
   cd "C:\path\to\Advanced security 475 exp v2"
   .\deploy\pack-deploy.ps1
   ```

3. **Build the Windows 8 target executables** (skip if you will run Python on the laptop instead):

   ```powershell
   .\deploy\client\build-exe.ps1
   ```

   Output: **`deploy\client\target-exe-bundle\`** containing `ControlChannelTarget.exe`, `cv2_hack.exe`, and a flat **`target.ini`**.

4. **Put media** in that same folder: e.g. `giraffe_clipped.mp4`, `giraffe_clipped_audio.mp3` (names must match **`target.ini`** or edit the INI).

5. **Set operator address** in the bundle’s **`target.ini`**: **`operator_host`** = your **Linux VM** hostname or IP (e.g. `cs448lnx132.gcc.edu` or `10.x.x.x`). Save.

6. **Copy onto the USB stick** (data partition, not the live-USB system partition):

   - The whole **`deploy\server`** folder (for the VM), and  
   - The whole **`target-exe-bundle`** folder (for Windows 8),  
   **or** zip them on the stick for fewer copy steps.

---

## Phase B — Linux VM (operator / server)

7. **SSH or log into** the Linux VM.

8. **Copy `server/`** from the USB (or `scp` from your PC) to the VM, e.g. `~/control-channel-server/`.

9. **Python venv + deps:**

   ```bash
   cd ~/control-channel-server
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

10. **Firewall:** allow **TCP inbound 47001** on the VM (ufw, cloud security group, or campus instructions).

11. **Start the listener** and leave it running:

    ```bash
    python listener.py
    ```

    If you have **no GUI** (SSH only), hotkeys will not work—use:

    ```bash
    python listener.py --no-hotkeys
    ```

12. **Confirm the port** is listening (optional): from the VM, `ss -tlnp | grep 47001` or similar.

---

## Phase C — Windows 8 laptop (target) via Linux USB

13. **Boot the Windows 8 laptop from the Linux USB** (live environment).

14. **Find the internal Windows partition** (NTFS), e.g. `lsblk -f` / `sudo fdisk -l`.

15. **Mount it read-write**, e.g.:

    ```bash
    sudo mkdir -p /mnt/win
    sudo mount -t ntfs-3g /dev/sdXY /mnt/win
    ```

    (Replace `/dev/sdXY` with your Windows partition. BitLocker must be unlocked if used.)

16. **Copy the bundle** onto the SSD (same folder for all files), e.g.:

    ```bash
    sudo mkdir -p /mnt/win/ControlChannel
    sudo cp -a /run/media/youruser/USBSTICK/target-exe-bundle/. /mnt/win/ControlChannel/
    ```

    Adjust the USB path to where **`target-exe-bundle`** actually is on the stick.

17. **`sync`**, then **`sudo umount /mnt/win`**, reboot, **remove the USB**, boot **Windows 8 from the SSD**.

---

## Phase D — First boot on Windows 8

18. Open **`C:\ControlChannel\`** (or whatever path you used). Confirm **both `.exe`**, **`target.ini`**, and media files are there.

19. **Unblock** (if Windows shows it): right‑click each **`.exe`** → Properties → **Unblock** → OK.

20. **Startup (optional):** `Win+R` → `shell:startup` → new **Shortcut** to `C:\ControlChannel\ControlChannelTarget.exe` (set “Start in” to that folder if needed).

21. **Network:** Windows 8 must reach the VM on **TCP 47001** (same lab network / VPN per your school).

22. **Run once manually** to test: double‑click **`ControlChannelTarget.exe`** (or run from cmd). On the VM listener you should see activity; in the operator CLI type **`list`** and you should see a session.

---

## Phase E — Operate

23. On the **VM**, in the `listener.py` terminal:

    ```text
    list
    use 1
    ping
    ```

    Expect **`PONG`**.

24. **`play`** (or Ctrl+Alt+T if you did **not** use `--no-hotkeys` on a machine with a desktop) starts video on Windows 8. **`stop`** or Ctrl+Alt+Q stops it.

---

## If you skip the `.exe` (Python only on Windows 8)

- Copy **`deploy/client`** (or full repo) to the laptop by any means (USB, network).
- Install Python 3.8 on Windows 8 if needed, `venv`, `pip install -r requirements.txt`.
- Edit **`client\target\target.ini`** → **`operator_host`** = VM.
- Run: **`python client\target\connector.py`** from the folder that contains **`client`** (paths as in README).

---

## Quick failure checks

| Problem | Check |
|--------|--------|
| No session on `list` | VM listener running? `operator_host` / DNS? Windows 8 outbound firewall? VM inbound **47001**? |
| `PLAY` errors | Media filenames and **`project_root`** in INI; flat exe folder uses **`project_root = .`** in bundled `target.ini`. |
| Exe won’t run on Win8 | Build with **Python 3.8** + compatible PyInstaller on the build PC. |

More detail: **[README.md](README.md)** and **[EXE-DEPLOYMENT-GUIDE.md](EXE-DEPLOYMENT-GUIDE.md)**.
