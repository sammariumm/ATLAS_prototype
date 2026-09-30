#!/bin/bash
# Autostart wrapper for ATLAS-BC: rotates the display to portrait, then
# launches the kiosk app. Runs from the labwc session's autostart bridge
# (lxsession-xdg-autostart), so the compositor should already be up, but
# retry briefly in case an output isn't ready yet on a slow boot.
#
# Logs every attempt to ~/atlas-boot.log so boot-time failures (which can
# differ from an interactive shell run -- different PATH, no controlling
# terminal, etc.) leave a trail to inspect afterwards.

LOG=/home/raspi/atlas-boot.log
exec >>"$LOG" 2>&1

echo "=== launch-atlas-bc.sh started: $(date) ==="
echo "PATH=$PATH"
echo "whoami=$(whoami) WAYLAND_DISPLAY=$WAYLAND_DISPLAY XDG_RUNTIME_DIR=$XDG_RUNTIME_DIR"
command -v wlr-randr || echo "wlr-randr NOT FOUND on PATH"

OUTPUT="HDMI-A-2"
TRANSFORM="90"

for i in 1 2 3 4 5; do
    if wlr-randr --output "$OUTPUT" --transform "$TRANSFORM"; then
        echo "wlr-randr succeeded on attempt $i"
        break
    fi
    echo "wlr-randr attempt $i failed, retrying..."
    sleep 1
done

# Give the compositor time to settle the new output geometry before handing
# it a new fullscreen client. Confirmed on-device: 2s was not enough (the
# app hung with no window ever appearing), 10s was. Using 12s for margin.
sleep 12

BIN=/home/raspi/app_prototype/build/linux/arm64/release/bundle/atlas_bc
if [ ! -x "$BIN" ]; then
    echo "ERROR: $BIN not found or not executable"
    exit 1
fi

echo "Launching $BIN"
exec "$BIN"
