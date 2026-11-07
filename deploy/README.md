# Deploying ATLAS-BC on the Raspberry Pi

These steps turn the dev checkout into a real installed app that starts on
boot instead of something you launch by hand with `flutter run` / `python3
app.py`. Run all of this **on the Pi**, from `~/app_prototype`.

## 1. One-time build setup

```bash
sudo apt update
sudo apt install -y clang cmake ninja-build pkg-config libgtk-3-dev
flutter config --enable-linux-desktop
flutter pub get
```

## 2. Build the release binary

```bash
flutter build linux --release
```

This produces a standalone bundle at `build/linux/<arch>/release/bundle/`
(`<arch>` is `arm64` on 64-bit Raspberry Pi OS). The `atlas_bc` executable
inside that folder, together with the rest of the bundle, is the actual
application — copy/move the whole `bundle/` folder wherever you want to run
it from, but keep its contents together.

If your build lands in a differently-named `<arch>` folder, update the
`exec` path at the bottom of `launch-atlas-bc.sh` to match.

## 3. Install the Python backend's packages

The backend (`app.py`) now also converts softcopies to PNG (`atlas_convert.py`) and prepares film photos and
images for the AI (`atlas_preprocess.py`). Keep those two files in the same folder as `app.py`. They need a few
more Python packages. The service runs the system Python, so install them with apt:

```bash
sudo apt install -y python3-flask python3-numpy python3-opencv python3-pydicom python3-picamera2
```

Only if you will import **compressed** DICOM files (JPEG / JPEG-LS / JPEG 2000 transfer syntaxes — uncompressed
DICOM works without this), add the decoders:

```bash
sudo pip3 install --break-system-packages pylibjpeg pylibjpeg-libjpeg pylibjpeg-openjpeg
```

(`requirements.txt` lists the same packages for a development PC: `pip install -r requirements.txt`.)

### 3b. The AI: PyTorch and the model files

The backend runs the trained ensemble (`atlas_models.py`): 15 networks, 5 folds each of ResNet50, DenseNet121 and
InceptionV3, combined by the weighted average from the thesis. It needs PyTorch and the model folder.

```bash
sudo pip3 install --break-system-packages torch torchvision     # 64-bit Raspberry Pi OS: CPU wheels from PyPI
python3 -c "import torch, torchvision; print(torch.__version__, torchvision.__version__)"   # must print versions
```

Copy the model folder next to `app.py` (it is about 1.2 GB and is not in git). It must look like this:

```
app_prototype/models/ensemble_config.json            (= v3_ensemble/final_config.json)
app_prototype/models/resnet50_in/fold0_best.pth ... fold4_best.pth
app_prototype/models/densenet121_in/fold0_best.pth ... fold4_best.pth
app_prototype/models/inception_v3_in/fold0_best.pth ... fold4_best.pth
```

```bash
# from the PC that holds the folder (the .pth files of Google Drive's ATLAS_Models/final/<run>/foldK_best.pth):
scp -r models raspi@<pi-address>:app_prototype/
```

Only the `fold*_best.pth` files are needed (not `fold*_last.pth`, `*_oof.npz`, ...). If the folder is somewhere else,
set `ATLAS_MODELS_DIR`. After the backend starts, `curl localhost:5000/health` shows `"models": "real"` and, under `ai`,
whether the 15 networks are loaded or why not. Loading takes a while after boot and runs in the background while the
operator captures the views.

**One analysis runs all 15 networks on 4 images of 1280 x 800, about 8.6 TFLOPs. Time it on the Pi** (`ai.last_analysis_seconds`
in `/health` after an analysis). On a 2-vCPU x86 server one network takes about 4 to 5 seconds; a Raspberry Pi 4 is
several times slower. If it is too slow for a kiosk, the options are fewer folds, a smaller `ATLAS_VIEW_CHUNK` if it
runs out of memory, or exporting the networks to ONNX / int8.

Check the install without the camera:

```bash
python3 -m pytest backend_tests      # needs: sudo apt install -y python3-pytest
```

The tests that run the real ensemble skip themselves when PyTorch or the model files are missing.

## 4. Auto-start the Python backend on boot

```bash
sudo cp deploy/atlas-backend.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now atlas-backend.service
sudo systemctl status atlas-backend.service   # confirm it's running and picked Picamera2
```

Logs: `journalctl -u atlas-backend.service -f`

The service keeps the camera open, so to run `python3 app.py` by hand (to see its output) stop the service first with
`sudo systemctl stop atlas-backend.service`, otherwise the second copy cannot open the camera.

The service file assumes user `raspi` and project path `/home/raspi/app_prototype`
— edit `deploy/atlas-backend.service` first if yours differ.

To change a backend setting (see "Settings" below) without editing the file:

```bash
sudo systemctl edit atlas-backend.service
# in the editor that opens, add for example:
#   [Service]
#   Environment=ATLAS_CAMERA_ROTATION=270
sudo systemctl restart atlas-backend.service
```

## 5. Auto-start the app (and auto-rotate to portrait) when the desktop loads

`launch-atlas-bc.sh` rotates the display to portrait via `wlr-randr` (Wayfire
default on Raspberry Pi OS) and then launches the app. It assumes the screen
is on `HDMI-A-2` with a `90` transform, matching this setup's current
`wlr-randr --output HDMI-A-2 --transform 90` — if you move the cable to the
other HDMI port or the orientation comes out wrong, edit `OUTPUT`/`TRANSFORM`
at the top of the script (run `wlr-randr` with no arguments to list outputs).

```bash
chmod +x deploy/launch-atlas-bc.sh
mkdir -p ~/.config/autostart
cp deploy/atlas-bc.desktop ~/.config/autostart/
```

Make sure the Pi is set to boot to desktop with auto-login
(`sudo raspi-config` → System Options → Boot / Auto Login → Desktop
Autologin) so this actually launches without anyone signing in manually.

## 6. Test it

```bash
sudo reboot
```

The app should come up in portrait, full-screen, borderless, with the
backend already running.

## Using the two input modes

Every scan is a two-sided exam of up to four views: **Left CC, Left MLO, Right CC, Right MLO**.

1. On the **Camera** tab choose the image source first: **SOFTCOPY** (a digital file) or **CAMERA** (a film on the
   lightbox). You can change the source at any time ("Change source"), even between views.
2. Work through the four views. For each one press **CAPTURE** (camera) or **SELECT FILE** (softcopy). If a view does
   not exist (for example only one breast was imaged) press **NOT AVAILABLE** for it. At least one view is needed.
   Tap a view in the progress row to redo it.
3. When all four views are set, press **ANALYZE**. The results, the per-breast results and the PDF report then appear
   on the Results and Export tabs.

If only one view of a breast exists, the AI is given a copy of that breast's other view in its place and the app says
so, because that result is less reliable. A breast with no view at all gets no result ("Not available").

### Softcopy (digital files)

**On the kiosk the operator plugs in a USB stick.** Nobody can copy files into a folder, so **SELECT FILE** lists
the images on every USB stick that is plugged into the Pi (looking up to three folders deep) and the operator taps
the one for the view. The list also shows the files in the **inbox folder**, `~/atlas_inbox` of the backend's user
(setting `ATLAS_INBOX_DIR`), for anything that does put files there (the serial transfer, `scp`, ...).

- A stick is found when it is *mounted* below `/media` or `/run/media` (setting `ATLAS_MEDIA_ROOTS`, folders
  separated by `:`). Raspberry Pi OS mounts a stick at `/media/<user>/<label>` by itself while the desktop session
  is running (which the kiosk is). FAT32 always works; exFAT, NTFS and ext4 sticks need the matching driver.
- On a stick only image files are listed (DICOM, PNG, JPEG, BMP, TIFF, GIF, WebP, JPEG 2000; DICOM files without an
  ending are recognised from their content). Documents, hidden files and `System Volume Information` are left out.
- The list is read when **SELECT FILE** is pressed. If the stick was plugged in after that, press **REFRESH**.
- A picked file is converted to a PNG and **copied to the Pi**, so the stick can be pulled out afterwards.
  The stick itself is only read, never written.
- Check it on the Pi: plug in a stick, then `curl localhost:5000/health` must list it under `usb_volumes`
  (and `ls /media/*` shows it).

If the stick does **not** appear under `/media/<user>/` (this Pi's desktop does not auto-mount), this udev rule is
a starting point. It is *not tested*: it mounts every USB partition read-only at `/media/atlas-usb`, which the backend
finds like any other stick (only one stick at a time):

```bash
sudo tee /etc/udev/rules.d/99-atlas-usb.rules <<'RULE'
ACTION=="add", SUBSYSTEM=="block", SUBSYSTEMS=="usb", ENV{DEVTYPE}=="partition", ENV{ID_FS_USAGE}=="filesystem", RUN+="/usr/bin/systemd-mount --no-block --collect -o ro,nosuid,nodev,noexec $devnode /media/atlas-usb"
RULE
sudo udevadm control --reload-rules
```

Files with the endings `.part`, `.tmp`, `.partial` and hidden files are not listed, so a transfer that is still running
is never picked up half-finished; have the sender write to a temporary name and rename it when done.

When a file is picked it is turned into a PNG first (what the AI sees is always a PNG):

| Source file | What happens |
|---|---|
| DICOM | converted to PNG (16-bit by default, rescale slope/intercept applied, MONOCHROME1 inverted) |
| PNG | stays a PNG, copied byte for byte |
| anything else (JPEG, BMP, TIFF, GIF, WebP, JPEG 2000) | converted to PNG |

The file type is recognised from its content, not its extension. The converted PNGs are stored with the scan in
`~/atlas_scans_test/<scan id>/<Left|Right>/`.

### Camera (film on the lightbox)

* **Which camera.** On the Pi the CSI camera is used (Picamera2). On a PC, or a Pi without that camera, the backend
  looks for a **USB** webcam (found through `/sys/class/video4linux`; the Pi's own internal `/dev/video*` nodes for the
  video codec and ISP are not cameras and are never touched) and uses the first one that really delivers a picture. A
  camera that does not answer within 6 seconds is given up, so the backend always starts. `ATLAS_CAMERA_INDEX` forces
  one, e.g. `2` or `/dev/video2`. `ATLAS_CAMERA=none` switches the camera **off** (softcopy only), so do **not** set it
  when you want the live view.
* **One program at a time.** A camera can be opened by only one program. On the Pi the backend already runs as
  `atlas-backend.service` from boot and owns the camera, so starting a second copy by hand (`python3 app.py`) fails with
  *Failed to acquire camera: Device or resource busy*. To run it by hand, stop the service first
  (`sudo systemctl stop atlas-backend.service`), and start it again afterwards
  (`sudo systemctl start atlas-backend.service`). To see what holds the camera: `pgrep -af "app.py|rpicam|libcamera"`.
  After copying new files to the Pi, `sudo systemctl restart atlas-backend.service` makes the service use them.
* **"Camera frontend has timed out".** libcamera finds the sensor (`Adding camera ... imx219`) but no picture ever
  arrives. This is hardware: the ribbon cable is not fully seated at one end, is damaged, or is too long; a weak power
  supply can do it too (`vcgencmd get_throttled` should print `0x0`). `rpicam-hello -t 5000` fails the same way when it
  is the hardware, whatever the backend does. Power the Pi off, reseat the cable at both ends (CAMERA port, not
  DISPLAY), or try another cable. The backend still starts in this state and the live view says *CAMERA ERROR*; it
  works again by itself once pictures arrive (no restart needed for the live view; restart the service to also get the
  fixed exposure).
* **No live view?** The stream tells you why in words: *CAMERA OFF* (switched off with `ATLAS_CAMERA=none`),
  *NO CAMERA FOUND* (nothing opened; the text says why: in use by another program, no USB camera, ...) or *CAMERA ERROR*
  (it opened but stopped delivering a picture). The same is in `curl localhost:5000/health` under `camera_status`. To see
  the stream without the app, open `http://127.0.0.1:5000/video_feed` in a browser. On Linux check `ls -l /dev/video*`
  (USB cameras) and that your user is in the `video` group.
* The picture is rotated by `ATLAS_CAMERA_ROTATION` degrees counter-clockwise (default **90**) before anything else
  sees it, so the live preview and the saved photo have the same orientation. If the film comes out sideways or
  upside down, set the value to `270` (or `0` / `180`).
* **Auto-exposure is off.** At start-up the backend lets the camera settle once on the scene and then freezes the
  exposure time and gain (so **start the backend with the lightbox on**). To use fixed values instead set
  `ATLAS_EXPOSURE_US` and `ATLAS_ANALOGUE_GAIN`. Set the exposure so the empty lightbox is bright but **not fully
  saturated** (the app warns when parts of the film are over-exposed; `curl localhost:5000/health` shows the values in
  use, and the debug pictures show the result).
* The photo goes through a film front end (`film_to_digital` in `atlas_preprocess.py`): it finds the film, masks the
  lightbox, measures the film's black level and outputs an image whose background is exactly black, like a digital
  mammogram, which is what the AI's preprocessing (`process_image`) expects. The AI's preprocessing itself is the
  same code as in the training notebook and is unchanged.
* A capture in which no breast tissue is found is rejected with an explanation (set `ATLAS_REQUIRE_TISSUE=0` to
  accept it anyway).

**Calibrate it with real films before trusting it** (this part was developed on synthetic photos only):

1. Photograph a few films. For every capture the backend saves, in `~/atlas_scans_test/<scan id>/`: the untouched
   photo (`<Side>/..._camera.png`), the image given to the AI (`<Side>/<...>.png`) and a debug picture
   (`debug/..._film.jpg`) that shows what was detected: the lightbox, the film outline and the tissue.
2. Compare the debug picture with the film. The warnings shown in the app explain the usual problems (film not
   found, lightbox saturated, tissue touching the edge, ...).
3. If the film outline or the tissue mask is off, adjust `ATLAS_FILM_*` (below). If the film is only part of the
   picture, `ATLAS_FILM_ROI=x,y,w,h` restricts the search to that rectangle of the (rotated) camera frame.
4. Compare the AI's classification of a film photographed this way with the same case as a digital image: the
   photograph path should agree with the digital one before it is used for anything that matters.

### Settings (environment variables of the backend)

| Variable | Default | Meaning |
|---|---|---|
| `ATLAS_CAMERA` | `auto` | `none` = do not open a camera (softcopy-only machine; the live view then says CAMERA OFF) |
| `ATLAS_CAMERA_INDEX` | first that works | USB webcam to use: a number or a device path such as `/dev/video2` |
| `ATLAS_CAMERA_SIZE` | `1640x1232` | camera resolution (the Camera Module 2's full-field 4:3 mode) |
| `ATLAS_CAMERA_ROTATION` | `90` | degrees counter-clockwise: `0`, `90`, `180`, `270` |
| `ATLAS_EXPOSURE_US` | `0` | exposure time in microseconds; `0` = freeze what auto-exposure chose at start-up |
| `ATLAS_ANALOGUE_GAIN` | `0` | sensor gain; `0` = freeze the start-up value |
| `ATLAS_LOCK_AWB` | `0` | `1` = also freeze the white balance |
| `ATLAS_OPENCV_EXPOSURE` | – | USB webcam only (development): exposure value for OpenCV |
| `ATLAS_CAPTURE_AVG` | `4` | frames averaged per photograph (less sensor noise) |
| `ATLAS_REQUIRE_TISSUE` | `1` | `0` = accept camera shots in which no breast is found |
| `ATLAS_SAVE_DEBUG` | `1` | save the debug pictures and the AI's input images with each scan |
| `ATLAS_SCAN_DIR` | `~/atlas_scans_test` | where scans are stored |
| `ATLAS_INBOX_DIR` | `~/atlas_inbox` | an extra folder softcopy files are picked from (USB sticks are always listed too) |
| `ATLAS_MEDIA_ROOTS` | `/media:/run/media` | folders below which a mounted USB stick is looked for (separate with `:`) |
| `ATLAS_DICOM_PNG_BITS` | `16` | bit depth of PNGs converted from DICOM: `8` or `16` |
| `ATLAS_DICOM_VOI` | `0` | `1` = apply the window / VOI LUT from the DICOM header |
| `ATLAS_FILM_ROI` | – | `x,y,w,h`: only look for the film inside this rectangle |
| `ATLAS_FILM_LIGHTBOX_REL` | `0.70` | the lightbox and clear film count as bright above this fraction of the lightbox level |
| `ATLAS_FILM_MARGIN` | `0.006` | grow the lightbox mask by this fraction of the frame, to remove the film's bright rim |
| `ATLAS_FILM_INSET` | `0.008` | shrink the film by this fraction of its short side, to remove the cut edge |
| `ATLAS_FILM_BLACK_K` | `4.0` | tissue = brighter than the film's black level + this many noise units |

`curl localhost:5000/health` shows the camera, rotation, exposure, model status (`mock` / `real`) and folders in use.

### The AI

`run_models()` in `app.py` calls `atlas_models.run_ensemble`. For every analysis the backend

1. preprocesses each view exactly like the training notebook (`process_image`: crop to the breast, CLAHE, chest wall on
   the left, fit onto a 1280 x 800 black canvas) and fills a missing view from the other view of the same breast, as
   `predict_exam_files` does,
2. runs the 15 networks (mean over the 5 folds of each architecture, then the weighted average
   0.449 ResNet50 / 0.198 DenseNet121 / 0.353 InceptionV3 from `ensemble_config.json`),
3. reports for each breast the most probable of the five BI-RADS classes (`decide: "five"`) with its probability as
   the confidence; the combined result is the worse breast.

If PyTorch or the model files are missing the analysis fails with a message saying what is missing; it never
substitutes random numbers. `ATLAS_MOCK_MODELS=1` selects the old random placeholder (every result labelled
"MOCK RESULT"), for developing the app on a PC without PyTorch or the model files.

| Variable | Default | Meaning |
|---|---|---|
| `ATLAS_MODELS_DIR` | `<app folder>/models` | where `ensemble_config.json` and the three architecture folders are |
| `ATLAS_TORCH_THREADS` | all cores | CPU threads PyTorch may use |
| `ATLAS_VIEW_CHUNK` | `4` | views pushed through a network at once (`1` to `4`); lower uses less RAM, same result |
| `ATLAS_KEEP_MODELS` | `1` | `1` = keep all 15 networks in RAM (about 1.2 GB, fast); `0` = load each one when needed (slow, small RAM) |
| `ATLAS_MOCK_MODELS` | `0` | `1` = random placeholder instead of the networks (development only) |

## Getting out of kiosk mode (to update the codebase, debug, etc.)

- **Keyboard attached to the Pi**: press **Ctrl+Alt+Q**. This quits the app
  immediately — it's handled at the native window level before Flutter sees
  the keypress, so it works even if the UI has frozen. You'll land back on
  the desktop, where you can open a terminal, `git pull`, rebuild
  (`flutter build linux --release`), and either re-launch
  `launch-atlas-bc.sh` manually or just reboot.
- **No keyboard / remote only**: SSH into the Pi and run `pkill atlas_bc`
  (or `sudo systemctl stop atlas-backend.service` if you also need the
  backend down). Since the app isn't managed by systemd itself, killing the
  process is enough — it won't auto-relaunch until the next login/reboot.
- To get a normal decorated window back for debugging instead of kiosk
  fullscreen, bypass the autostart entry and run the binary directly with:

  ```bash
  ATLAS_BC_WINDOWED=1 ./build/linux/arm64/release/bundle/atlas_bc
  ```
