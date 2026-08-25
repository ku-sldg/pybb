#!/usr/bin/env python3
"""Diff two .pptx decks at the fidelity the slide-regeneration protocol needs:
per-slide paragraph text INCLUDING <a:br/> line breaks, run-level formatting
(size, bold, italic, font), and shape position AND extent.

Usage: python3 pptx_diff.py OLD.pptx NEW.pptx
"""
import sys, zipfile, re

EMU = 914400

def slide_parts(path):
    z = zipfile.ZipFile(path)
    return z, sorted(
        (n for n in z.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", n)),
        key=lambda n: int(re.search(r"(\d+)", n).group(1)),
    )

def para_repr(p_xml):
    """Text of one paragraph with runs annotated by formatting; <a:br/> -> \\n."""
    out = []
    for tok in re.finditer(r"<a:br/>|<a:r>.*?</a:r>", p_xml, re.S):
        t = tok.group(0)
        if t == "<a:br/>":
            out.append("\\n")
            continue
        text = "".join(re.findall(r"<a:t>([^<]*)</a:t>", t))
        rpr = re.search(r"<a:rPr[^>]*>", t)
        fmt = ""
        if rpr:
            r = rpr.group(0)
            sz = re.search(r'sz="(\d+)"', r)
            if sz: fmt += f"@{int(sz.group(1))/100:g}pt"
            if re.search(r'b="1"', r): fmt += " b"
            if re.search(r'i="1"', r): fmt += " i"
            f = re.search(r'typeface="([^"]+)"', r)
            if f: fmt += f" {f.group(1)}"
        out.append(f"{text!r}[{fmt.strip()}]" if fmt else repr(text))
    return " + ".join(out)

def shape_repr(sp_xml):
    txt = " ".join(re.findall(r"<a:t>([^<]*)</a:t>", sp_xml))[:40]
    off = re.search(r'<a:off x="(-?\d+)" y="(-?\d+)"', sp_xml)
    ext = re.search(r'<a:ext cx="(\d+)" cy="(\d+)"', sp_xml)
    pos = tuple(round(int(v)/EMU, 2) for v in off.groups()) if off else None
    size = tuple(round(int(v)/EMU, 2) for v in ext.groups()) if ext else None
    return txt, pos, size

def slide_model(xml):
    paras = [para_repr(p) for p in re.findall(r"<a:p>.*?</a:p>", xml, re.S)]
    shapes = [shape_repr(sp) for sp in re.findall(r"<p:sp>.*?</p:sp>", xml, re.S)]
    return paras, shapes

def main(old, new):
    za, parts_a = slide_parts(old)
    zb, parts_b = slide_parts(new)
    any_diff = False
    for i in range(max(len(parts_a), len(parts_b))):
        name = f"slide{i+1}"
        if i >= len(parts_a): print(f"== {name}: only in NEW =="); any_diff = True; continue
        if i >= len(parts_b): print(f"== {name}: only in OLD =="); any_diff = True; continue
        pa, sa = slide_model(za.read(parts_a[i]).decode())
        pb, sb = slide_model(zb.read(parts_b[i]).decode())
        if pa != pb:
            any_diff = True
            print(f"== {name}: PARAGRAPHS ==")
            for p in pa:
                if p not in pb: print(f"  OLD: {p[:160]}")
            for p in pb:
                if p not in pa: print(f"  NEW: {p[:160]}")
        if sa != sb:
            geo_a = [(s[1], s[2]) for s in sa]
            geo_b = [(s[1], s[2]) for s in sb]
            if geo_a != geo_b:
                any_diff = True
                print(f"== {name}: SHAPE GEOMETRY ==")
                for x, y in zip(sa, sb):
                    if (x[1], x[2]) != (y[1], y[2]):
                        print(f"  {x[0]!r}: pos {x[1]}->{y[1]} size {x[2]}->{y[2]}")
    if not any_diff:
        print("IDENTICAL (at protocol fidelity)")

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
