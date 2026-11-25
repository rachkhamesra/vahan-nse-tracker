#!/bin/sh
# Pulls registrations from the official VAHAN dashboard and pushes them to GitHub.
# Run by the launch agent that install.sh sets up (08:00 and 20:30, and at login). Safe to run by hand.
export PATH="/usr/bin:/bin:/usr/sbin:/sbin:$HOME/miniforge3/bin:/opt/homebrew/bin:/usr/local/bin"
REPO="${VAHAN_REPO:-$HOME/vahan-nse-tracker}"
LOG="$HOME/Library/Logs/vahan-nse-tracker.log"
mkdir -p "$HOME/Library/Logs"
{
  echo "=== $(date '+%Y-%m-%d %H:%M:%S')"
  cd "$REPO" || { echo "repo not found at $REPO"; exit 1; }
  git pull -q --rebase || { echo "git pull failed"; exit 1; }
  if /usr/bin/python3 pipeline/refresh.py portal && /usr/bin/python3 pipeline/refresh.py publish --only registrations; then
    git add data/registrations.json pipeline/data/registrations.json
    if git diff --cached --quiet; then
      echo "no change"
    else
      git commit -q -m "Registrations from VAHAN $(date -u '+%Y-%m-%d %H:%M') UTC"
      git push -q || { git pull -q --rebase && git push -q; } || echo "git push failed"
      echo "pushed"
    fi
  else
    echo "portal pull failed; leaving the previous data in place"
  fi
} >> "$LOG" 2>&1
