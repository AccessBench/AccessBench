# Figures

Every SVG in this folder is generated. Do not edit one by hand; the next build
will overwrite it.

```bash
python3 tools/make_hero.py       # hero.svg, hero-plain.svg, mark.svg
python3 tools/make_diagrams.py   # fig-*.svg
```

`tools/svgkit.py` holds the shared palette, type scale and arrow vocabulary, so
changing a colour there changes it everywhere at once. The palette is the same
one the dashboard uses (`dashboard/static/styles.css`); the variable names in
that file are historical and the hex values are what count.

No figure paints a background. Each one draws its boxes and nothing else, so it
sits on the page rather than on a card of its own, and every colour is a token
with a light value and a dark value carried in a `<style>` block inside the
file. One SVG therefore follows whichever theme the reader is in.

Type is Charter throughout, with `Charis SIL` and Georgia behind it for readers
who do not have Charter installed.

Design tools import SVG as plain geometry and drop the stylesheet, so a figure
opened straight in Figma or Illustrator loses its colours. Flatten it first:

```bash
python3 tools/flatten_svg.py --theme dark --plate --out build/figma
```

The output is a working copy, never a source of truth, and `build/` is ignored.

| File | Where it appears |
| --- | --- |
| `hero.svg` | README header |
| `hero-plain.svg` | the same picture with no headline, for a page that sets its own type |
| `mark.svg` | square mark, for a favicon or an app icon |
| `fig-run.svg` | README, one run end to end |
| `fig-models.svg` | README and 11 Results, seven models behind Benchmark PDP v3 (the numbers of record) |
| `fig-headline.svg` | retired, v2 era: one model (gpt-4o) behind Benchmark PDP v2; no page uses it |
| `fig-paired.svg` | 01 Design, the paired experiment |
| `fig-lifecycle.svg` | 01 Design, how one case runs |
| `fig-seam.svg` | 02 Methodology, the enforcement seam |
| `fig-bricks.svg` | 02 Methodology, the method on a real lakehouse |
| `fig-result.svg` | 03 Scope, what one run hands back |
| `fig-bank.svg` | 03 Scope, the shape of the bank |
| `fig-setup.svg` | 04 Setup, three ways in and one pipeline out |
| `fig-integrity.svg` | 06 Integrity, the integrity decision |
| `fig-sealed.svg` | 06 Integrity, the life of a sealed pack |
| `fig-gates.svg` | 07 Validation, the gates a result has to clear |
| `fig-digests.svg` | 10 Replication, what binds a number to its source |

Two placeholders were removed rather than filled, both because the paragraph
next to them already said the same thing: the bank grid in the README (it is
drawn in 03 Scope, where the contract lives) and the second copy of the paired
experiment in 02 Methodology (it is drawn in 01 Design).

The two hand-typed flow charts that used to sit in code fences, in 01 Design and
06 Integrity, are now `fig-lifecycle.svg` and `fig-integrity.svg`.
