"""
generate_level.py

Generador de niveles (etapa 1): sorteo + recocido simulado (simulated annealing).

1. SORTEA el inventario: copia los conteos por tipo de un nivel real elegido al
   azar de la familia (así los conteos son coherentes entre sí).
2. SORTEA tamaño local y giro de cada objeto según lo aprendido, y de ahí calcula
   su caja alineada a los ejes (como la exporta Unity).
3. COLOCA todo al azar y lo va moviendo: cada movimiento se acepta si acerca las
   estadísticas del nivel a las del modelo (cuántos vecinos de cada tipo a cada
   rango de distancia), o con cierta probabilidad si las aleja (la "temperatura"
   baja con el tiempo). Se penaliza que dos objetos se atraviesen.
4. EXPORTA un JSON con el mismo formato que los niveles reales (SceneIR 0.7),
   con las relaciones calculadas por spatial_relations.py.

Uso:
    python generate_level.py <model_familia.json> <carpeta_salida> [n_niveles] [semilla]
"""
import json
import math
import sys
from pathlib import Path

import numpy as np

from spatial_relations import build_relations

GAP_EDGES = np.array([0.0, 0.5, 1.0, 2.0, 4.0, 8.0, 16.0, 32.0])  # último rango: >= 32
K = len(GAP_EDGES)
PEN_TOL = 0.3         # penetración tolerada (unidades) antes de penalizar
PEN_WEIGHT = 40.0     # peso de la penalización frente al término estadístico


# --------------------------------------------------------------------------- #
class Model:
    def __init__(self, path):
        m = json.loads(Path(path).read_text(encoding="utf-8"))
        self.raw = m
        self.family = m["family"]
        self.tags = m["meta"]["tags"]
        self.tix = {t: i for i, t in enumerate(self.tags)}
        self.zone = (m["zone"]["width_median"], m["zone"]["length_median"])
        self.types = m["types"]
        nt = len(self.tags)
        self.npo = np.zeros((nt, K, nt))        # vecinos por origen [A, rango, B]
        for key, p in m["pairs"].items():
            A, B = key.split("|")
            self.npo[self.tix[A], :, self.tix[B]] = p["neighbors_per_origin"]


def aabb(local, yaw_deg):
    a, y, c = local
    th = math.radians(yaw_deg)
    C, S = abs(math.cos(th)), abs(math.sin(th))
    return np.array([a * C + c * S, y, a * S + c * C])


def sample_yaw(info, rng):
    if info["mode"] == "cardinal":
        ks = [0, 90, 180, 270]
        return float(rng.choice(ks, p=[info["probs"][str(k)] for k in ks]))
    if info["mode"] == "free":
        if rng.random() < info.get("cardinal_fraction", 0):
            return float(rng.choice([0, 90, 180, 270]))
        return float(rng.uniform(0, 360))
    return 0.0


def sample_local_size(t, rng):
    ls = t["local_size"]["samples"]
    if ls:
        w = np.array([c for _, c in ls], dtype=float)
        return tuple(ls[rng.choice(len(ls), p=w / w.sum())][0])
    return tuple(t["local_size"]["aabb_median"])


def sample_position(t, zone, rng):
    g = np.array(t["position_grid"]["fractions"])
    nx, nz = g.shape
    if g.sum() <= 0:
        return rng.uniform(-zone[0] / 2, zone[0] / 2), rng.uniform(-zone[1] / 2, zone[1] / 2)
    k = rng.choice(g.size, p=g.ravel() / g.sum())
    ix, iz = divmod(k, nz)
    x = -zone[0] / 2 + (ix + rng.random()) * zone[0] / nx
    z = -zone[1] / 2 + (iz + rng.random()) * zone[1] / nz
    return x, z


# --------------------------------------------------------------------------- #
def gaps_and_pen(i, pos, ext, ycen, skip_self=True):
    """Hueco (3D, entre cajas) y penetración de la caja i contra todas las demás."""
    d = np.abs(pos[:, 0] - pos[i, 0]), np.abs(ycen - ycen[i]), np.abs(pos[:, 1] - pos[i, 1])
    half = (ext + ext[i]) / 2
    ov = [half[:, 0] - d[0], half[:, 1] - d[1], half[:, 2] - d[2]]
    gx, gy, gz = (np.maximum(-o, 0) for o in ov)
    gap = np.sqrt(gx * gx + gy * gy + gz * gz)
    pen = np.minimum(np.minimum(ov[0], ov[1]), ov[2])
    pen = np.where(pen > PEN_TOL, pen - PEN_TOL, 0.0)
    return gap, pen


def to_bin(gap):
    return np.clip(np.searchsorted(GAP_EDGES, gap, side="right") - 1, 0, K - 1)


class Level:
    def __init__(self, model, rng):
        self.m, self.rng = model, rng
        m = model
        counts = m.types
        # inventario: copiar los conteos de un nivel real de la familia
        any_t = next(iter(counts.values()))
        n_lv = len(any_t["count"]["per_level"])
        lv = int(rng.integers(n_lv))
        # per_level incluye TODOS los niveles del ajuste de la familia (ver fit_families)
        self.tag_idx, self.local, self.yaw, self.ext, self.base = [], [], [], [], []
        for t in m.tags:
            c = counts[t]["count"]["per_level"][lv]
            for _ in range(c):
                self.tag_idx.append(m.tix[t])
        self.n = len(self.tag_idx)
        self.tag_idx = np.array(self.tag_idx)
        self.pos = np.zeros((self.n, 2))
        self.ext = np.zeros((self.n, 3))
        self.ycen = np.zeros(self.n)
        self.local = []
        self.yaw = np.zeros(self.n)
        self.base = np.zeros(self.n)
        for i, ti in enumerate(self.tag_idx):
            t = counts[m.tags[ti]]
            self.local.append(sample_local_size(t, rng))
            self.yaw[i] = sample_yaw(t["yaw"], rng)
            self.ext[i] = aabb(self.local[i], self.yaw[i])
            self.base[i] = t["base_y"]["mean"]
            self.ycen[i] = self.base[i] + self.ext[i][1] / 2
            self.pos[i] = sample_position(t, m.zone, rng)
        self.count = np.bincount(self.tag_idx, minlength=len(m.tags)).astype(float)
        self.target = m.npo * self.count[:, None, None]
        self.weight = 1.0 / (self.target + 1.0)
        self.O = np.zeros_like(self.target)
        self.pen = 0.0
        self._build_counts()

    def _build_counts(self):
        self.O[:] = 0
        self.pen = 0.0
        for i in range(self.n):
            gap, pen = gaps_and_pen(i, self.pos, self.ext, self.ycen)
            b = to_bin(gap)
            mask = np.arange(self.n) != i
            np.add.at(self.O, (self.tag_idx[i], b[mask], self.tag_idx[mask]), 1)
            self.pen += pen[mask].sum() / 2

    def loss(self, O=None, pen=None):
        O = self.O if O is None else O
        pen = self.pen if pen is None else pen
        return float((((O - self.target) ** 2) * self.weight).sum()) + PEN_WEIGHT * pen

    def try_move(self, i, new_pos, new_yaw, T):
        ti = self.tag_idx[i]
        mask = np.arange(self.n) != i
        tj = self.tag_idx[mask]

        gap0, pen0 = gaps_and_pen(i, self.pos, self.ext, self.ycen)
        b0 = to_bin(gap0)[mask]

        old = (self.pos[i].copy(), self.yaw[i], self.ext[i].copy(), self.ycen[i])
        self.pos[i] = new_pos
        if new_yaw != self.yaw[i]:
            self.yaw[i] = new_yaw
            self.ext[i] = aabb(self.local[i], new_yaw)
            self.ycen[i] = self.base[i] + self.ext[i][1] / 2
        gap1, pen1 = gaps_and_pen(i, self.pos, self.ext, self.ycen)
        b1 = to_bin(gap1)[mask]

        O = self.O.copy()
        np.add.at(O, (ti, b0, tj), -1); np.add.at(O, (tj, b0, ti), -1)
        np.add.at(O, (ti, b1, tj), 1);  np.add.at(O, (tj, b1, ti), 1)
        pen = self.pen - pen0[mask].sum() + pen1[mask].sum()

        d = self.loss(O, pen) - self.loss()
        if d <= 0 or self.rng.random() < math.exp(-d / max(T, 1e-12)):
            self.O, self.pen = O, pen
            return True
        self.pos[i], self.yaw[i], self.ext[i], self.ycen[i] = old
        return False

    def anneal(self, iters=60000, verbose=True):
        rng, m = self.rng, self.m
        L0 = self.loss()
        T0, T1 = L0 * 0.004, L0 * 1e-6
        W, Ln = m.zone
        acc = 0
        for it in range(iters):
            f = it / iters
            T = T0 * (T1 / T0) ** f
            sigma = 12.0 * (1 - f) + 0.5 * f
            i = int(rng.integers(self.n))
            r = rng.random()
            t = m.types[m.tags[self.tag_idx[i]]]
            new_yaw = self.yaw[i]
            if r < 0.7:
                p = self.pos[i] + rng.normal(0, sigma, 2)
            elif r < 0.9:
                p = np.array(sample_position(t, m.zone, rng))
            else:
                p = self.pos[i].copy()
                new_yaw = sample_yaw(t["yaw"], rng)
            p[0] = np.clip(p[0], -W / 2, W / 2)
            p[1] = np.clip(p[1], -Ln / 2, Ln / 2)
            acc += self.try_move(i, p, new_yaw, T)
            if verbose and (it + 1) % (iters // 6) == 0:
                print(f"    iter {it+1:6d}  pérdida {self.loss():9.1f}  (inicial {L0:.1f})  "
                      f"penetración {self.pen:6.2f}  aceptados {acc/(it+1):.0%}")

    # ---------------------------------------------------------------------- #
    def to_scene(self, level_id):
        m = self.m
        objs = []
        for i in range(self.n):
            tag = m.tags[self.tag_idx[i]]
            e = self.ext[i]
            x, z = self.pos[i]
            objs.append({
                "id": i, "name": f"{tag}_{i}", "tag": "" if tag == "Untagged" else tag,
                "parentId": -1, "children": [],
                "transform": {"position": {"x": float(x), "y": float(self.base[i]), "z": float(z)},
                              "rotation": {"x": 0.0, "y": float(self.yaw[i]), "z": 0.0},
                              "scale": {"x": 1.0, "y": 1.0, "z": 1.0}},
                "boundsSize": {"x": float(e[0]), "y": float(e[1]), "z": float(e[2])},
                "boundsCenter": {"x": float(x), "y": float(self.ycen[i]), "z": float(z)},
                "localSize": {"x": self.local[i][0], "y": self.local[i][1], "z": self.local[i][2]},
            })
        rels = build_relations(objs)
        return {"format": "SceneIR", "version": "0.7", "levelId": level_id, "label": -1,
                "generated": True, "family": m.family,
                "objects": objs,
                "relations": [{"sourceId": s, "targetId": t, "relation": r, "value": v}
                              for s, t, r, v in rels]}


def generate(model_path, out_dir, n_levels=3, seed=0, iters=60000):
    model = Model(model_path)
    out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)
    paths = []
    for k in range(n_levels):
        print(f"  nivel {k+1}/{n_levels}")
        lv = Level(model, rng)
        lv.anneal(iters)
        scene = lv.to_scene(f"gen_{model.family}_{seed}_{k:03d}")
        p = out / f"{scene['levelId']}.json"
        p.write_text(json.dumps(scene), encoding="utf-8")
        paths.append(p)
    return paths


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__); sys.exit(1)
    generate(sys.argv[1], sys.argv[2],
             int(sys.argv[3]) if len(sys.argv) > 3 else 3,
             int(sys.argv[4]) if len(sys.argv) > 4 else 0)
