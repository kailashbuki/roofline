#!/bin/bash

APP_NAME="Inference News"
APP_DIR="$APP_NAME.app"
CONTENTS="$APP_DIR/Contents"
MACOS="$CONTENTS/MacOS"
RESOURCES="$CONTENTS/Resources"

# Clean old app
rm -rf "$APP_DIR"

# Create structure
mkdir -p "$MACOS" "$RESOURCES"

# Create launcher script
cat > "$MACOS/launch" << 'LAUNCH'
#!/bin/bash
cd "$(dirname "$0")/../Resources"
source .venv/bin/activate
python widget.py
LAUNCH
chmod +x "$MACOS/launch"

# Copy resources
cp -r .venv collectors database.py config.yaml collect_all.py relevance_scorer.py bedrock_classifier.py widget.py articles.db "$RESOURCES/"
cp icon.png icon_rounded.png "$RESOURCES/"
cp icon_rounded.png "$RESOURCES/icon.icns"

# Create Info.plist
cat > "$CONTENTS/Info.plist" << 'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleExecutable</key>
    <string>launch</string>
    <key>CFBundleIconFile</key>
    <string>icon.icns</string>
    <key>CFBundleIdentifier</key>
    <string>com.inference.news</string>
    <key>CFBundleName</key>
    <string>Inference News</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleShortVersionString</key>
    <string>1.0</string>
    <key>LSMinimumSystemVersion</key>
    <string>10.13</string>
</dict>
</plist>
PLIST

echo "App created: $APP_DIR"
