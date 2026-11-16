"""The only place that runs ``nvidia-smi``: fixed argv, no shell, bounded by a timeout.

Callers pass field names from module constants. No value from the backend, a buyer or any
other external source is ever interpolated into the argument list.
"""

import csv
import subprocess

import structlog

logger = structlog.get_logger(__name__)


def query_gpu_fields(
    executable: str, fields: tuple[str, ...], *, timeout_seconds: float
) -> list[list[str]] | None:
    """Return one list of stripped CSV cells per GPU, or ``None`` if the query failed."""
    argv = [executable, f"--query-gpu={','.join(fields)}", "--format=csv,noheader,nounits"]
    try:
        result = subprocess.run(  # noqa: S603  # fixed argv, no shell, no external input
            argv, capture_output=True, text=True, timeout=timeout_seconds, check=False
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("gpu_probe_failed", error=type(exc).__name__)
        return None
    if result.returncode != 0:
        logger.warning("gpu_probe_nonzero_exit", returncode=result.returncode)
        return None
    rows = csv.reader(result.stdout.splitlines(), skipinitialspace=True)
    return [[cell.strip() for cell in row] for row in rows]
