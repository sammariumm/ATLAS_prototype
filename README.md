# ATLAS-BC App Prototype (Raspberry Pi)

Flutter client for the **ATLAS-BC** thesis edge node: bilateral mammography-style capture using the Pi camera module, physician review of combined AI output, PDF generation, and optional email delivery.

This branch (`sam/raspi-implementation`) targets **Linux on Raspberry Pi** rather than a Windows/Python Flask capture stack.

## Architecture

```text
┌──────────────────────────────────────────────────────────────┐
│  Raspberry Pi                                                 │
│  ┌─────────────────┐    MJPEG :8080    ┌──────────────────┐  │
│  │ rpicam-vid /    │ ─────────────────►│ Flutter UI       │  │
│  │ mjpg streamer   │                   │ (camera_panel)   │  │
│  └─────────────────┘                   └────────┬─────────┘  │
│                                                    │ capture   │
│  ┌─────────────────┐   rpicam-still (1920×1080)  │           │
│  │ Camera module   │ ◄────────────────────────────┘           │
│  └─────────────────┘                                          │
│         │ saves JPG under ./scans/<SCAN-ID>/                  │
└─────────┼────────────────────────────────────────────────────┘
          │
          ▼
   Results → Export (PDF + Gmail SMTP via backend_service.dart)
```

| Component | Path | Role |
|-----------|------|------|
| App shell | `lib/main.dart` | Tab navigation, scan session state, bilateral AI summary |
| Capture UI | `lib/panels/camera_panel.dart` | Side/view picker, MJPEG preview, `rpicam-still` capture |
| Review | `lib/panels/results_panel.dart` | Thumbnails, combined AI, accurate/inaccurate submission |
| Export | `lib/panels/export_panel.dart` | Left/right/combined PDF, email |
| Integrations | `lib/services/backend_service.dart` | DB/blockchain stubs, Gmail SMTP |

## Prerequisites

- Raspberry Pi OS (64-bit recommended) with **libcamera** tools (`rpicam-still`, `rpicam-vid`)
- Flutter SDK for Linux ARM (or cross-build pipeline your team uses)
- Pi camera connected and enabled (`raspi-config`)
- Network access for Gmail SMTP if using email export

## Camera setup

The app expects **two cooperating processes**:

1. **MJPEG preview** on `http://localhost:8080` while the user frames the shot.  
   Example (adjust resolution/rotation for your mount):

   ```bash
   rpicam-vid -t 0 --codec mjpeg -n -o - | \
     mjpg_streamer -i -
   ```

   If you use another MJPEG server, update `mjpegStreamUrl` in `lib/panels/camera_panel.dart`.

2. **Still capture** when the user taps **SNAP IMAGE**. The UI hides the MJPEG widget for ~1s so the sensor is free, then runs:

   ```bash
   rpicam-still -o <path> -t 1000 --nopreview --width 1920 --height 1080
   ```

   Images are stored under `./scans/<SCAN-ID>/` relative to the Flutter process working directory.

## Run the Flutter app

```bash
flutter pub get
flutter run -d linux
```

The UI is framed at 480×800 for kiosk demos; remove the `SizedBox` wrapper in `main.dart` for full-screen kiosk mode.

## User workflow

1. **Camera** — Select left/right and CC/MLO, open live stream, capture both sides.
2. **Results** — Review combined BI-RADS summary; mark accurate (blockchain stub) or inaccurate; submit (DB stub).
3. **Export** — Enter optional physician name and recipient email; generate PDF and send.

The app bar **New patient** button clears the current session.

## Configuration

| Setting | Location |
|---------|----------|
| MJPEG URL | `CameraPanel.mjpegStreamUrl` in `camera_panel.dart` |
| Gmail sender / app password | `BackendService` in `backend_service.dart` |
| Mock per-capture AI labels | `_executeCapture` in `camera_panel.dart` |

Do not commit real Gmail app passwords to public repositories.

## Development on Windows/macOS

`rpicam-still` and the MJPEG stream are Pi-specific. You can still run `flutter analyze` and widget tests on a dev machine; capture will fail without the Pi binaries.

```bash
flutter analyze lib test
flutter test
```

## Troubleshooting

| Symptom | Likely cause |
|---------|----------------|
| “Waiting for MJPEG stream on :8080” | Preview server not running or wrong URL |
| Capture fails immediately | `rpicam-still` missing, camera busy, or permissions |
| Black preview after capture | Normal briefly while still capture runs; stream restarts when MJPEG widget rebuilds |
| Email fails | Invalid app password, blocked SMTP, or missing PDF path |

## License

Thesis / research prototype — set licensing per your institution.
