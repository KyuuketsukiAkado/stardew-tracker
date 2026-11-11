"""Pin the console language so tests do not depend on the language of the machine they run on."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stardew_tracker import i18n


def pin_english() -> None:
    """Use as ``setUpModule``: console output and error texts become English."""

    i18n.set_language("en")


def unpin() -> None:
    """Use as ``tearDownModule``: back to automatic detection."""

    i18n.set_language(None)
