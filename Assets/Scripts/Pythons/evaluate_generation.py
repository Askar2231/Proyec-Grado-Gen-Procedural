"""
evaluate_generation.py

Compara niveles generados contra niveles reales de la misma familia.

Métricas (por nivel):
  pérdida_estadística  qué tan lejos están sus conteos de vecinos por tipo y rango
                       de distancia de lo que dice el modelo (menor = más parecido).
                       Se calcula igual para los reales: es la línea base.
  pares_atravesados    pares de objetos que se meten uno dentro de otro > 0.3 unid.
  novedad              distancia al nivel real más parecido (cuadrícula 6x4 de
                       posiciones por tipo); si fuera ~0 sería una copia.
Además dibuja la vista desde arriba (PNG) de un generado y un real.

Uso:
    python evaluate_generation.py <model_familia.json> <carpeta_generados> <carpeta_json_reales> <salida_png>
"""
import json
import sys
from pathlib import Path

import numpy as np

import generate_level as gl

NX, NZ = 6, 4


def arrays_from_scene(model, scene):
    objs = scene["objects"]
    tag = [("Untagged" if not o["tag"] else o["tag"]) for o in objs]
    pos = np.array([[o["boundsCenter"]["x"], o["boundsCenter"]["z"]] for o in objs])
    ycen = np.array([o["boundsCenter"]["y"] for o in objs])
    ext = np.array([[o["boundsSize"][k] for k in "xyz"] for o in objs])
    return np.array([model.tix[t] for t in tag]), pos, ext, ycen


def stat_loss(model, tag_idx, pos, ext, ycen):
    n, nt = len(tag_idx), len(model.tags)
    count = np.bincount(tag_idx, minlength=nt).astype(float)
    target = model.npo * count[:, None, None]
    O = np.zeros_like(target)
    pen = 0.0
    for i in range(n):
        gap, p = gl.gaps_and_pen(i, pos, ext, ycen)
        m = np.arange(n) != i
        np.add.at(O, (tag_idx[i], gl.to_bin(gap)[m], tag_idx[m]), 1)
        pen += p[m].sum() / 2
    loss = float((((O - target) ** 2) / (target + 1.0)).sum())
    # pares atravesados (profundidad > tolerancia)
    n_pairs = 0
    for i in range(n):
        _, p = gl.gaps_and_pen(i, pos, ext, ycen)
        n_pairs += int((p[np.arange(n) > i] > 0).sum())
    return loss, n_pairs


def signature(model, tag_idx, pos):
    """Dónde pone cada tipo, normalizado: vector de histogramas 6x4 por tipo."""
    W, L = model.zone
    sig = []
    for t in range(len(model.tags)):
        sel = pos[tag_idx == t]
        h, _, _ = np.histogram2d(sel[:, 0] if len(sel) else [], sel[:, 1] if len(sel) else [],
                                 bins=[NX, NZ], range=[[-W / 2, W / 2], [-L / 2, L / 2]])
        sig.append(h.ravel() / max(h.sum(), 1))
    return np.concatenate(sig)


def center(scene):
    c = np.array([[o["boundsCenter"]["x"], o["boundsCenter"]["z"]] for o in scene["objects"]])
    s = np.array([[o["boundsSize"]["x"], o["boundsSize"]["z"]] for o in scene["objects"]])
    lo, hi = (c - s / 2).min(0), (c + s / 2).max(0)
    return (lo + hi) / 2


def load_scene(path, model):
    s = json.loads(Path(path).read_text(encoding="utf-8"))
    o = center(s)
    for ob in s["objects"]:
        ob["boundsCenter"]["x"] -= o[0]; ob["boundsCenter"]["z"] -= o[1]
    return s


def plot(model, scenes, titles, png):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle
    cmap = plt.get_cmap("tab20")
    fig, axes = plt.subplots(1, len(scenes), figsize=(7 * len(scenes), 5))
    axes = np.atleast_1d(axes)
    for ax, sc, ti in zip(axes, scenes, titles):
        for o in sc["objects"]:
            t = "Untagged" if not o["tag"] else o["tag"]
            c = cmap(model.tix[t] % 20)
            x, z = o["boundsCenter"]["x"], o["boundsCenter"]["z"]
            w, d = o["boundsSize"]["x"], o["boundsSize"]["z"]
            ax.add_patch(Rectangle((x - w / 2, z - d / 2), w, d, fc=c, ec="k", lw=0.3, alpha=0.8))
        ax.set_xlim(-model.zone[0] * 0.6, model.zone[0] * 0.6)
        ax.set_ylim(-model.zone[1] * 0.6, model.zone[1] * 0.6)
        ax.set_aspect("equal"); ax.set_title(ti)
    handles = [Rectangle((0, 0), 1, 1, fc=cmap(model.tix[t] % 20), ec="k") for t in model.tags]
    axes[-1].legend(handles, model.tags, fontsize=7, loc="upper left", bbox_to_anchor=(1.01, 1))
    fig.tight_layout(); fig.savefig(png, dpi=110); plt.close(fig)


def main(model_path, gen_dir, real_dir, png):
    model = gl.Model(model_path)
    fam = model.family
    gens = [load_scene(p, model) for p in sorted(Path(gen_dir).glob(f"gen_{fam}_*.json"))]

    # reales de la familia (los JSON disponibles)
    reals = []
    for p in sorted(Path(real_dir).glob("level_*.json")):
        s = load_scene(p, model)
        if s.get("version") != "0.7":
            continue
        has_water = any(o["tag"] == "Water" for o in s["objects"])
        if (fam == "agua") == has_water:
            reals.append(s)
    print(f"familia {fam}: {len(gens)} generados, {len(reals)} reales (JSON)\n")

    def metrics(sc):
        a = arrays_from_scene(model, sc)
        l, p = stat_loss(model, *a)
        return l, p, signature(model, a[0], a[1])

    R = [metrics(s) for s in reals]
    G = [metrics(s) for s in gens]
    print(f"{'':10s} {'pérdida estadística':>22s} {'pares atravesados':>20s} {'novedad':>10s}")
    for name, rows, others in (("reales", R, R), ("generados", G, R)):
        for k, (l, p, sig) in enumerate(rows):
            d = [np.abs(sig - o[2]).sum() for j, o in enumerate(others) if not (rows is R and j == k)]
            print(f"{name:10s} {l:22.1f} {p:20d} {min(d) if d else float('nan'):10.2f}")
    print(f"\nmedia reales   : pérdida {np.mean([r[0] for r in R]):.1f}  atravesados {np.mean([r[1] for r in R]):.1f}")
    print(f"media generados: pérdida {np.mean([g[0] for g in G]):.1f}  atravesados {np.mean([g[1] for g in G]):.1f}")
    if gens and reals:
        plot(model, [reals[0], gens[0]], [f"real ({reals[0]['levelId']})", f"generado ({gens[0]['levelId']})"], png)
        print(f"imagen: {png}")


if __name__ == "__main__":
    if len(sys.argv) != 5:
        print(__doc__); sys.exit(1)
    main(*sys.argv[1:])
