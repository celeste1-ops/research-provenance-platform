"""Make the files of the FSF sample research (fixtures/fsf_sample, DECISIONS D-059).

The sample is fictional: the research, the numbers, the code, the pictures and the people are
made up to show what the app does. Its steps are in fixtures/fsf_sample/records.<lang>.json;
this script writes the files those steps attach, the same bytes every time:

    uv run python tools/make_fsf_sample.py
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent.parent / "fixtures" / "fsf_sample" / "files"
ZIP_TIME = (2025, 11, 20, 9, 0, 0)  # fixed, so the same files give the same zip


def font(size: int):
    return ImageFont.load_default(size=size)


def save_png(img: Image.Image, name: str) -> None:
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    (OUT / name).write_bytes(buf.getvalue())


def saturation(t: float, k: float = 0.8, alpha: float = 1.3) -> float:
    """v(t) for dv/dt = k (1 - v)^alpha, v(0) = 0."""
    return 1 - (1 + (alpha - 1) * k * t) ** (-1 / (alpha - 1))


# ---------------------------------------------------------------- pictures


def notebook_page() -> None:
    img = Image.new("RGB", (640, 420), (250, 246, 232))
    d = ImageDraw.Draw(img)
    for y in range(40, 420, 28):
        d.line((0, y, 640, y), fill=(196, 214, 236), width=1)
    d.line((70, 0, 70, 420), fill=(232, 160, 160), width=2)
    ink = (38, 52, 110)
    d.text((90, 18), "Sept. 2025 - flow speed?", fill=ink, font=font(20))
    ox, oy = 120, 360
    d.line((ox, oy, 560, oy), fill=ink, width=3)
    d.line((ox, oy, ox, 90), fill=ink, width=3)
    d.text((570, 350), "F", fill=ink, font=font(20))
    d.text((100, 72), "v", fill=ink, font=font(20))
    pts = [(ox + 4 * i, oy - 230 * (1 - (1 + 0.04 * i) ** -2.2)) for i in range(0, 108)]
    d.line(pts, fill=ink, width=3, joint="curve")
    d.line((ox, 128, 560, 128), fill=(160, 70, 70), width=2)
    d.text((400, 98), "levels off?", fill=(160, 70, 70), font=font(18))
    d.text((300, 250), "why? how fast?", fill=ink, font=font(18))
    save_png(img, "notebook-page.png")


def axes(d: ImageDraw.ImageDraw, box, xlabel: str, ylabel: str, title: str) -> None:
    x0, y0, x1, y1 = box
    d.rectangle(box, outline=(60, 60, 60), width=2)
    d.text((x0, 14), title, fill=(30, 30, 30), font=font(18))
    d.text(((x0 + x1) // 2 - 40, y1 + 34), xlabel, fill=(30, 30, 30), font=font(16))
    d.text((8, y0 - 26), ylabel, fill=(30, 30, 30), font=font(16))


def figure_exponent() -> None:
    img = Image.new("RGB", (720, 480), "white")
    d = ImageDraw.Draw(img)
    box = (90, 50, 690, 410)
    axes(d, box, "forcing F", "alpha", "Figure 2: fitted exponent vs forcing (sample)")
    fx = lambda f: box[0] + (f - 0.25) / 1.5 * (box[2] - box[0])  # noqa: E731
    fy = lambda a: box[3] - (a - 1.1) / 0.4 * (box[3] - box[1])  # noqa: E731
    for f in (0.5, 1.0, 1.5):
        d.text((fx(f) - 12, box[3] + 8), f"{f:.1f}", fill=(60, 60, 60), font=font(14))
    for a in (1.2, 1.3, 1.4):
        d.text((box[0] - 40, fy(a) - 8), f"{a:.1f}", fill=(60, 60, 60), font=font(14))
        d.line((box[0], fy(a), box[2], fy(a)), fill=(232, 232, 232), width=1)
    d.line((fx(0.25), fy(1.45), fx(1.75), fy(1.15)), fill=(47, 91, 211), width=3)
    for f, a, err in ((0.5, 1.40, 0.02), (1.0, 1.30, 0.015), (1.5, 1.21, 0.02)):
        d.line((fx(f), fy(a - err), fx(f), fy(a + err)), fill=(200, 80, 40), width=2)
        d.ellipse((fx(f) - 7, fy(a) - 7, fx(f) + 7, fy(a) + 7), fill=(200, 80, 40))
    d.text((box[2] - 250, box[1] + 12), "alpha(F) = 1.5 - 0.2 F", fill=(47, 91, 211), font=font(16))
    save_png(img, "figure2-exponent.png")


def figure_sweep(alpha: list[list[float]], ks: list[float], fs: list[float]) -> None:
    img = Image.new("RGB", (720, 480), "white")
    d = ImageDraw.Draw(img)
    box = (110, 50, 610, 410)
    axes(d, box, "forcing F", "k", "Figure 3: exponent over the sweep (sample)")
    cw = (box[2] - box[0]) / len(fs)
    ch = (box[3] - box[1]) / len(ks)
    lo, hi = 1.05, 1.5
    for i, k in enumerate(ks):
        for j, _f in enumerate(fs):
            a = alpha[i][j]
            u = max(0.0, min(1.0, (a - lo) / (hi - lo)))
            color = (int(40 + 200 * u), int(90 + 80 * (1 - abs(u - 0.5) * 2)), int(220 - 180 * u))
            x = box[0] + j * cw
            y = box[3] - (i + 1) * ch
            d.rectangle((x, y, x + cw, y + ch), fill=color, outline="white")
        d.text((box[0] - 42, box[3] - (i + 0.5) * ch - 8), f"{k:.2f}", fill=(60, 60, 60), font=font(13))
    for j, f in enumerate(fs):
        d.text((box[0] + (j + 0.5) * cw - 14, box[3] + 8), f"{f:.2f}", fill=(60, 60, 60), font=font(13))
    for n in range(6):  # colour key
        u = n / 5
        color = (int(40 + 200 * u), int(90 + 80 * (1 - abs(u - 0.5) * 2)), int(220 - 180 * u))
        d.rectangle((640, 330 - n * 50, 670, 380 - n * 50), fill=color)
        d.text((674, 345 - n * 50), f"{lo + u * (hi - lo):.2f}", fill=(60, 60, 60), font=font(12))
    save_png(img, "figure3-sweep.png")


def setup_sketch() -> None:
    img = Image.new("RGB", (640, 360), (245, 247, 250))
    d = ImageDraw.Draw(img)
    ink = (40, 50, 70)
    d.text((20, 14), "Flow channel (sample sketch)", fill=ink, font=font(20))
    d.rounded_rectangle((80, 150, 560, 210), radius=8, outline=ink, width=3, fill=(214, 232, 250))
    for x in range(120, 540, 60):
        d.line((x, 180, x + 30, 180), fill=(47, 91, 211), width=3)
        d.polygon([(x + 30, 174), (x + 40, 180), (x + 30, 186)], fill=(47, 91, 211))
    d.ellipse((20, 160, 60, 200), outline=ink, width=3)
    d.text((14, 210), "pump", fill=ink, font=font(16))
    d.line((60, 180, 80, 180), fill=ink, width=3)
    d.rectangle((560, 165, 600, 195), outline=ink, width=3)
    d.text((548, 210), "sensor", fill=ink, font=font(16))
    d.text((250, 222), "1.2 m acrylic channel", fill=ink, font=font(16))
    d.text((200, 290), "controller: variable frequency, 0-50 Hz", fill=ink, font=font(16))
    save_png(img, "setup-sketch.png")


def figure_saturation_svg() -> None:
    w, h, x0, y0, x1, y1 = 520, 340, 60, 30, 500, 290
    pts = []
    for i in range(0, 81, 2):
        v = saturation(i)
        pts.append(f"{x0 + i / 80 * (x1 - x0):.1f},{y1 - v * (y1 - y0):.1f}")
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">
<rect width="{w}" height="{h}" fill="#ffffff"/>
<text x="{x0}" y="20" font-family="sans-serif" font-size="14" fill="#222">Figure 1: saturation curve, run 1 (sample)</text>
<line x1="{x0}" y1="{y1}" x2="{x1}" y2="{y1}" stroke="#444" stroke-width="1.5"/>
<line x1="{x0}" y1="{y1}" x2="{x0}" y2="{y0}" stroke="#444" stroke-width="1.5"/>
<line x1="{x0}" y1="{y0}" x2="{x1}" y2="{y0}" stroke="#bbb" stroke-dasharray="4 4"/>
<polyline points="{' '.join(pts)}" fill="none" stroke="#2f5bd3" stroke-width="2.5"/>
<text x="{x1 - 20}" y="{y1 + 22}" font-family="sans-serif" font-size="13" fill="#444">t</text>
<text x="{x0 - 30}" y="{y0 + 10}" font-family="sans-serif" font-size="13" fill="#444">v</text>
<text x="{x0 - 22}" y="{y0 + 30}" font-family="sans-serif" font-size="11" fill="#888">1.0</text>
<text x="{x1 - 170}" y="{y0 + 40}" font-family="sans-serif" font-size="12" fill="#2f5bd3">fitted alpha = 1.3 (H1 said 1.5)</text>
</svg>
"""
    (OUT / "figure1-saturation.svg").write_text(svg, encoding="utf-8", newline="\n")


# ---------------------------------------------------------------- data, code, documents


def data_files(ks: list[float], fs: list[float]) -> list[list[float]]:
    rows = ["t,v"] + [f"{t},{saturation(t):.4f}" for t in range(0, 81, 5)]
    (OUT / "run1_results.csv").write_text("\n".join(rows) + "\n", encoding="utf-8", newline="\n")
    (OUT / "run2_summary.csv").write_text(
        "forcing_F,alpha_fit,residual_formula_v2,residual_formula_v1\n"
        "0.5,1.40,0.012,0.038\n1.0,1.30,0.011,0.041\n1.5,1.21,0.013,0.047\n", encoding="utf-8", newline="\n")
    alpha = [[round(1.5 - 0.2 * f + 0.02 * (k - 0.8) - 0.004 * ((i + j) % 3), 3) for j, f in enumerate(fs)]
             for i, k in enumerate(ks)]
    sweep = {"description": "Sensitivity sweep (sample data): fitted alpha for each k and F.",
             "solver": "v0.2 (c05b9e2)", "k": ks, "F": fs, "alpha": alpha}
    (OUT / "run3_sweep.json").write_text(json.dumps(sweep, indent=1) + "\n", encoding="utf-8", newline="\n")
    (OUT / "run4_robustness.csv").write_text(
        "step_size,forcing_F,alpha_fit\n"
        "0.005,1.0,1.301\n0.010,1.0,1.300\n0.020,1.0,1.298\n"
        "0.005,2.0,1.102\n0.010,2.0,1.099\n0.020,2.0,unstable\n", encoding="utf-8", newline="\n")
    (OUT / "calibration.csv").write_text(
        "controller_hz,flow_l_per_min\n10,1.9\n20,4.1\n30,6.0\n40,8.2\n50,9.9\n", encoding="utf-8", newline="\n")
    (OUT / "lattice_run.log").write_text(
        "lattice model, 64 x 64 grid, periodic boundary\n"
        "step  1000  mean v = 0.412\nstep  5000  mean v = 0.733\nstep 20000  mean v = 0.861\n"
        "fit: alpha = 1.10 (+/- 0.08)\n"
        "WARNING: boundary condition set to periodic; channel walls should be no-slip\n", encoding="utf-8", newline="\n")
    return alpha


SOLVER_V1 = '''"""FSF solver prototype (sample code): dv/dt = k (1 - v)^alpha, explicit Euler."""


def solve(k=0.8, alpha=1.5, steps=80, dt=1.0):
    v, out = 0.0, []
    for n in range(steps + 1):
        out.append((n * dt, v))
        v += dt * k * (1 - v) ** alpha
    return out
'''

SOLVER_V2 = '''"""FSF solver v2 (sample code): the exponent depends on the forcing F."""


def alpha_of(forcing):
    return 1.5 - 0.2 * forcing


def solve(forcing, k=0.8, steps=80, dt=1.0):
    alpha = alpha_of(forcing)
    v, out = 0.0, []
    for n in range(steps + 1):
        out.append((n * dt, v))
        v += dt * k * (1 - v) ** alpha
    return out
'''

SOLVER_V21 = '''"""FSF solver v0.2 (sample code): exponent depends on F; adaptive step size."""


def alpha_of(forcing):
    return 1.5 - 0.2 * forcing


def solve(forcing, k=0.8, t_end=80.0, tol=1e-4):
    alpha = alpha_of(forcing)
    t, v, dt, out = 0.0, 0.0, 0.5, [(0.0, 0.0)]
    while t < t_end:
        full = v + dt * k * (1 - v) ** alpha
        half = v + dt / 2 * k * (1 - v) ** alpha
        half = half + dt / 2 * k * (1 - half) ** alpha
        if abs(full - half) > tol:
            dt /= 2
            continue
        t, v = t + dt, half
        out.append((t, v))
        dt = min(dt * 1.5, 2.0)
    return out
'''


def code_files() -> None:
    (OUT / "solver-v1.py").write_text(SOLVER_V1, encoding="utf-8", newline="\n")
    (OUT / "solver-v2.py").write_text(SOLVER_V2, encoding="utf-8", newline="\n")
    for name, commit, code in (("fsf-solver-3f9c2ab.zip", "3f9c2ab", SOLVER_V1),
                               ("fsf-solver-c05b9e2.zip", "c05b9e2", SOLVER_V21)):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for member, text in (("README.md", f"FSF solver at commit {commit} (sample code).\n"),
                                 ("solver.py", code)):
                info = zipfile.ZipInfo(member, date_time=ZIP_TIME)
                info.compress_type = zipfile.ZIP_DEFLATED
                z.writestr(info, text)
        (OUT / name).write_bytes(buf.getvalue())


def document_files() -> None:
    (OUT / "references.bib").write_text(
        "% Fictional references for the sample research.\n"
        "@article{modelA, author = {Example, A.}, title = {Linear response of driven channel flow},"
        " journal = {Sample Journal}, year = {2014}}\n"
        "@article{modelB, author = {Sample, B. and Demo, C.}, title = {Logistic saturation with a fixed exponent},"
        " journal = {Sample Journal}, year = {2018}}\n"
        "@article{modelC, author = {Placeholder, D.}, title = {An empirical fit for saturating flows},"
        " journal = {Sample Letters}, year = {2021}}\n", encoding="utf-8", newline="\n")
    (OUT / "formula-v1.tex").write_text(
        "% Formula v1 (sample)\n\\begin{equation}\n  \\frac{dv}{dt} = k\\,(1 - v)^{\\alpha},"
        " \\qquad k = 0.8,\\ \\alpha = 1.5\n\\end{equation}\n", encoding="utf-8", newline="\n")
    (OUT / "formula-v2.tex").write_text(
        "% Formula v2 (sample): the exponent depends on the forcing F\n\\begin{equation}\n"
        "  \\frac{dv}{dt} = k\\,(1 - v)^{\\alpha(F)}, \\qquad \\alpha(F) = 1.5 - 0.2\\,F\n\\end{equation}\n",
        encoding="utf-8", newline="\n")


def pdf_file() -> None:
    """A one-page PDF (a file the app cannot show itself: it opens with its own program)."""
    lines = ["Forcing-dependent saturation of flow speed", "Preprint v1 - FICTIONAL SAMPLE",
             "", "This document only illustrates an attached PDF in the Research History sample."]
    text = "BT /F1 16 Tf 72 740 Td " + " ".join(
        f"({ln}) Tj 0 -24 Td" for ln in lines) + " ET"
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >>"
        " /Contents 5 0 R >>",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        f"<< /Length {len(text)} >>\nstream\n{text}\nendstream",
    ]
    out = b"%PDF-1.4\n"
    offsets = []
    for n, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{n} 0 obj\n{body}\nendobj\n".encode("latin-1")
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode("latin-1")
    out += "".join(f"{o:010d} 00000 n \n" for o in offsets).encode("latin-1")
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode("latin-1")
    (OUT / "preprint-v1.pdf").write_bytes(out)


DRAFTS = {
    "en": {
        "draft-method.md": (
            "# Method (draft 1)\n\n"
            "We model the flow speed v with dv/dt = k (1 - v)^alpha(F), where the exponent depends on the "
            "forcing F (formula v2).\n\n"
            "The equation is solved with the FSF solver v0.2 (adaptive step size).\n\n"
            "As a cross-check we also use a lattice discretisation on a 64 x 64 grid.\n\n"
            "*Sample text: the research is fictional.*\n"),
        "draft-method-v2.md": (
            "# Method (draft 2)\n\n"
            "We model the flow speed v with dv/dt = k (1 - v)^alpha(F), alpha(F) = 1.5 - 0.2 F.\n\n"
            "The equation is solved with the FSF solver v0.2 (adaptive step size; commit c05b9e2). "
            "A sweep over k and F (35 runs) shows that alpha(F) stays linear within 0.03 for 0.25 <= F <= 2.\n\n"
            "Changes after the meeting with the advisor: the lattice cross-check is removed (wrong boundary "
            "condition); a sensitivity sweep is added.\n\n"
            "*Sample text: the research is fictional.*\n"),
    },
    "zh": {
        "draft-method.md": (
            "# 方法（第 1 稿）\n\n"
            "用 dv/dt = k (1 - v)^alpha(F) 描述流速 v，其中指数随驱动强度 F 变化（公式 v2）。\n\n"
            "方程用 FSF 求解器 v0.2（自适应步长）求解。\n\n"
            "另外用 64 × 64 的格点模型做交叉验证。\n\n"
            "*示例文字：这项研究是虚构的。*\n"),
        "draft-method-v2.md": (
            "# 方法（第 2 稿）\n\n"
            "用 dv/dt = k (1 - v)^alpha(F) 描述流速 v，alpha(F) = 1.5 - 0.2 F。\n\n"
            "方程用 FSF 求解器 v0.2 求解（自适应步长；提交 c05b9e2）。对 k 和 F 的扫描（35 次计算）显示，"
            "在 0.25 ≤ F ≤ 2 范围内 alpha(F) 的线性误差不超过 0.03。\n\n"
            "按导师意见的修改：删掉了格点模型的交叉验证（边界条件设错了）；加上了参数敏感性扫描。\n\n"
            "*示例文字：这项研究是虚构的。*\n"),
    },
}


def drafts() -> None:
    for lang, files in DRAFTS.items():
        (OUT / lang).mkdir(exist_ok=True)
        for name, text in files.items():
            (OUT / lang / name).write_text(text, encoding="utf-8", newline="\n")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    ks = [0.6, 0.7, 0.8, 0.9, 1.0]
    fs = [0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0]
    alpha = data_files(ks, fs)
    notebook_page()
    figure_saturation_svg()
    figure_exponent()
    figure_sweep(alpha, ks, fs)
    setup_sketch()
    code_files()
    document_files()
    pdf_file()
    drafts()
    for p in sorted(OUT.rglob("*")):
        if p.is_file():
            print(f"{p.relative_to(OUT)}  {p.stat().st_size} bytes")


if __name__ == "__main__":
    main()
