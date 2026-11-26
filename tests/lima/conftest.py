import os
import shutil
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import pytest


@dataclass(frozen=True)
class LimaVM:
    executable: str
    name: str

    def _run(self, *args: str) -> str:
        result = subprocess.run(  # noqa: S603  # Invokes the resolved limactl path.
            [self.executable, *args],
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
        )
        if result.returncode:
            pytest.fail(
                f'{self.name}: {args!r} exited {result.returncode}\n'
                f'{result.stdout}{result.stderr}'
            )
        return result.stdout

    def shell(self, *args: str) -> str:
        return self._run('shell', self.name, *args)

    def copy(self, source: Path, destination: str) -> None:
        self._run('copy', str(source), f'{self.name}:{destination}')

    @contextmanager
    def staging_directory(self) -> Iterator[str]:
        directory = self.shell('mktemp', '-d').strip()
        try:
            yield directory
        finally:
            self.shell('rm', '-rf', '--', directory)


@pytest.fixture
def vm(family: str) -> LimaVM:
    variable = f'HARDENING_VM_{family.upper()}'
    name = os.environ.get(variable, '').strip()
    if not name:
        pytest.skip(f'Set {variable} to a running disposable Lima VM')
    executable = shutil.which('limactl')
    if executable is None:
        pytest.skip('Install limactl to run the Lima hardening checks')
    return LimaVM(executable, name)
