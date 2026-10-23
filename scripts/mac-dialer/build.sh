#!/bin/zsh
# Builds Linphone Dialer and installs it, replacing any earlier copy.
#   zsh build.sh [destination.app]      (default: /Applications/Linphone Dialer.app)
# Needs the Xcode command line tools (swiftc). Open the installed app once to make it the
# Mac's app for phone links.
set -euo pipefail

SRC=${0:A:h}
DEST=${1:-"/Applications/Linphone Dialer.app"}
WORK=$(mktemp -d)
APP="$WORK/Linphone Dialer.app"
trap 'rm -rf "$WORK"' EXIT

mkdir -p "$APP/Contents/MacOS"
cp "$SRC/Info.plist" "$APP/Contents/Info.plist"
swiftc -O -swift-version 5 "$SRC/main.swift" -o "$APP/Contents/MacOS/LinphoneDialer"
codesign --force --sign - "$APP"

rm -rf "$DEST"
mv "$APP" "$DEST"
echo "Installed $DEST. Open it once to make phone links dial in Linphone."
