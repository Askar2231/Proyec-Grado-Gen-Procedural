import argparse
import csv
import hashlib
import json
import math
import platform
import random
import sys
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import fit_statistics as fs            # noqa: E402
import fit_families as ff              # noqa: E402
import generate_level as gl            # noqa: E402
import evaluate_generation as ev       # noqa: E402
import spatial_relations as sr         # noqa: E402

BRIDGE_TAGS = ("Puente", "Untagged")
FAMILIES = ("agua", "sin_agua")
FAM_LABEL = {"agua": "Con río", "sin_agua": "Sin río"}
RASTER = 0.25          # tamaño de celda (m) para medir áreas
CROSS_TOL = 0.5        # tolerancia (m) para decir que un puente cruza el río
LINK_DIST = 2.0        # distancia (m) desde el extremo de un puente a la que debe haber un Camino

METRICS = [            # (columna, nombre legible, decimales)
    ("objetos", "Objetos por nivel", 0),
    ("pares_atravesados", "Pares de objetos atravesados", 2),
    ("perdida_estadistica", "Pérdida estadística", 1),
    ("novedad", "Novedad (distancia al nivel de ajuste más parecido)", 2),
    ("densidad_ocupacion", "Densidad de ocupación", 3),
    ("fraccion_agua", "Fracción de agua", 3),
    ("puentes_sobre_agua", "Puentes que tocan el agua", 2),
    ("puentes_que_cruzan", "Puentes que cruzan el río", 2),
    ("puentes_conectados", "Puentes con camino en ambos extremos", 2),
    ("rel_cerca_por_objeto", "Relaciones de cercanía por objeto", 2),
    ("rel_apilado_por_objeto", "Relaciones de apilamiento por objeto", 3),
    ("rel_lateral_por_objeto", "Relaciones laterales por objeto", 2),
    ("rel_frontal_por_objeto", "Relaciones frontales por objeto", 2),
]


# --------------------------------------------------------------------------- #
# Utilidades
# --------------------------------------------------------------------------- #
def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def tag_of(o):
    return o["tag"] if o.get("tag") else "Untagged"


def centered(scene):
    """Copia del nivel con su caja envolvente centrada en (0, 0)."""
    s = json.loads(json.dumps(scene))
    c = ev.center(s)
    for o in s["objects"]:
        o["boundsCenter"]["x"] -= c[0]
        o["boundsCenter"]["z"] -= c[1]
    return s


def footprints(scene, pred):
    """Rectángulos (xmin, xmax, zmin, zmax) en planta de los objetos que cumplen pred."""
    out = []
    for o in scene["objects"]:
        if pred(o):
            c, s = o["boundsCenter"], o["boundsSize"]
            out.append((c["x"] - s["x"] / 2, c["x"] + s["x"] / 2, c["z"] - s["z"] / 2, c["z"] + s["z"] / 2))
    return out


def level_bbox(scene):
    r = footprints(scene, lambda o: True)
    return min(a[0] for a in r), max(a[1] for a in r), min(a[2] for a in r), max(a[3] for a in r)


def union_fraction(rects, bbox):
    """Fracción del área de bbox cubierta por la unión de los rectángulos (rasterizado)."""
    x0, x1, z0, z1 = bbox
    nx = max(1, int(math.ceil((x1 - x0) / RASTER)))
    nz = max(1, int(math.ceil((z1 - z0) / RASTER)))
    grid = np.zeros((nx, nz), dtype=bool)
    for a, b, c, d in rects:
        i0 = int(np.clip(math.floor((a - x0) / RASTER), 0, nx)); i1 = int(np.clip(math.ceil((b - x0) / RASTER), 0, nx))
        j0 = int(np.clip(math.floor((c - z0) / RASTER), 0, nz)); j1 = int(np.clip(math.ceil((d - z0) / RASTER), 0, nz))
        grid[i0:i1, j0:j1] = True
    return float(grid.mean())


def overlap(r1, r2):
    return min(r1[1], r2[1]) > max(r1[0], r2[0]) and min(r1[3], r2[3]) > max(r1[2], r2[2])


def bridge_metrics(scene):
    """Fracción de puentes que tocan el agua, que la cruzan de orilla a orilla y que
    tienen un Camino junto a sus DOS extremos (llevan de un camino a otro)."""
    water = footprints(scene, lambda o: tag_of(o) == "Water")
    bridges = footprints(scene, lambda o: tag_of(o) in BRIDGE_TAGS)
    paths = footprints(scene, lambda o: tag_of(o) == "Camino")
    if not water or not bridges:
        return float("nan"), float("nan"), float("nan")
    xs = [((w[0] + w[1]) / 2) for w in water]; zs = [((w[2] + w[3]) / 2) for w in water]
    along_x = (max(xs) - min(xs)) >= (max(zs) - min(zs))   # el río corre a lo largo de X
    touch = cross = linked = 0
    for b in bridges:
        # zonas junto a cada extremo del puente, en la dirección en que cruza el río
        if along_x:
            ends = [(b[0], b[1], b[2] - LINK_DIST, b[2]), (b[0], b[1], b[3], b[3] + LINK_DIST)]
        else:
            ends = [(b[0] - LINK_DIST, b[0], b[2], b[3]), (b[1], b[1] + LINK_DIST, b[2], b[3])]
        if paths and all(any(overlap(e, p) for p in paths) for e in ends):
            linked += 1
        hits = [w for w in water if overlap(b, w)]
        if not hits:
            continue
        touch += 1
        if along_x:   # se cruza en Z
            lo, hi = min(w[2] for w in hits), max(w[3] for w in hits)
            cross += (b[2] <= lo + CROSS_TOL) and (b[3] >= hi - CROSS_TOL)
        else:
            lo, hi = min(w[0] for w in hits), max(w[1] for w in hits)
            cross += (b[0] <= lo + CROSS_TOL) and (b[1] >= hi - CROSS_TOL)
    nb = len(bridges)
    return touch / nb, cross / nb, (linked / nb if paths else float("nan"))


def relation_metrics(scene):
    """Relaciones espaciales por objeto, con el mismo cálculo que SpatialRelationBuilder.cs."""
    rels = sr.spatial_relations(scene["objects"])
    n = max(1, len(scene["objects"]))
    c = Counter()
    for _, _, r, v in rels:
        if r == sr.NEAR:
            if v >= 0.5:          # hueco entre cajas menor que 1 unidad
                c["cerca"] += 1
        elif r in (sr.ABOVE, sr.BELOW):
            c["apilado"] += 1
        elif r in (sr.LEFTOF, sr.RIGHTOF):
            c["lateral"] += 1
        elif r in (sr.INFRONTOF, sr.BEHIND):
            c["frontal"] += 1
    return {f"rel_{k}_por_objeto": c[k] / n for k in ("cerca", "apilado", "lateral", "frontal")}


def level_metrics(model, scene, train_sigs):
    sc = centered(scene)
    tag_idx, pos, ext, ycen = ev.arrays_from_scene(model, sc)
    loss, n_pairs = ev.stat_loss(model, tag_idx, pos, ext, ycen)
    sig = ev.signature(model, tag_idx, pos)
    nov = min(float(np.abs(sig - t).sum()) for t in train_sigs) if train_sigs else float("nan")
    bbox = level_bbox(sc)
    on, cr, ln = bridge_metrics(sc)
    m = {"objetos": len(sc["objects"]),
         "pares_atravesados": n_pairs,
         "perdida_estadistica": loss,
         "novedad": nov,
         "densidad_ocupacion": union_fraction(footprints(sc, lambda o: tag_of(o) != "Water"), bbox),
         "fraccion_agua": union_fraction(footprints(sc, lambda o: tag_of(o) == "Water"), bbox),
         "puentes_sobre_agua": on,
         "puentes_que_cruzan": cr,
         "puentes_conectados": ln,
         "ancho": bbox[1] - bbox[0], "largo": bbox[3] - bbox[2]}
    m.update(relation_metrics(sc))
    return m, sig


# --------------------------------------------------------------------------- #
# Generación (una tarea por nivel, con su propia semilla)
# --------------------------------------------------------------------------- #
def _generate_one(args):
    model_path, fam, k, seed, iters, out_dir = args
    model = gl.Model(model_path)
    rng = np.random.default_rng([seed, FAMILIES.index(fam), k])
    t0 = time.perf_counter()
    lv = gl.Level(model, rng)
    lv.anneal(iters, verbose=False)
    t1 = time.perf_counter()
    scene = lv.to_scene(f"gen_{fam}_s{seed}_{k:03d}")
    path = Path(out_dir) / f"{scene['levelId']}.json"
    path.write_text(json.dumps(scene), encoding="utf-8")
    t2 = time.perf_counter()
    return {"archivo": path.name, "familia": fam, "tiempo_s": t2 - t0, "tiempo_recocido_s": t1 - t0,
            "perdida_final": lv.loss(), "penetracion_final": lv.pen}


# --------------------------------------------------------------------------- #
# Estadística
# --------------------------------------------------------------------------- #
def cliffs_delta(a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    if len(a) == 0 or len(b) == 0:
        return float("nan")
    gt = (a[:, None] > b[None, :]).sum(); lt = (a[:, None] < b[None, :]).sum()
    return float((gt - lt) / (len(a) * len(b)))


def mann_whitney(a, b):
    try:
        from scipy.stats import mannwhitneyu
    except ImportError:
        return float("nan")
    a = [v for v in a if not math.isnan(v)]; b = [v for v in b if not math.isnan(v)]
    if len(a) < 2 or len(b) < 2 or (len(set(a)) == 1 and set(a) == set(b)):
        return float("nan")
    return float(mannwhitneyu(a, b, alternative="two-sided").pvalue)


def describe(v):
    v = [x for x in v if not (isinstance(x, float) and math.isnan(x))]
    if not v:
        return {"n": 0, "media": float("nan"), "de": float("nan"), "mediana": float("nan"),
                "min": float("nan"), "max": float("nan")}
    a = np.asarray(v, float)
    return {"n": len(a), "media": float(a.mean()), "de": float(a.std(ddof=1)) if len(a) > 1 else 0.0,
            "mediana": float(np.median(a)), "min": float(a.min()), "max": float(a.max())}


def diversity(sigs):
    if len(sigs) < 2:
        return float("nan")
    d = [float(np.abs(sigs[i] - sigs[j]).sum()) for i in range(len(sigs)) for j in range(i + 1, len(sigs))]
    return float(np.mean(d))


# --------------------------------------------------------------------------- #
# Figuras
# --------------------------------------------------------------------------- #
def figures(out, model_by_fam, rows, scenes, gen_times):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle
    figdir = out / "figuras"; figdir.mkdir(exist_ok=True)
    COL = {"prueba": "#4c78a8", "generado": "#f58518"}

    # vistas superiores: 3 reales de prueba y 3 generados por familia
    for fam, model in model_by_fam.items():
        tests = [s for s in scenes if s[1] == fam and s[2] == "prueba"][:3]
        gens = [s for s in scenes if s[1] == fam and s[2] == "generado"][:3]
        allsc = tests + gens
        if not allsc:
            continue
        cmap = plt.get_cmap("tab20")
        ncol = max(len(tests), len(gens))
        fig, axes = plt.subplots(2, ncol, figsize=(5.2 * ncol, 9.0), squeeze=False)
        W = max(model.zone[0], max(r["ancho"] for r in rows if r["familia"] == fam)) * 0.55
        L = max(model.zone[1], max(r["largo"] for r in rows if r["familia"] == fam)) * 0.55
        for r, group in enumerate((tests, gens)):
            for c in range(ncol):
                ax = axes[r][c]; ax.set_xticks([]); ax.set_yticks([])
                if c >= len(group):
                    ax.axis("off"); continue
                name, _, kind, sc = group[c]
                sc = centered(sc)
                for o in sc["objects"]:
                    t = tag_of(o)
                    col = cmap(model.tix.get(t, 0) % 20)
                    x, z = o["boundsCenter"]["x"], o["boundsCenter"]["z"]
                    w, d = o["boundsSize"]["x"], o["boundsSize"]["z"]
                    ax.add_patch(Rectangle((x - w / 2, z - d / 2), w, d, fc=col, ec="k", lw=0.25, alpha=0.85))
                ax.set_xlim(-W, W); ax.set_ylim(-L, L); ax.set_aspect("equal")
                ax.set_title(("Real (prueba): " if kind == "prueba" else "Generado: ") + name.replace(".json", ""), fontsize=10)
        handles = [Rectangle((0, 0), 1, 1, fc=cmap(model.tix[t] % 20), ec="k") for t in model.tags]
        fig.legend(handles, model.tags, loc="lower center", ncol=min(7, len(handles)), fontsize=9, frameon=False)
        fig.suptitle(f"{FAM_LABEL[fam]}: niveles reales de prueba (arriba) y generados (abajo)", fontsize=13)
        fig.tight_layout(rect=(0, 0.06, 1, 0.97))
        fig.savefig(figdir / f"vistas_{fam}.png", dpi=130); plt.close(fig)

    # cajas por métrica
    keys = [k for k, _, _ in METRICS if k != "objetos"]
    for fam in model_by_fam:
        ks = [k for k in keys if any(not math.isnan(float(r[k])) for r in rows if r["familia"] == fam)]
        n = len(ks); nc = 4; nr = math.ceil(n / nc)
        fig, axes = plt.subplots(nr, nc, figsize=(4.2 * nc, 3.4 * nr), squeeze=False)
        for i, k in enumerate(ks):
            ax = axes[i // nc][i % nc]
            data = [[float(r[k]) for r in rows if r["familia"] == fam and r["grupo"] == g and not math.isnan(float(r[k]))]
                    for g in ("prueba", "generado")]
            bp = ax.boxplot(data, patch_artist=True, widths=0.55)
            ax.set_xticks([1, 2], ["Reales\n(prueba)", "Generados"])
            for patch, g in zip(bp["boxes"], ("prueba", "generado")):
                patch.set_facecolor(COL[g]); patch.set_alpha(0.55)
            for j, d in enumerate(data):
                ax.scatter(np.full(len(d), j + 1) + np.random.default_rng(0).uniform(-0.12, 0.12, len(d)), d, s=10, c="k", alpha=0.6, zorder=3)
            ax.set_title(dict((a, b) for a, b, _ in METRICS)[k], fontsize=9.5)
        for j in range(n, nr * nc):
            axes[j // nc][j % nc].axis("off")
        fig.suptitle(f"{FAM_LABEL[fam]}: métricas de los niveles reales de prueba y de los generados", fontsize=13)
        fig.tight_layout(rect=(0, 0, 1, 0.96))
        fig.savefig(figdir / f"metricas_{fam}.png", dpi=130); plt.close(fig)

    # relaciones por objeto
    rk = ["rel_cerca_por_objeto", "rel_apilado_por_objeto", "rel_lateral_por_objeto", "rel_frontal_por_objeto"]
    labels = ["Cercanía", "Apilamiento", "Laterales", "Frontales"]
    fams = list(model_by_fam)
    fig, axes = plt.subplots(1, len(fams), figsize=(6.5 * len(fams), 4.2), squeeze=False)
    for ax, fam in zip(axes[0], fams):
        x = np.arange(len(rk)); w = 0.38
        for j, g in enumerate(("prueba", "generado")):
            vals = [[float(r[k]) for r in rows if r["familia"] == fam and r["grupo"] == g] for k in rk]
            m = [np.mean(v) if v else 0 for v in vals]; e = [np.std(v, ddof=1) if len(v) > 1 else 0 for v in vals]
            ax.bar(x + (j - 0.5) * w, m, w, yerr=e, capsize=3, color=COL[g], alpha=0.8,
                   label="Reales (prueba)" if g == "prueba" else "Generados")
        ax.set_xticks(x, labels); ax.set_ylabel("Relaciones por objeto"); ax.set_title(FAM_LABEL[fam])
        ax.legend(frameon=False)
    fig.tight_layout(); fig.savefig(figdir / "relaciones.png", dpi=130); plt.close(fig)

    # tiempos
    if gen_times:
        fig, ax = plt.subplots(figsize=(6.5, 3.8))
        for fam in fams:
            t = [g["tiempo_s"] for g in gen_times if g["familia"] == fam]
            if t:
                ax.hist(t, bins=12, alpha=0.6, label=FAM_LABEL[fam])
        ax.set_xlabel("Segundos por nivel"); ax.set_ylabel("Niveles"); ax.legend(frameon=False)
        ax.set_title("Tiempo de generación por nivel")
        fig.tight_layout(); fig.savefig(figdir / "tiempos.png", dpi=130); plt.close(fig)


# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder", help="carpeta con los level_*.json exportados de Unity")
    ap.add_argument("--out", default="experimento")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--test-frac", type=float, default=0.2, help="fracción de niveles reales para prueba")
    ap.add_argument("--n-gen", type=int, default=20, help="niveles a generar por familia")
    ap.add_argument("--iters", type=int, default=60000, help="iteraciones del recocido simulado")
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--blind", type=int, default=10, help="niveles de cada tipo para la prueba ciega (0 = no)")
    args = ap.parse_args()

    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    started = datetime.now()
    print(f"Experimento -> {out.resolve()}")

    # ---- 1) leer y dividir --------------------------------------------------
    levels = fs.load_levels(args.folder)
    levels = [l for l in levels if l.get("objects")]
    all_tags = sorted({tag_of(o) for l in levels for o in l["objects"]})
    by_fam = {f: sorted([l for l in levels if ff.family_of(l) == f], key=lambda l: l["_file"]) for f in FAMILIES}
    rng = random.Random(args.seed)
    split = {}
    for fam, lv in by_fam.items():
        names = [l["_file"] for l in lv]
        rng.shuffle(names)
        n_test = int(round(len(names) * args.test_frac)) if len(names) >= 2 else 0
        n_test = max(1, n_test) if len(names) >= 2 else 0
        for i, n in enumerate(names):
            split[n] = "prueba" if i < n_test else "ajuste"
    with open(out / "division.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh); w.writerow(["archivo", "familia", "conjunto", "objetos"])
        for l in sorted(levels, key=lambda l: l["_file"]):
            w.writerow([l["_file"], ff.family_of(l), split[l["_file"]], len(l["objects"])])
    for fam in FAMILIES:
        a = sum(1 for l in by_fam[fam] if split[l["_file"]] == "ajuste")
        p = sum(1 for l in by_fam[fam] if split[l["_file"]] == "prueba")
        print(f"  {FAM_LABEL[fam]:8s}: {a} de ajuste, {p} de prueba")

    # ---- 2) ajustar con AJUSTE ----------------------------------------------
    train = [l for l in levels if split[l["_file"]] == "ajuste"]
    model_paths = ff.fit_models(train, out / "modelos", all_tags=all_tags, verbose=False)
    model_by_fam = {f: gl.Model(p) for f, p in model_paths.items()}
    print(f"  Modelos ajustados: {', '.join(model_paths)}")

    # ---- 3) generar ----------------------------------------------------------
    gdir = out / "generados"; gdir.mkdir(exist_ok=True)
    tasks = [(str(model_paths[f]), f, k, args.seed, args.iters, str(gdir))
             for f in model_paths for k in range(args.n_gen)]
    print(f"  Generando {len(tasks)} niveles ({args.iters} iteraciones, {args.workers} proceso(s))...")
    gen_times = []
    if args.workers > 1:
        with ProcessPoolExecutor(max_workers=args.workers) as ex:
            for i, r in enumerate(ex.map(_generate_one, tasks)):
                gen_times.append(r); print(f"    {i+1}/{len(tasks)} {r['archivo']}  {r['tiempo_s']:.1f} s")
    else:
        for i, t in enumerate(tasks):
            r = _generate_one(t); gen_times.append(r)
            print(f"    {i+1}/{len(tasks)} {r['archivo']}  {r['tiempo_s']:.1f} s")

    # ---- 4) medir --------------------------------------------------------------
    print("  Midiendo niveles...")
    rows, scenes, sigs = [], [], {}
    for fam, model in model_by_fam.items():
        train_sigs = []
        for l in by_fam[fam]:
            if split[l["_file"]] == "ajuste":
                sc = centered(l)
                ti, pos, _, _ = ev.arrays_from_scene(model, sc)
                train_sigs.append(ev.signature(model, ti, pos))
        groups = [("prueba", [(l["_file"], l) for l in by_fam[fam] if split[l["_file"]] == "prueba"])]
        gens = [(g["archivo"], json.loads((gdir / g["archivo"]).read_text(encoding="utf-8")))
                for g in gen_times if g["familia"] == fam]
        groups.append(("generado", gens))
        tmap = {g["archivo"]: g for g in gen_times}
        for grp, items in groups:
            for name, scene in items:
                m, sig = level_metrics(model, scene, train_sigs)
                sigs.setdefault((fam, grp), []).append(sig)
                row = {"archivo": name, "familia": fam, "grupo": grp}
                row.update(m)
                row["tiempo_s"] = tmap[name]["tiempo_s"] if name in tmap else float("nan")
                rows.append(row); scenes.append((name, fam, grp, scene))
    cols = ["archivo", "familia", "grupo", "tiempo_s"] + [k for k, _, _ in METRICS] + ["ancho", "largo"]
    with open(out / "metricas_por_nivel.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore"); w.writeheader()
        for r in rows:
            w.writerow({k: (f"{v:.6g}" if isinstance(v, float) else v) for k, v in r.items()})

    # ---- 5) resumir ------------------------------------------------------------
    summary = []
    for fam in model_by_fam:
        for k, label, dec in [("tiempo_s", "Tiempo de generación (s)", 1)] + METRICS:
            a = [float(r[k]) for r in rows if r["familia"] == fam and r["grupo"] == "prueba"]
            b = [float(r[k]) for r in rows if r["familia"] == fam and r["grupo"] == "generado"]
            da, db = describe(a), describe(b)
            if da["n"] == 0 and db["n"] == 0:
                continue
            aa = [v for v in a if not math.isnan(v)]; bb = [v for v in b if not math.isnan(v)]
            summary.append({"familia": fam, "metrica": k, "nombre": label, "decimales": dec,
                            **{f"real_{x}": da[x] for x in da}, **{f"gen_{x}": db[x] for x in db},
                            "p_mann_whitney": mann_whitney(aa, bb) if da["n"] and db["n"] else float("nan"),
                            "delta_cliff": cliffs_delta(bb, aa) if da["n"] and db["n"] else float("nan")})
        summary.append({"familia": fam, "metrica": "diversidad", "nombre": "Diversidad entre niveles del grupo",
                        "decimales": 2, "real_n": len(sigs.get((fam, "prueba"), [])),
                        "real_media": diversity(sigs.get((fam, "prueba"), [])),
                        "gen_n": len(sigs.get((fam, "generado"), [])),
                        "gen_media": diversity(sigs.get((fam, "generado"), []))})
    scols = ["familia", "metrica", "nombre", "real_n", "real_media", "real_de", "real_mediana", "real_min", "real_max",
             "gen_n", "gen_media", "gen_de", "gen_mediana", "gen_min", "gen_max", "p_mann_whitney", "delta_cliff"]
    with open(out / "resumen.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=scols, extrasaction="ignore"); w.writeheader()
        for s in summary:
            w.writerow({k: (f"{v:.6g}" if isinstance(v, float) else v) for k, v in s.items()})

    def fmt(v, d):
        return "–" if v is None or (isinstance(v, float) and math.isnan(v)) else f"{v:.{d}f}"

    md = [f"# Resumen del experimento\n",
          f"Semilla {args.seed} · {args.n_gen} niveles generados por familia · {args.iters} iteraciones · "
          f"{int(args.test_frac * 100)} % de niveles reales para prueba\n",
          "Reales = niveles hechos a mano que el modelo NO usó para ajustarse. "
          "p = prueba de Mann-Whitney (p < 0,05: diferencia significativa). "
          "δ = delta de Cliff (generados frente a reales; |δ| < 0,15 despreciable, < 0,33 pequeña, < 0,47 mediana, mayor: grande).\n"]
    for fam in model_by_fam:
        md.append(f"\n## {FAM_LABEL[fam]}\n")
        md.append("| Métrica | Reales: media ± DE (n) | Generados: media ± DE (n) | p | δ |")
        md.append("|---|---|---|---|---|")
        for s in summary:
            if s["familia"] != fam:
                continue
            d = s["decimales"]
            if s["metrica"] == "diversidad":
                md.append(f"| {s['nombre']} | {fmt(s['real_media'], d)} ({s['real_n']}) | {fmt(s['gen_media'], d)} ({s['gen_n']}) | | |")
                continue
            ra = f"{fmt(s['real_media'], d)} ± {fmt(s['real_de'], d)} ({s['real_n']})" if s["real_n"] else "–"
            ga = f"{fmt(s['gen_media'], d)} ± {fmt(s['gen_de'], d)} ({s['gen_n']})" if s["gen_n"] else "–"
            md.append(f"| {s['nombre']} | {ra} | {ga} | {fmt(s['p_mann_whitney'], 3)} | {fmt(s['delta_cliff'], 2)} |")
        zero = [r for r in rows if r["familia"] == fam and r["grupo"] == "generado"]
        if zero:
            n0 = sum(1 for r in zero if r["pares_atravesados"] == 0)
            md.append(f"\nNiveles generados sin objetos atravesados: {n0} de {len(zero)} ({100 * n0 / len(zero):.0f} %).")
    (out / "resumen.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    # ---- 6) figuras ------------------------------------------------------------
    figures(out, model_by_fam, rows, scenes, gen_times)

    # ---- 7) prueba ciega ---------------------------------------------------------
    if args.blind > 0:
        bdir = out / "prueba_ciega"; bdir.mkdir(exist_ok=True)
        pool = []
        for fam in model_by_fam:
            reals = [(n, s) for n, f, g, s in scenes if f == fam and g == "prueba"]
            gens = [(n, s) for n, f, g, s in scenes if f == fam and g == "generado"]
            k = min(args.blind, len(reals), len(gens))
            pool += [(n, fam, "real", s) for n, s in reals[:k]] + [(n, fam, "generado", s) for n, s in gens[:k]]
        brng = random.Random(args.seed + 999)
        brng.shuffle(pool)
        with open(bdir / "clave_NO_ABRIR.csv", "w", newline="", encoding="utf-8") as fk, \
             open(bdir / "planilla.csv", "w", newline="", encoding="utf-8") as fp:
            wk, wp = csv.writer(fk), csv.writer(fp)
            wk.writerow(["codigo", "archivo_original", "familia", "origen"])
            wp.writerow(["codigo", "evaluador", "aceptable (si/no)", "calidad (1-5)", "parece hecho a mano (si/no)", "comentario"])
            for i, (name, fam, origin, scene) in enumerate(pool):
                code = f"N{i + 1:02d}"
                s = json.loads(json.dumps(scene)); s["levelId"] = code; s.pop("generated", None); s.pop("family", None)
                (bdir / f"{code}.json").write_text(json.dumps(s), encoding="utf-8")
                wk.writerow([code, name, fam, origin]); wp.writerow([code, "", "", "", "", ""])
        print(f"  Prueba ciega: {len(pool)} niveles en {bdir}")

    # ---- 8) manifiesto -----------------------------------------------------------
    import numpy
    try:
        import scipy
        scipy_v = scipy.__version__
    except ImportError:
        scipy_v = None
    manifest = {
        "fecha_inicio": started.isoformat(timespec="seconds"),
        "fecha_fin": datetime.now().isoformat(timespec="seconds"),
        "parametros": vars(args),
        "equipo": {"sistema": platform.platform(), "procesador": platform.processor(),
                   "python": platform.python_version(), "numpy": numpy.__version__, "scipy": scipy_v},
        "niveles": {l["_file"]: {"familia": ff.family_of(l), "conjunto": split[l["_file"]],
                                 "sha256": sha256(Path(args.folder) / l["_file"])} for l in levels},
        "scripts": {p.name: sha256(p) for p in sorted(HERE.glob("*.py"))
                    if p.name in ("run_experiment.py", "fit_statistics.py", "fit_families.py",
                                  "generate_level.py", "evaluate_generation.py", "spatial_relations.py")},
        "generados": gen_times,
    }
    (out / "manifiesto.json").write_text(json.dumps(manifest, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"\nListo. Resumen: {out / 'resumen.md'}")


if __name__ == "__main__":
    main()
