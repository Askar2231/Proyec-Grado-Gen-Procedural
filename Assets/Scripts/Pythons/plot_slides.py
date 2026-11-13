"""
plot_slides.py
==============
Gráficas para las diapositivas de resultados, a partir de un experimento ya corrido
(no lo repite). Una gráfica por resultado, con letra grande y los colores de la presentación.

USO
    python plot_slides.py experimento_03
    python plot_slides.py experimento_03 --rendimiento "C:\\...\\PCG_Metricas\\rendimiento.csv"

Escribe en experimento_03/diapositivas/:
    1_validez.png         pares de objetos atravesados, reales de prueba vs generados, por familia
    2_variabilidad.png    novedad (distancia al nivel de ajuste más parecido), por familia
    3_tiempo.png          segundos de cada nivel generado, en orden, por familia
    4_rendimiento.png     FPS promedio y del 1 % más lento por nivel (si se da --rendimiento)
    5_similitud.png       copia de relaciones_por_par.png (si existe)
    numeros.md            los números clave de cada diapositiva

--rendimiento: el CSV de PCGPerfRecorder. Los niveles se reconocen por su nombre: los códigos
de la prueba ciega (N01, N02…) se cruzan con prueba_ciega/clave_NO_ABRIR.csv; los nombres que
empiezan por "gen_" cuentan como generados y el resto como reales. Si un nivel se midió varias
veces, se promedian sus repeticiones.
"""
import argparse
import csv
import json
import math
import shutil
from collections import defaultdict
from pathlib import Path

import numpy as np

DARK = "#1f4e3d"       # reales
GREEN = "#84D700"      # generados
EDGE = "#002317"
FAM_LABEL = {"agua": "Con río", "sin_agua": "Sin río"}


def setup():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.size": 15, "axes.titlesize": 17, "axes.labelsize": 15,
                         "xtick.labelsize": 14, "ytick.labelsize": 13, "axes.spines.top": False,
                         "axes.spines.right": False})
    return plt


def load_rows(exp):
    with open(exp / "metricas_por_nivel.csv", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    for r in rows:
        for k, v in list(r.items()):
            if k in ("archivo", "familia", "grupo"):
                continue
            try:
                r[k] = float(v)
            except (TypeError, ValueError):
                r[k] = float("nan")
    return rows


def vals(rows, fam, grp, key):
    return [r[key] for r in rows if r["familia"] == fam and r["grupo"] == grp and not math.isnan(r[key])]


def mw_cliff(a, b):
    try:
        from scipy.stats import mannwhitneyu
        p = float(mannwhitneyu(a, b, alternative="two-sided").pvalue) if len(a) > 1 and len(b) > 1 else float("nan")
    except Exception:
        p = float("nan")
    A, B = np.asarray(a, float), np.asarray(b, float)
    d = float(((B[:, None] > A[None, :]).sum() - (B[:, None] < A[None, :]).sum()) / (len(A) * len(B))) if len(A) and len(B) else float("nan")
    return p, d


def paired_boxes(plt, rows, key, ylabel, title, png, fams):
    """Por familia, dos cajas (reales de prueba, generados) con cada nivel como punto."""
    fig, ax = plt.subplots(figsize=(12, 5.6))
    pos, data, cols, ticks, labels = [], [], [], [], []
    for i, fam in enumerate(fams):
        for j, (grp, col) in enumerate((("prueba", DARK), ("generado", GREEN))):
            p = i * 3 + j + 1
            pos.append(p); data.append(vals(rows, fam, grp, key)); cols.append(col)
        ticks.append(i * 3 + 1.5); labels.append(FAM_LABEL[fam])
    bp = ax.boxplot(data, positions=pos, widths=0.7, patch_artist=True, showfliers=False,
                    medianprops=dict(color="white", lw=2.5))
    for patch, c in zip(bp["boxes"], cols):
        patch.set_facecolor(c); patch.set_edgecolor(EDGE); patch.set_alpha(0.9)
    rng = np.random.default_rng(0)
    for p, d in zip(pos, data):
        ax.scatter(p + rng.uniform(-0.18, 0.18, len(d)), d, s=26, color="black", alpha=0.55, zorder=3)
        if d:
            ax.text(p, ax.get_ylim()[1] if False else max(max(dd) for dd in data if dd) * 1.04,
                    "mediana\n" + f"{np.median(d):.1f}".replace(".", ","), ha="center", va="bottom", fontsize=12, color="#333333")
    ax.set_xticks(ticks, labels)
    ax.set_ylabel(ylabel)
    ax.set_title(title, loc="left", pad=48)
    from matplotlib.patches import Patch
    ax.legend([Patch(color=DARK), Patch(color=GREEN)], ["Reales de prueba", "Generados"],
              frameon=False, loc="upper right", bbox_to_anchor=(1, 1.22), ncol=2)
    top = max(max(d) for d in data if d)
    ax.set_ylim(bottom=min(0, min(min(d) for d in data if d)), top=top * 1.22)
    fig.tight_layout()
    fig.savefig(png, dpi=150); plt.close(fig)


def times_plot(plt, gen, png, fams):
    fig, ax = plt.subplots(figsize=(12, 5.2))
    styles = {"agua": (DARK, "o"), "sin_agua": (GREEN, "s")}
    for fam in fams:
        t = [g["tiempo_s"] for g in gen if g["familia"] == fam]
        if not t:
            continue
        c, mk = styles[fam]
        m, sd = float(np.mean(t)), float(np.std(t, ddof=1)) if len(t) > 1 else 0.0
        ax.plot(range(1, len(t) + 1), t, "-" + mk, color=c, ms=7, lw=2, mec=EDGE,
                label=f"{FAM_LABEL[fam]}: " + f"{m:.1f} s ± {sd:.1f} s".replace(".", ","))
        ax.axhline(m, color=c, ls="--", lw=1.3)
    n = max(sum(1 for g in gen if g["familia"] == f) for f in fams)
    ax.set_xticks(range(1, n + 1))
    ax.set_xlabel("Nivel generado (en orden)")
    ax.set_ylabel("Segundos por nivel")
    ax.set_ylim(0, max(g["tiempo_s"] for g in gen if g["familia"] in fams) * 1.15)
    ax.set_title("Tiempo de generación de cada nivel", loc="left")
    ax.legend(frameon=False, loc="lower right")
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout(); fig.savefig(png, dpi=150); plt.close(fig)


def perf_plot(plt, perf_csv, exp, png):
    """FPS promedio y del 1 % más lento por nivel, reales vs generados."""
    key = {}
    kf = exp / "prueba_ciega" / "clave_NO_ABRIR.csv"
    if kf.exists():
        with open(kf, encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                key[r["codigo"]] = r["origen"]
    rep = defaultdict(list)
    with open(perf_csv, encoding="utf-8-sig") as fh:
        skipped = 0
        for r in csv.DictReader(fh):
            if (r.get("completa") or "si").strip().lower() == "no":
                skipped += 1          # mediciones detenidas antes de tiempo
                continue
            rep[r["nivel"].strip()].append(r)
        if skipped:
            print(f"Se omitieron {skipped} mediciones incompletas (Play detenido antes de tiempo).")

    def origin(name):
        if name in key:
            return key[name]
        return "generado" if name.lower().startswith("gen_") else "real"

    levels = []
    for name, rs in rep.items():
        f = lambda c: float(np.mean([float(x[c]) for x in rs if x.get(c) not in (None, "", "-1", "-1.00")] or [float("nan")]))
        levels.append({"nivel": name, "origen": origin(name), "n": len(rs), "fps": f("fps_promedio"),
                       "fps1": f("fps_1pct_bajo"), "ram": f("ram_asignada_max_mb"), "gpu": f("ms_gpu_promedio")})
    levels.sort(key=lambda l: (l["origen"] != "real", l["nivel"]))
    if not levels:
        return None
    fig, ax = plt.subplots(figsize=(12, 5.4))
    x = np.arange(len(levels))
    colors = [DARK if l["origen"] == "real" else GREEN for l in levels]
    ax.bar(x, [l["fps"] for l in levels], color=colors, edgecolor=EDGE, width=0.7, label="FPS promedio")
    ax.scatter(x, [l["fps1"] for l in levels], color="black", marker="_", s=380, lw=2.5, zorder=3,
               label="FPS del 1 % más lento")
    ax.set_xticks(x, [l["nivel"] for l in levels], rotation=60, ha="right", fontsize=11)
    ax.set_ylabel("Cuadros por segundo")
    ax.set_title("Rendimiento en Unity por nivel (promedio de las repeticiones)", loc="left")
    from matplotlib.patches import Patch
    from matplotlib.lines import Line2D
    ax.legend([Patch(color=DARK), Patch(color=GREEN), Line2D([], [], color="black", lw=2.5)],
              ["Reales", "Generados", "FPS del 1 % más lento"], frameon=False, loc="upper right", ncol=3)
    ax.set_ylim(0, max(l["fps"] for l in levels) * 1.25)
    fig.tight_layout(); fig.savefig(png, dpi=150); plt.close(fig)
    return levels


def fmt(v, d=1):
    return "–" if v is None or (isinstance(v, float) and math.isnan(v)) else f"{v:.{d}f}".replace(".", ",")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("experimento")
    ap.add_argument("--rendimiento", default=None, help="rendimiento.csv de PCGPerfRecorder")
    args = ap.parse_args()
    exp = Path(args.experimento)
    out = exp / "diapositivas"; out.mkdir(exist_ok=True)
    plt = setup()
    rows = load_rows(exp)
    fams = [f for f in ("agua", "sin_agua") if any(r["familia"] == f for r in rows)]
    md = ["# Números para las diapositivas de resultados\n",
          "Mediana = valor del nivel del medio. p = Mann-Whitney (< 0,05: diferencia significativa). "
          "δ = delta de Cliff, generados frente a reales (|δ| < 0,15 despreciable, < 0,33 pequeña, < 0,47 mediana).\n"]

    # 1) validez
    paired_boxes(plt, rows, "pares_atravesados", "Pares de objetos atravesados por nivel",
                 "Validez: objetos que se atraviesan", out / "1_validez.png", fams)
    md.append("## 1. Validez (1_validez.png)\n")
    md.append("| Familia | Reales: mediana | Generados: mediana | Generados con 0 atravesados | p | δ |")
    md.append("|---|---|---|---|---|---|")
    for fam in fams:
        a, b = vals(rows, fam, "prueba", "pares_atravesados"), vals(rows, fam, "generado", "pares_atravesados")
        p, d = mw_cliff(a, b)
        z = sum(1 for v in b if v == 0)
        md.append(f"| {FAM_LABEL[fam]} | {fmt(float(np.median(a)))} | {fmt(float(np.median(b)))} | "
                  f"{z} de {len(b)} ({100 * z / len(b):.0f} %) | {fmt(p, 3)} | {fmt(d, 2)} |")

    # 2) variabilidad
    paired_boxes(plt, rows, "novedad", "Distancia al nivel de ajuste más parecido",
                 "Variabilidad: novedad (0 = copia)", out / "2_variabilidad.png", fams)
    md.append("\n## 2. Variabilidad (2_variabilidad.png)\n")
    md.append("| Familia | Reales: mediana | Generados: mediana | p | δ |")
    md.append("|---|---|---|---|---|")
    for fam in fams:
        a, b = vals(rows, fam, "prueba", "novedad"), vals(rows, fam, "generado", "novedad")
        p, d = mw_cliff(a, b)
        md.append(f"| {FAM_LABEL[fam]} | {fmt(float(np.median(a)), 2)} | {fmt(float(np.median(b)), 2)} | {fmt(p, 3)} | {fmt(d, 2)} |")
    rs = exp / "resumen.csv"
    if rs.exists():
        with open(rs, encoding="utf-8") as fh:
            div = [r for r in csv.DictReader(fh) if r["metrica"] == "diversidad"]
        if div:
            md.append("\nDiversidad (distancia promedio entre niveles del mismo grupo):\n")
            for r in div:
                md.append(f"- {FAM_LABEL.get(r['familia'], r['familia'])}: reales {fmt(float(r['real_media']), 2)}, "
                          f"generados {fmt(float(r['gen_media']), 2)}")

    # 3) tiempo
    man = json.loads((exp / "manifiesto.json").read_text(encoding="utf-8"))
    gen = man.get("generados", [])
    if gen:
        times_plot(plt, gen, out / "3_tiempo.png", fams)
        md.append("\n## 3. Tiempo de generación (3_tiempo.png)\n")
        md.append("| Familia | Media | Desviación | Mínimo | Máximo | n |")
        md.append("|---|---|---|---|---|---|")
        for fam in fams:
            t = [g["tiempo_s"] for g in gen if g["familia"] == fam]
            md.append(f"| {FAM_LABEL[fam]} | {fmt(float(np.mean(t)))} s | {fmt(float(np.std(t, ddof=1)))} s | "
                      f"{fmt(min(t))} s | {fmt(max(t))} s | {len(t)} |")
        w = man.get("parametros", {}).get("workers", 1)
        if w and w > 1:
            md.append(f"\nAVISO: corrido con --workers {w}; los tiempos están inflados por la generación en paralelo.")

    # 4) rendimiento
    if args.rendimiento and Path(args.rendimiento).exists():
        levels = perf_plot(plt, args.rendimiento, exp, out / "4_rendimiento.png")
        if levels:
            md.append("\n## 4. Rendimiento en Unity (4_rendimiento.png)\n")
            md.append("| Grupo | Niveles | FPS promedio | FPS 1 % más lento | RAM máx. (MB) | GPU (ms) |")
            md.append("|---|---|---|---|---|---|")
            for g in ("real", "generado"):
                L = [l for l in levels if l["origen"] == g]
                if L:
                    m = lambda k: float(np.nanmean([l[k] for l in L]))
                    md.append(f"| {'Reales' if g == 'real' else 'Generados'} | {len(L)} | {fmt(m('fps'))} | "
                              f"{fmt(m('fps1'))} | {fmt(m('ram'), 0)} | {fmt(m('gpu'), 2)} |")
    else:
        md.append("\n## 4. Rendimiento en Unity\n\nPendiente: correr con --rendimiento y el CSV de PCGPerfRecorder.")

    # 5) similitud
    rp = exp / "figuras" / "relaciones_por_par.png"
    if rp.exists():
        shutil.copy(rp, out / "5_similitud.png")
        md.append("\n## 5. Similitud (5_similitud.png)\n\nVer la tabla «Relaciones por par de tipos» de resumen.md (ρ generados y ρ referencia).")

    (out / "numeros.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))
    print(f"\nGráficas en {out}")


if __name__ == "__main__":
    main()
