#!/usr/bin/env python3
"""Rewrite security chart image tags to verified multi-architecture digests."""

import json
import pathlib
import sys

root = pathlib.Path(__file__).resolve().parent
mapping = json.loads((root / "images.lock.json").read_text())
rendered = sys.stdin.read()
for source, pinned in mapping.items():
    rendered = rendered.replace(source, pinned)
sys.stdout.write(rendered)
