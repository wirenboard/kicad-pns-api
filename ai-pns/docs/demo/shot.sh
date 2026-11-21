#!/bin/bash
# shot.sh N OUT.png x0 y0 x1 y1 : screenshot of instance N's Xvfb (:9N), cropped to a board rectangle in mm.
# The pixel mapping below fits the demo board after the window was resized to 1920x1080 and "zoom to
# fit" (Home); measure two board corners in a full screenshot for any other board.
#   W=$(DISPLAY=:9N xdotool search --name "PCB Editor" | head -1); DISPLAY=:9N xdotool windowsize $W 1920 1080
#   DISPLAY=:9N xdotool mousemove 1000 1000 click 1 key Home
# The canvas repaints lazily after API edits: a mouse move over it forces the redraw before the capture.
export DISPLAY=:9$1
xdotool mousemove 1000 1000; sleep 0.4; xdotool mousemove 1012 992; sleep 1.2
T=$(mktemp --suffix .png); import -window root "$T"
px() { python3 -c "print(int(368 + ($1 - 100) * 27.93))"; }
py() { python3 -c "print(int(171 + ($1 - 100) * 27.86))"; }
X0=$(px $3); Y0=$(py $4); X1=$(px $5); Y1=$(py $6)
convert "$T" -crop $((X1 - X0))x$((Y1 - Y0))+$X0+$Y0 +repage -strip "$2"; rm -f "$T"
