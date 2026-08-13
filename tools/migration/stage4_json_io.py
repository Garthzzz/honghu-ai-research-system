from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def read_json(path: Path) -> Any:
    """Read Stage 4 JSON using the cross-runtime UTF-8 contract.

    Windows PowerShell 5.1 historically writes a UTF-8 BOM for
    ``-Encoding UTF8`` while Python and PowerShell 7 normally do not.  Stage 4
    evidence may therefore contain either representation.  ``utf-8-sig``
    accepts both, removes only the UTF-8 BOM, and still rejects UTF-16 or an
    invalid byte stream instead of guessing another encoding.
    """

    return json.loads(path.read_text(encoding="utf-8-sig"))
