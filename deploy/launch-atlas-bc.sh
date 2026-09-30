#!/bin/bash
# Autostart wrapper for ATLAS-BC: rotates the display to portrait, then
# launches the kiosk app. Runs as an XDG autostart entry (atlas-bc.desktop),
# so the Wayfire/Wayland session is already up, but retry briefly in case
# the compositor isn't quite ready yet on a slow boot.

OUTPUT="HDMI-A-2"
TRANSFORM="90"

for i in 1 2 3 4 5; do
    if wlr-randr --output "$OUTPUT" --transform "$TRANSFORM"; then
        break
    fi
    sleep 1
done

exec /home/raspi/app_prototype/build/linux/arm64/release/bundle/atlas_bc
