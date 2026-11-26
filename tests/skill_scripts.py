"""Run the shell snippets the vuln-* skills document against fake commands."""

import os
import re
import shutil
import subprocess
from collections.abc import Iterable, Sequence
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[1] / 'plugins/alpacon/skills'


def doc_blocks(reference: str, lang: str) -> list[str]:
    """The fenced `lang` blocks of a skill file under `SKILLS`, in document order."""
    return re.findall(rf'```{lang}\n(.*?)```', (SKILLS / reference).read_text(), re.S)


def install_fakes(bin_dir: Path, fakes: dict[str, str]) -> None:
    """Write each body as an executable `/bin/sh` script named after the command it replaces."""
    bin_dir.mkdir(exist_ok=True)
    for name, body in fakes.items():
        path = bin_dir / name
        path.write_text('#!/bin/sh\n' + body + '\n')
        path.chmod(0o755)


GNU_COREUTILS = {'sha256sum', 'stat'}  # macOS installs these as gstat, gsha256sum


def toolbox(bin_dir: Path, real: Iterable[str]) -> str:
    bin_dir.mkdir(exist_ok=True)
    for name in real:
        gnu = shutil.which(f'g{name}') if name in GNU_COREUTILS else None
        resolved = gnu or shutil.which(name)
        if resolved is None:
            raise FileNotFoundError(name)
        (bin_dir / name).symlink_to(Path(resolved).resolve())
    return str(bin_dir)


def run_with_fakes(
    argv: Sequence[str], bin_dir: Path, **env: str
) -> subprocess.CompletedProcess[str]:
    """Run `argv` with `bin_dir` first on PATH, so its fakes shadow the real commands."""
    return subprocess.run(  # noqa: S603  # repository snippets against isolated fakes
        argv,
        env={
            **os.environ,
            'PATH': str(bin_dir) + os.pathsep + os.environ['PATH'],
            **env,
        },
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )
