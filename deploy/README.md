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
`Exec=` path in `atlas-bc.desktop` below to match.

## 3. Auto-start the Python backend on boot

```bash
sudo cp deploy/atlas-backend.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now atlas-backend.service
sudo systemctl status atlas-backend.service   # confirm it's running and picked Picamera2
```

Logs: `journalctl -u atlas-backend.service -f`

The service file assumes user `raspi` and project path `/home/raspi/app_prototype`
— edit `deploy/atlas-backend.service` first if yours differ.

## 4. Auto-start the app when the desktop session loads

```bash
mkdir -p ~/.config/autostart
cp deploy/atlas-bc.desktop ~/.config/autostart/
```

Make sure the Pi is set to boot to desktop with auto-login
(`sudo raspi-config` → System Options → Boot / Auto Login → Desktop
Autologin) so this actually launches without anyone signing in manually.

## 5. Test it

```bash
sudo reboot
```

The app should come up full-screen, borderless, with the backend already
running. To get a normal decorated window back for debugging instead of
kiosk fullscreen:

```bash
ATLAS_BC_WINDOWED=1 ./build/linux/arm64/release/bundle/atlas_bc
```
