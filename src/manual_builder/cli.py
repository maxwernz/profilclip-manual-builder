"""Command line: manual-builder [gui|build|check|import|seed|template] ..."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .library import Library, Machine


def _lib(args) -> Library:
    return Library(Path(args.library))


def cmd_build(args) -> int:
    from .build import BuildError, build_manual
    lib = _lib(args)
    machine_path = Path(args.machine)
    if not machine_path.exists():
        machine_path = lib.machines_dir / f"{args.machine}.yaml"
    machine = Machine.load(machine_path)
    if args.language:
        machine.language = args.language
    try:
        res = build_manual(lib, machine, Path(args.out), pdf=not args.no_pdf, engine=args.engine)
    except BuildError as e:
        print(e, file=sys.stderr)
        return 2
    for i in res.issues:
        print(i)
    return 0


def cmd_check(args) -> int:
    from .importer import check
    lib = _lib(args)
    rep = check(lib, Path(args.file), kind=args.kind, title=args.title or Path(args.file).stem)
    print(rep.summary())
    return 1 if rep.errors else 0


def cmd_import(args) -> int:
    from .importer import import_file
    lib = _lib(args)
    module = lib.modules.get(args.module)
    if module is None:
        if not args.slot:
            print(f"Modul '{args.module}' existiert nicht – mit --slot und --title neu anlegen",
                  file=sys.stderr)
            return 2
        module = lib.new_module(args.module, {args.language: args.title or args.module},
                                args.slot, args.kind)
    rep = import_file(lib, Path(args.file), module, args.language, note=args.note or "")
    print(rep.summary())
    return 1 if rep.errors else 0


def cmd_seed(args) -> int:
    from .seed import seed_from_legacy
    target = Path(args.library)
    if (target / "library.yaml").exists() and not args.force:
        print(f"{target} enthält schon eine Bibliothek (--force zum Überschreiben)", file=sys.stderr)
        return 2
    if args.force and target.exists():
        import shutil
        shutil.rmtree(target)
    seed_from_legacy(Path(args.legacy), target)
    print(f"Bibliothek angelegt: {target}  (Bericht: {target / 'SEED_REPORT.md'})")
    return 0


def cmd_template(args) -> int:
    from .template import create_master_template
    create_master_template(Path(args.source), Path(args.out))
    print(f"Vorlage geschrieben: {args.out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="manual-builder", description="Betriebsanleitungen aus Modulen bauen")
    ap.add_argument("--library", "-l", default="library", help="Pfad zur Bibliothek")
    sub = ap.add_subparsers(dest="cmd")

    sub.add_parser("gui", help="Programmoberfläche starten (Standard)")

    b = sub.add_parser("build", help="Anleitung für eine Maschine erzeugen")
    b.add_argument("machine", help="Maschinen-Datei (.yaml) oder Name in library/machines")
    b.add_argument("--out", "-o", default="output")
    b.add_argument("--language")
    b.add_argument("--engine", default="auto", choices=["auto", "word", "libreoffice", "none"])
    b.add_argument("--no-pdf", action="store_true")

    c = sub.add_parser("check", help="Word-Datei prüfen, ohne sie zu importieren")
    c.add_argument("file")
    c.add_argument("--kind", default="component", choices=["component", "chapters"])
    c.add_argument("--title")

    i = sub.add_parser("import", help="Word-Datei als Modul (neu oder Update) importieren")
    i.add_argument("file")
    i.add_argument("module", help="Modul-ID, z. B. clipper-dcx5s")
    i.add_argument("--language", default="de")
    i.add_argument("--slot", help="nur für neue Module")
    i.add_argument("--title", help="nur für neue Module")
    i.add_argument("--kind", default="component", choices=["component", "chapters"])
    i.add_argument("--note")

    s = sub.add_parser("seed", help="Bibliothek aus den bisherigen Anleitungen anlegen")
    s.add_argument("legacy", help="Ordner 'Bedienungsanleitungen'")
    s.add_argument("--force", action="store_true")

    t = sub.add_parser("template", help="Master-Vorlage aus einer bestehenden Anleitung erzeugen")
    t.add_argument("source")
    t.add_argument("out")

    args = ap.parse_args(argv)
    if args.cmd in (None, "gui"):
        from .gui.app import run
        return run(Path(args.library) if args.cmd else None)
    return {"build": cmd_build, "check": cmd_check, "import": cmd_import, "seed": cmd_seed,
            "template": cmd_template}[args.cmd](args)
