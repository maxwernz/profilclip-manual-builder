"""Anleitungs-Baukasten – Betriebsanleitungen aus Bausteinen zusammenstellen."""

__version__ = "0.2.0"          # single source of truth (pyproject + release tag must match)
APP_NAME = "Anleitungs-Baukasten"
BUNDLE_ID = "de.profilclip.anleitungsbaukasten"
GITHUB_REPO = "maxwernz/profilclip-manual-builder"


def main() -> int:
    from .cli import main as _main
    return _main()
