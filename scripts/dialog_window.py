#!/usr/bin/env python3
from __future__ import annotations

from _bootstrap import add_repo_root

ROOT_DIR = add_repo_root(__file__)

from resp_lanu.gui import launch_dialog_window

if __name__ == "__main__":
    launch_dialog_window(ROOT_DIR)
