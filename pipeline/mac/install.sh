#!/bin/sh
# One-time setup of the scheduled job on a Mac. It keeps its own clone outside Desktop and Documents, because
# macOS blocks background jobs from reading those folders.
set -e
REPO="$HOME/vahan-nse-tracker"
LABEL="com.vahan-nse-tracker.refresh"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
GH="${GH:-$(command -v gh || echo "$HOME/miniforge3/bin/gh")}"

if [ ! -d "$REPO/.git" ]; then
  git clone https://github.com/rachkhamesra/vahan-nse-tracker.git "$REPO"
fi
cd "$REPO"
# the global helper may live in a protected folder; use a copy of gh the background job can run
git config --local --replace-all credential.helper ""
git config --local --add credential.helper "!$GH auth git-credential"
chmod +x pipeline/mac/run.sh

mkdir -p "$HOME/Library/LaunchAgents" "$HOME/Library/Logs"
cat > "$PLIST" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key><array><string>/bin/sh</string><string>$REPO/pipeline/mac/run.sh</string></array>
  <key>RunAtLoad</key><true/>
  <key>StartCalendarInterval</key><array>
    <dict><key>Hour</key><integer>8</integer><key>Minute</key><integer>0</integer></dict>
    <dict><key>Hour</key><integer>20</integer><key>Minute</key><integer>30</integer></dict>
  </array>
  <key>StandardOutPath</key><string>$HOME/Library/Logs/vahan-nse-tracker.launchd.log</string>
  <key>StandardErrorPath</key><string>$HOME/Library/Logs/vahan-nse-tracker.launchd.log</string>
</dict></plist>
PL
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "Installed. Runs at 08:00 and 20:30 and at login. Log: ~/Library/Logs/vahan-nse-tracker.log"
