"""
fit_statistics.py

Ajuste estadístico a partir de los niveles exportados (level_*.json).
No entrena una red: cuenta y promedia lo que se repite en los niveles y lo
guarda en un archivo JSON (el "modelo"), que luego usa el generador.

Uso:
    python fit_statistics.py <carpeta_con_los_json> <modelo_salida.json>
    python fit_statistics.py <carpeta_json> <modelo_salida.json> <dataset.npz> <vocab.json>
        (con los dos últimos, los niveles que NO estén en la carpeta se completan
         desde el npz: sin inclinación, base ni tamaño local, pero con conteos,
         giro, posiciones y relaciones exactas)

Necesita estar junto a spatial_relations.py (reutiliza su geometría, que ya está
validada contra C#). Requiere que los niveles traigan boundsCenter (SceneIR 0.6+).

QUÉ APRENDE
-----------
Por cada TIPO de objeto (su tag; los objetos sin tag cuentan como "Untagged"):
  count      cuántos hay por nivel (la distribución real, nivel por nivel)
  local_size su tamaño SIN rotar. El boundsSize que exporta Unity es una caja
             alineada a los ejes del mundo, que crece cuando el objeto gira; aquí
             se deshace el giro para recuperar el tamaño real del objeto.
  yaw        si el tipo se coloca solo en múltiplos de 90° o con giro libre
  base_y     a qué altura queda la base (casi siempre 0 = apoyado en el suelo)
  position_grid  en qué zonas del nivel suele aparecer (posiciones centradas)

Por cada PAR ORDENADO de tipos (A, B):
  neighbors_per_origin  cuántos objetos B hay, en promedio, alrededor de un
                        objeto A, según el hueco entre cajas (por rangos)
  sector_fractions      si B suele quedar delante, a la derecha, detrás o a la
                        izquierda de A (en el marco local de A)

Todas las posiciones se centran por nivel: cada nivel vive en una zona distinta
de la escena de Unity, y lo único que importa es la disposición dentro de él.
"""

import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

from spatial_relations import (BEHIND, INFRONTOF, LEFTOF, NEAR, RIGHTOF,
                               build_relations)

# Bordes de los rangos de hueco entre cajas (en unidades de Unity).
# rango k = [GAP_EDGES[k], GAP_EDGES[k+1])
GAP_EDGES = [0.0, 0.5, 1.0, 2.0, 4.0, 8.0, 16.0, 32.0, float("inf")]
N_BINS = len(GAP_EDGES) - 1
NEAR_BINS = 3          # rangos 0..2 = hueco < 2: lo que se considera "pegado/cerca"

SECTOR_OF_RELATION = {INFRONTOF: 0, RIGHTOF: 1, BEHIND: 2, LEFTOF: 3}
SECTOR_NAMES = ["front", "right", "behind", "left"]

GRID_NX, GRID_NZ = 6, 4   # cuadrícula para "dónde suele aparecer" cada tipo
N_PERMUTATIONS = 30        # barajadas para el informe de afinidades


# --------------------------------------------------------------------------- #
# Lectura
# --------------------------------------------------------------------------- #
def load_levels(folder):
    levels = []
    for path in sorted(Path(folder).glob("level_*.json")):
        d = json.loads(path.read_text(encoding="utf-8"))
        if not all("boundsCenter" in o for o in d["objects"]):
            print(f"  [omitido] {path.name}: sin boundsCenter (exportado con una versión vieja)")
            continue
        d["_file"] = path.name
        levels.append(d)
    if not levels:
        raise SystemExit("No hay niveles utilizables en la carpeta.")
    return levels


def load_npz_levels(npz_path, vocab_path, skip_ids):
    """Reconstruye niveles desde dataset.npz (para los que no se tienen en JSON).

    Del npz se recupera: tag, posición (pivote, no centro de caja), boundsSize,
    yaw, y las relaciones exactas (matriz de adyacencia). NO se recupera la
    inclinación en X/Z, ni la altura de la base, ni el tamaño local.
    """
    d = np.load(npz_path, allow_pickle=True)
    vocab = json.loads(Path(vocab_path).read_text(encoding="utf-8"))
    inv = {int(k): v for k, v in vocab["id_to_tag"].items()}
    levels = []
    for li, lid in enumerate(d["level_ids"]):
        lid = str(lid)
        if lid in skip_ids:
            continue
        n = int(d["mask"][li].sum())
        f = d["object_features"][li][:n]
        yaw = np.degrees(np.arctan2(f[:, 7], f[:, 8]))
        tags = []
        for tok in f[:, 0].astype(int):
            name = inv.get(int(tok), "Untagged")
            tags.append("Untagged" if name in ("<unknown>", "", None) else name)
        levels.append({"_file": f"{lid} (npz)", "_npz": True, "levelId": lid, "version": "npz",
                       "tags": tags, "pos": f[:, 1:4].astype(np.float64),
                       "size": f[:, 4:7].astype(np.float64), "yaw": yaw,
                       "adj": d["adjacency"][li][:n, :n, :]})
    return levels


def _angle_from_zero(deg):
    return abs(((deg + 180.0) % 360.0) - 180.0)


def level_arrays(level):
    """Pasa un nivel a arrays y lo centra en la zona que ocupa."""
    if level.get("_npz"):
        c, sz = level["pos"], level["size"]
        rot = np.zeros((len(c), 3)); rot[:, 1] = level["yaw"]
        xmin, xmax = (c[:, 0] - sz[:, 0] / 2).min(), (c[:, 0] + sz[:, 0] / 2).max()
        zmin, zmax = (c[:, 2] - sz[:, 2] / 2).min(), (c[:, 2] + sz[:, 2] / 2).max()
        origin = np.array([(xmin + xmax) / 2, 0.0, (zmin + zmax) / 2])
        return {"tags": level["tags"], "center": c - origin, "size": sz, "rot": rot,
                "width": xmax - xmin, "length": zmax - zmin, "objects": None,
                "adj": level["adj"], "npz": True}
    objs = level["objects"]
    tags = [o["tag"] for o in objs]
    c = np.array([[o["boundsCenter"][k] for k in "xyz"] for o in objs], dtype=np.float64)
    s = np.array([[o["boundsSize"][k] for k in "xyz"] for o in objs], dtype=np.float64)
    rot = np.array([[o["transform"]["rotation"][k] for k in "xyz"] for o in objs], dtype=np.float64)

    # Caja que envuelve a todo el nivel (en X y Z) y su centro.
    xmin, xmax = (c[:, 0] - s[:, 0] / 2).min(), (c[:, 0] + s[:, 0] / 2).max()
    zmin, zmax = (c[:, 2] - s[:, 2] / 2).min(), (c[:, 2] + s[:, 2] / 2).max()
    origin = np.array([(xmin + xmax) / 2, 0.0, (zmin + zmax) / 2])

    return {
        "tags": tags, "center": c - origin, "size": s, "rot": rot,
        "width": xmax - xmin, "length": zmax - zmin, "objects": objs,
    }


# --------------------------------------------------------------------------- #
# Tamaño local: deshacer el giro de la caja alineada a los ejes
# --------------------------------------------------------------------------- #
def local_size(size_xyz, rot_xyz):
    """
    Para un objeto girado solo en Y (yaw), la caja de mundo mide:
        x = a|cos| + c|sin|        z = a|sin| + c|cos|
    donde a y c son sus medidas locales. Despejando a y c se recupera el tamaño
    sin rotar. Devuelve None si no se puede: objeto inclinado en X o Z, o yaw
    cerca de 45° (ahí x y z no permiten separar a de c).
    """
    if _angle_from_zero(rot_xyz[0]) > 0.5 or _angle_from_zero(rot_xyz[2]) > 0.5:
        return None
    th = math.radians(rot_xyz[1])
    C, S = abs(math.cos(th)), abs(math.sin(th))
    den = C * C - S * S
    if abs(den) < 0.15:
        return None
    x, y, z = size_xyz
    a = (x * C - z * S) / den
    c = (z * C - x * S) / den
    return (round(a, 2), round(y, 2), round(c, 2))


# --------------------------------------------------------------------------- #
# Estadísticas por tipo
# --------------------------------------------------------------------------- #
def yaw_model(yaws):
    yaws = np.mod(yaws, 360.0)
    near_cardinal = [min(_angle_from_zero(y - k) for k in (0, 90, 180, 270)) <= 1.0 for y in yaws]
    frac = float(np.mean(near_cardinal))
    if frac >= 0.95:
        snapped = [int(round(y / 90.0)) % 4 * 90 for y in yaws]
        cnt = Counter(snapped)
        return {"mode": "cardinal",
                "probs": {str(k): cnt.get(k, 0) / len(yaws) for k in (0, 90, 180, 270)}}
    return {"mode": "free", "cardinal_fraction": round(frac, 3)}


def fit_types(arrs, all_tags, zone_w, zone_l):
    types = {}
    per_level_counts = {t: [] for t in all_tags}
    for a in arrs:
        cnt = Counter(a["tags"])
        for t in all_tags:
            per_level_counts[t].append(cnt.get(t, 0))

    for t in all_tags:
        samples, aabb, yaws, base_y, tilted, pos = [], [], [], [], 0, []
        for a in arrs:
            for i, tag in enumerate(a["tags"]):
                if tag != t:
                    continue
                aabb.append(a["size"][i])
                yaws.append(a["rot"][i][1])
                pos.append((a["center"][i][0], a["center"][i][2]))
                if a.get("npz"):
                    continue   # el npz no trae inclinación, base ni tamaño local
                base_y.append(a["center"][i][1] - a["size"][i][1] / 2)
                if _angle_from_zero(a["rot"][i][0]) > 0.5 or _angle_from_zero(a["rot"][i][2]) > 0.5:
                    tilted += 1
                ls = local_size(a["size"][i], a["rot"][i])
                if ls is not None:
                    samples.append(ls)

        n = len(yaws)
        cnts = per_level_counts[t]

        size_counter = Counter(samples)
        size_list = [[list(k), v] for k, v in size_counter.most_common(30)]
        grid, _, _ = np.histogram2d(
            [p[0] for p in pos], [p[1] for p in pos], bins=[GRID_NX, GRID_NZ],
            range=[[-zone_w / 2, zone_w / 2], [-zone_l / 2, zone_l / 2]])

        types[t] = {
            "total_objects": n,
            "count": {"per_level": cnts, "mean": float(np.mean(cnts)),
                      "min": int(min(cnts)), "max": int(max(cnts)),
                      "levels_present": int(sum(1 for c in cnts if c > 0))},
            "local_size": {"n_valid": len(samples), "n_distinct": len(size_counter),
                           "samples": size_list,
                           "aabb_median": ([float(v) for v in np.median(np.array(aabb), axis=0)] if aabb else [1.0, 1.0, 1.0])},
            "yaw": (yaw_model(np.array(yaws)) if yaws else {"mode": "none"}),
            "base_y": {"mean": float(np.mean(base_y)) if base_y else 0.0,
                       "std": float(np.std(base_y)) if base_y else 0.0},
            "tilted_fraction": round(tilted / n, 3) if n else 0.0,
            "position_grid": {"nx": GRID_NX, "nz": GRID_NZ,
                              "fractions": (grid / max(grid.sum(), 1)).round(4).tolist()},
        }
    return types


# --------------------------------------------------------------------------- #
# Estadísticas por pares de tipos
# --------------------------------------------------------------------------- #
def level_matrices(a):
    """Matrices de hueco entre cajas y de sector (origen -> destino) de un nivel.

    Se sacan de las relaciones que calcula el port (mismas fórmulas que C#):
    el hueco sale de Near (Near = 1 / (1 + hueco)) y el sector de InFrontOf /
    RightOf / Behind / LeftOf.
    """
    if a.get("npz"):
        adj = a["adj"]
        nn = adj.shape[0]
        gap = np.full((nn, nn), np.inf)
        sector = np.full((nn, nn), -1, dtype=np.int8)
        nv = adj[:, :, NEAR]
        m = nv > 0
        gap[m] = np.maximum(1.0 / nv[m] - 1.0, 0.0)
        gap = np.minimum(gap, gap.T)
        for r, k in SECTOR_OF_RELATION.items():
            sector[adj[:, :, r] > 0] = k
        return gap, sector
    objs = a["objects"]
    idx = {o["id"]: i for i, o in enumerate(objs)}
    n = len(objs)
    gap = np.full((n, n), np.inf)
    sector = np.full((n, n), -1, dtype=np.int8)

    for s, t, r, v in build_relations(objs):
        i, j = idx[s], idx[t]
        if r == NEAR:
            g = max(1.0 / v - 1.0, 0.0)
            gap[i, j] = gap[j, i] = g
        elif r in SECTOR_OF_RELATION:
            sector[i, j] = SECTOR_OF_RELATION[r]
    return gap, sector


def fit_pairs(arrs, all_tags, report=True):
    nt = len(all_tags)
    tix = {t: i for i, t in enumerate(all_tags)}
    rng = np.random.default_rng(0)

    neighbors = np.zeros((N_BINS, nt, nt))     # [rango, A, B]
    sectors = np.zeros((4, nt, nt))            # [sector, A, B]
    origin_count = np.zeros(nt)
    near_obs = np.zeros((nt, nt))
    near_null = np.zeros((nt, nt))

    for a in arrs:
        gap, sector = level_matrices(a)
        n = len(a["tags"])
        T = np.zeros((n, nt))
        for i, tag in enumerate(a["tags"]):
            T[i, tix[tag]] = 1.0
        origin_count += T.sum(axis=0)

        off = ~np.eye(n, dtype=bool)
        bin_idx = np.clip(np.searchsorted(GAP_EDGES, gap, side="right") - 1, 0, N_BINS - 1)

        for k in range(N_BINS):
            Mk = ((bin_idx == k) & off).astype(np.float64)
            neighbors[k] += T.T @ Mk @ T
        for k in range(4):
            Sk = (sector == k).astype(np.float64)
            sectors[k] += T.T @ Sk @ T

        # Afinidad: ¿los tipos quedan cerca más (o menos) de lo que daría el azar?
        # Nulo = barajar los tags entre las posiciones reales del mismo nivel.
        near_mask = ((bin_idx < NEAR_BINS) & off).astype(np.float64)
        near_obs += T.T @ near_mask @ T
        for _ in range(N_PERMUTATIONS):
            Tp = T[rng.permutation(n)]
            near_null += (Tp.T @ near_mask @ Tp) / N_PERMUTATIONS

    pairs = {}
    for A in all_tags:
        for B in all_tags:
            i, j = tix[A], tix[B]
            sec = sectors[:, i, j]
            pairs[f"{A}|{B}"] = {
                "origin_objects": int(origin_count[i]),
                "neighbors_per_origin": [round(float(neighbors[k, i, j] / max(origin_count[i], 1)), 5)
                                         for k in range(N_BINS)],
                "sector_counts": [int(v) for v in sec],
                "sector_fractions": ([round(float(v / sec.sum()), 4) for v in sec]
                                     if sec.sum() > 0 else None),
            }

    affinity = []
    for i in range(nt):
        for j in range(i, nt):
            obs = near_obs[i, j] + (near_obs[j, i] if i != j else 0)
            exp = near_null[i, j] + (near_null[j, i] if i != j else 0)
            if exp >= 10:
                affinity.append((all_tags[i], all_tags[j], obs, exp, obs / exp))
    return pairs, affinity


# --------------------------------------------------------------------------- #
# Informe legible
# --------------------------------------------------------------------------- #
def print_report(levels, types, zone, affinity):
    print(f"\nNiveles usados: {len(levels)}")
    print(f"Zona por nivel (mediana): {zone['width_median']:.1f} x {zone['length_median']:.1f} unidades")

    print("\nPor tipo de objeto:")
    print(f"  {'tag':11s} {'por nivel (media, rango)':26s} {'tamaño local típico':24s} {'giro':22s} {'base y'}")
    for t, d in types.items():
        c = d["count"]
        s = d["local_size"]["samples"]
        size = "-" if not s else "x".join(f"{v:g}" for v in s[0][0])
        if s and d["local_size"]["n_distinct"] > 1:
            size += f" (+{d['local_size']['n_distinct'] - 1} más)"
        y = d["yaw"]
        yaw = "solo múltiplos de 90°" if y["mode"] == "cardinal" else f"libre ({y['cardinal_fraction']*100:.0f}% en 90°)"
        extra = f"  [{d['tilted_fraction']*100:.0f}% inclinados]" if d["tilted_fraction"] > 0 else ""
        print(f"  {t:11s} {c['mean']:6.1f}  ({c['min']:2d}..{c['max']:2d})".ljust(40)
              + f" {size:24s} {yaw:22s} {d['base_y']['mean']:5.2f}{extra}")

    if affinity:
        affinity.sort(key=lambda r: -r[4])
        print("\nQué tipos quedan cerca (hueco < 2) más o menos que al azar (observado / esperado):")
        print("  Más juntos que al azar:")
        for A, B, obs, exp, ratio in affinity[:6]:
            print(f"    {A:11s} - {B:11s} x{ratio:5.2f}   ({obs:.0f} observados, {exp:.0f} esperados)")
        print("  Más separados que al azar:")
        for A, B, obs, exp, ratio in affinity[::-1][:6]:
            print(f"    {A:11s} - {B:11s} x{ratio:5.2f}   ({obs:.0f} observados, {exp:.0f} esperados)")


# --------------------------------------------------------------------------- #
def main(folder, out_path, npz=None, vocab=None):
    levels = load_levels(folder)
    if npz:
        have = {l["levelId"] for l in levels}
        extra = load_npz_levels(npz, vocab, have)
        print(f"  Niveles completados desde el npz: {len(extra)}")
        levels += extra
    arrs = [level_arrays(l) for l in levels]
    all_tags = sorted({t for a in arrs for t in a["tags"]})

    zone = {
        "width_median": float(np.median([a["width"] for a in arrs])),
        "length_median": float(np.median([a["length"] for a in arrs])),
        "width_max": float(max(a["width"] for a in arrs)),
        "length_max": float(max(a["length"] for a in arrs)),
    }

    types = fit_types(arrs, all_tags, zone["width_median"], zone["length_median"])
    pairs, affinity = fit_pairs(arrs, all_tags)

    model = {
        "format": "PCGStatModel",
        "version": "0.1",
        "meta": {
            "n_levels": len(levels),
            "level_files": [l["_file"] for l in levels],
            "scene_ir_versions": dict(Counter(str(l.get("version")) for l in levels)),
            "tags": all_tags,
            "gap_edges": [e if e != float("inf") else "inf" for e in GAP_EDGES],
            "sectors": SECTOR_NAMES,
            "note": "posiciones centradas por nivel; tamaños locales (sin rotar)",
        },
        "zone": zone,
        "types": types,
        "pairs": pairs,
    }
    Path(out_path).write_text(json.dumps(model, indent=1, ensure_ascii=False), encoding="utf-8")

    print_report(levels, types, zone, affinity)
    print(f"\nModelo guardado en {out_path}")


if __name__ == "__main__":
    if len(sys.argv) not in (3, 5):
        print(__doc__)
        sys.exit(1)
    main(*sys.argv[1:])
