#!/bin/bash
# Autostart wrapper for ATLAS-BC: rotates the display to portrait, then
# launches the kiosk app. Runs from the labwc session's autostart script, so
# the compositor is already up, but retry briefly in case an output isn't
# ready yet on a slow boot.

OUTPUT="HDMI-A-2"
TRANSFORM="90"

for i in 1 2 3 4 5; do
    if wlr-randr --output "$OUTPUT" --transform "$TRANSFORM"; then
        break
    fi
    sleep 1
done

# Give the compositor a moment to settle the new output geometry before
# handing it a new fullscreen client -- launching immediately after a
# transform change was observed to hang with the window never appearing.
sleep 2

exec /home/raspi/app_prototype/build/linux/arm64/release/bundle/atlas_bc
