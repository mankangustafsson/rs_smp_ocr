# rs_smp_ocr

Scripts and instructions for OCRing the Rohde & Schwarz **SMP Microwave
Signal Generator** documentation with
[MinerU](https://github.com/opendatalab/MinerU) and post-processing the
result into a curated, retrieval-ready markdown corpus — structured for
ingestion by AI context engines and RAG pipelines.

## Inputs

`scripts/restructure.py` matches these filenames verbatim:

| Filename                              | Volume id     | Language |
| ------------------------------------- | ------------- | -------- |
| `SMP-1036.5015.24-04-Band-1.pdf`      | `band-1`      | DE + EN  |
| `SMP-1036.5015.24-04-Band-2.pdf`      | `band-2`      | DE + EN  |
| `SMP-1036.5015.24-04-Band-3.pdf`      | `band-3`      | DE + EN  |
| `SMP-1036.5015.24-04-Band-4.pdf`      | `band-4`      | DE + EN  |
| `smp_08_e.pdf`                        | `user-manual` | EN       |
| `SMP_dat_en.pdf`                      | `datasheet`   | EN       |

## Prerequisites

Python 3.12 and `pip install -r requirements.txt`. MinerU's first run
downloads several GB of models from HuggingFace / ModelScope into a local
cache; subsequent runs are offline.

## Step 1 — Run MinerU

```bash
src=/path/to/pdfs   # directory holding the 6 PDFs

mineru -p "$src/smp_08_e.pdf"   -o output -b hybrid-auto-engine -l en
mineru -p "$src/SMP_dat_en.pdf" -o output -b hybrid-auto-engine -l en
for pdf in "$src"/SMP-1036.5015.24-04-Band-*.pdf; do
    mineru -p "$pdf" -o output -b hybrid-auto-engine -l latin
done
```

Drop to `-b pipeline` only if the VLM doesn't fit in VRAM (table
extraction quality degrades noticeably).

## Step 2 — Restructure into the volume tree

Rename the 6 raw output folders into `sources/<volume>/` — the layout
the build scripts expect (`band-1` … `band-4`, `user-manual`, `datasheet`):

```bash
python scripts/restructure.py --input-dir output --output-dir sources
```

Pass `--copy` to keep the originals.

## Step 3 — Trim MinerU output (optional)

Only `<stem>_content_list.json` and `images/` feed the build pipeline; the
rest is debug / audit output and can be removed to reclaim disk space.

```bash
python scripts/cleanup_mineru.py --input-dir output             # dry-run
python scripts/cleanup_mineru.py --input-dir output --apply     # delete
```

Runs on either the raw `output/` or the post-restructure `sources/`
layout, so cleanup can happen before or after restructuring.

## Step 4 — Build the curated corpus

```bash
python scripts/build_all.py    # runs build_pages, build_tables, build_figures,
                               # finalize_pages, build_sections, build_topic_hubs,
                               # build_indexes, verify
```

`scripts/config.yaml` defines the six volumes; `scripts/toc_overrides.yaml`
pins chapter boundaries and module names. The `finalize_pages` step inlines
each page's OCR'd HTML table(s) and curated figure image(s) into the page
body so the per-page markdown renders as self-contained, human-readable
documents in GitHub and VSCode. Output lands in a single `rs_smp_corpus/`
folder with `volumes/` (sections, tables, figures, pages) and `index/`
(cross-cutting indexes) as subdirectories — a derived artifact that is
self-contained enough to zip and move as-is.

## Related Projects

- [**rs_smp_tools**](https://github.com/mankangustafsson/rs_smp_tools) — GPIB control and functional testing for the SMP02 signal generator
- [**rs_smp_a21_repair**](https://github.com/mankangustafsson/rs_smp_a21_repair) — KiCAD files for A21 PA stage replacement board

## Diagnostics

Read-only inspection tools live under `scripts/diagnostics/`; none are part
of the build. See each script's module docstring for what it does and where
it writes its output.

## Searchable PDFs (optional deliverable)

Build the four band service manuals as searchable A4 PDFs from the curated
markdown. Not part of the main build; requires an extra install step.

```bash
playwright install chromium
python scripts/build_pdfs.py         # writes output/band_pdfs/band-{1..4}.pdf
python scripts/verify_pdfs.py        # writes _pdfs_verification.md at the repo root
```

`build_pdfs.py` accepts `--volume band-N` for partial builds.

## Development

```bash
pip install -r requirements-dev.txt
python ci/check.py          # ruff lint + format check + mypy strict
python ci/check.py --fix    # auto-fix and re-check
```

The same `ci/check.py` backs the pre-commit hook (`pre-commit install`)
and `.github/workflows/ci.yml`. Tool settings live in `pyproject.toml`
(88-char lines, `mypy --strict`, ruff rules `E,W,F,I,UP,B,SIM,RUF`).

## License

MIT — see [LICENSE](LICENSE). The R&S SMP service-manual PDFs are **not**
included and remain the property of their respective copyright holders.
If you end up using this pipeline on your own manuals, I'd be glad to hear
about it.
