"""Run a generated Salome Python script as a subprocess."""
from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


def find_salome() -> str | None:
    """Locate the `salome` binary.

    Resolution order: ``$SALOME_BIN`` env var, then ``salome`` on ``PATH``.
    Returns ``None`` if neither is present.
    """
    explicit = os.environ.get("SALOME_BIN")
    if explicit and Path(explicit).exists():
        return explicit
    return shutil.which("salome")


@dataclass
class SalomeRunResult:
    returncode: int
    stdout: str
    stderr: str
    script: Path
    binary: str


def run_script(
    script: Path,
    salome_bin: str | None = None,
    timeout: int = 600,
    extra_args: list[str] | None = None,
) -> SalomeRunResult:
    """Execute ``salome -t script.py``. Raises ``RuntimeError`` if Salome is
    not installed; raises ``subprocess.TimeoutExpired`` on timeout."""
    bin_path = salome_bin or find_salome()
    if not bin_path:
        raise RuntimeError(
            "Could not locate Salome. Set $SALOME_BIN or add `salome` to PATH."
        )
    cmd = [bin_path, "-t", str(script)]
    if extra_args:
        cmd.extend(extra_args)
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return SalomeRunResult(
        returncode=proc.returncode,
        stdout=proc.stdout,
        stderr=proc.stderr,
        script=script,
        binary=bin_path,
    )
