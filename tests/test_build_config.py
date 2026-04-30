import tomllib
from pathlib import Path


def load_pyproject():
    path = Path(__file__).parent.parent / 'pyproject.toml'
    with open(path, 'rb') as f:
        return tomllib.load(f)


def test_wheel_does_not_use_packages_dot():
    """packages=["."] includes the entire repo; must not be present."""
    data = load_pyproject()
    wheel_cfg = (
        data.get('tool', {})
        .get('hatch', {})
        .get('build', {})
        .get('targets', {})
        .get('wheel', {})
    )
    assert 'packages' not in wheel_cfg or wheel_cfg.get('packages') != ['.'], (
        'packages=["."] includes the whole repo in the wheel — use include= instead'
    )


def test_wheel_include_contains_runtime_files():
    """include list must cover every runtime module."""
    data = load_pyproject()
    wheel_cfg = data['tool']['hatch']['build']['targets']['wheel']
    include = wheel_cfg.get('include', [])

    required = {
        '/__init__.py',
        '/py.typed',
        '/server.py',
        '/main.py',
        '/main_sse.py',
        '/main_http.py',
    }
    missing = required - set(include)
    assert not missing, f'Missing from wheel include: {missing}'


def test_wheel_include_excludes_dev_paths():
    """None of the known dev-only paths may appear in include."""
    data = load_pyproject()
    wheel_cfg = data['tool']['hatch']['build']['targets']['wheel']
    include = '\n'.join(wheel_cfg.get('include', []))

    forbidden = [
        'tests',
        'docs',
        'CLAUDE.md',
        '.github',
        'uv.lock',
        'pytest.ini',
        'MANIFEST.in',
    ]
    found = [p for p in forbidden if p in include]
    assert not found, f'Dev-only paths found in wheel include: {found}'
