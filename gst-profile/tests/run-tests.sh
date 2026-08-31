#!/usr/bin/env bash
# Run the gst-profile unit suite. Integration tests self-skip when gst-launch-1.0 is absent.
cd "$(dirname "$0")/.." && exec python3 -m unittest discover -s tests -v "$@"
