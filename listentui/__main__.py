#!/usr/bin/env python3
import sys

from listentui.app import run as run_app

if __package__ is None and not getattr(sys, "frozen", False):  # type: ignore
    # direct call of __main__.py
    import os.path

    path = os.path.realpath(os.path.abspath(__file__))
    sys.path.insert(0, os.path.dirname(os.path.dirname(path)))


def run():
    run_app()


if __name__ == "__main__":
    run_app()
