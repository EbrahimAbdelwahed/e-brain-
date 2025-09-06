from __future__ import annotations

import subprocess
from typing import Optional

from ...util.logging import get_logger


logger = get_logger(__name__)


def encode_doi_for_path(doi: str) -> str:
    """Encode DOI for IPFS path components.

    Rules: lowercase the entire string; encode spaces as %20 and '/' as %2F.
    """
    if doi is None:
        return ""
    s = str(doi).strip().lower()
    # Encode precise characters per contract
    s = s.replace(" ", "%20").replace("/", "%2F")
    return s


def pin_dataset(base: str = "/ipns/libstc.cc/dois") -> None:
    """Run `ipfs pin add` for the dataset base path.

    Logs success/failure and does not raise to avoid blocking discovery.
    """
    try:
        proc = subprocess.run(
            ["ipfs", "pin", "add", base],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode == 0:
            logger.info("ipfs_pin_success", extra={"base": base, "out": proc.stdout.strip()})
        else:
            logger.error(
                "ipfs_pin_failed",
                extra={"base": base, "code": proc.returncode, "err": proc.stderr.strip()},
            )
    except Exception as e:
        logger.error("ipfs_pin_exception", extra={"base": base, "error": str(e)})


def try_fetch_content(doi: str) -> Optional[str]:
    """Stub: to be implemented in M2 using `ipfs cat` over configured layout.

    Returns None to signal no content available.
    """
    return None

