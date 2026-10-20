# Manual Builder

Desktop app (macOS + Windows) that assembles Profil-Clip operating manuals from Word modules.
You pick the parts of a machine; the app merges the matching `.docx` files into one manual,
numbers all chapters, builds the table of contents and the page numbers, and exports DOCX + PDF.

Each module is self-contained: its text (Word) **plus** structured tables for maintenance, wear/spare
parts and fault codes. These tables are printed in the module's own chapter, and also combined into a
machine-wide maintenance plan, parts list and fault-code overview with page references. A machine
without a printer therefore doesn't list printer faults.

## Quick start (development)

```bash
uv sync
uv run manual-builder                       # GUI (asks for the library on first start)
uv run manual-builder -l ../Anleitungs-Bibliothek build skt-h10-beispiel -o ~/Desktop/out
uv run pytest
```

For TOC/page numbers and the PDF, one of these must be installed:

| Engine | Used for | Notes |
|---|---|---|
| Microsoft Word (Windows) | DOCX + PDF | best fidelity, COM automation via pywin32 |
| Microsoft Word (macOS) | DOCX + PDF | AppleScript; first run asks for permission to control Word |
| LibreOffice | PDF | DOCX is delivered as generated; Word refreshes TOC/page numbers on open |
| none | DOCX only | Word asks "update fields?" on open |

"Automatisch" (auto) tries Word first, then LibreOffice.

## The library

The library is a plain folder, kept **outside** this repo (e.g. on a network drive, or in its own git repo):

```
Anleitungs-Bibliothek/
  library.yaml               slots (chapter order), languages, labels, variables
  templates/master.docx      cover page, header/footer with logo, TOC, heading numbering
  modules/<id>/module.yaml   title, slot, version, change history
  modules/<id>/de.docx       text per language (en.docx, it.docx …)
  modules/<id>/data.yaml     maintenance / spare_parts / faults (translatable)
  modules/<id>/archive/      previous versions
  machines/<name>.yaml       saved machine configurations
```

It was created once from `../Bedienungsanleitungen` with `manual-builder -l <dir> seed <legacy dir>`.
`SEED_REPORT.md` in the library lists how the old fault/maintenance tables were split up. **Please
review it.** Rows can be moved between modules in the app (double-click a module → table → "In anderes
Modul verschieben").

Rules for writing modules are in [docs/Word-Regeln.md](docs/Word-Regeln.md).

## How a build works

1. Validate the configuration (one clipper only, required chapters present, conflicts, missing translations).
2. Open `master.docx`. For each module: normalise the `.docx` (detect headings, remove typed numbers,
   fix levels) and append it with `docxcompose`, which keeps images, text boxes, lists and styles.
3. Insert the generated tables at the `{{ABSCHNITT_…}}` / `{{GESAMT_…}}` markers (or at the end of the
   module chapter), with bookmarks + `PAGEREF` fields for the fault overview.
4. Replace `{{Variablen}}` in body, header and footer.
5. Word/LibreOffice updates TOC and page fields and exports the PDF.

Code map: `normalize.py` (cleanup), `build.py` (assembly), `engines.py` (Word/LibreOffice),
`library.py` (data model), `importer.py`, `seed.py` (one-time legacy import), `gui/`.

## Packaging

```bash
cd packaging && uv run pyinstaller manual_builder.spec --noconfirm --distpath ../dist --workpath ../build
```

PyInstaller can't cross-compile, so the Windows `.exe` is built by GitHub Actions: run the
**Build** workflow manually (Actions → Build → Run workflow) or push a tag `v*`. The zipped app
is attached to the run as an artifact. The macOS app is unsigned: on first start, right-click → Open.
