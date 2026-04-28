#!/bin/bash
# Ensure ffmpeg is installed (survives container restarts)
if ! command -v ffmpeg &> /dev/null; then
    echo "Installing ffmpeg..."
    apt-get update -qq && apt-get install -y -qq ffmpeg > /dev/null 2>&1
    echo "ffmpeg installed: $(which ffmpeg)"
else
    echo "ffmpeg already installed: $(which ffmpeg)"
fi

# Ensure chunk storage dir exists
mkdir -p /var/video_chunks
echo "Setup complete"
