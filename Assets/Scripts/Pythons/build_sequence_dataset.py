import argparse
import json
import math
import random
from pathlib import Path

import numpy as np

# ----------------------------------------------------------------------------- #
# Ajustes (puedes cambiarlos; quedan guardados en seq_vocab.json)
# ----------------------------------------------------------------------------- #
N_POS = 256        # intervalos para X y Z
N_BASE = 32        # intervalos para la altura de la base
N_SIZE = 64        # intervalos para cada medida (escala logarítmica)
N_YAW = 24         # intervalos de giro (24 -> cada 15°; 0/90/180/270 caen exactos)
SIZE_MIN = 0.05    # medida mínima representable (m)
FIELDS = ["tag", "x", "z", "y", "w", "h", "l", "yaw"]
TOKENS_PER_OBJECT = len(FIELDS)
FIRST_TAGS = ["Water", "Untagged"]   # van primero en la secuencia, en este orden


# ----------------------------------------------------------------------------- #
# 1) Leer niveles
# ----------------------------------------------------------------------------- #
def angle_from_zero(deg):
    return abs(((deg + 180.0) % 360.0) - 180.0)


def local_size(size_xyz, yaw_deg):
    """Tamaño sin rotar a partir de la caja de mundo (misma regla que fit_statistics).

    La caja alineada a los ejes de un objeto girado en Y mide
        x = a|cos| + c|sin|,   z = a|sin| + c|cos|
    Se despeja a (ancho) y c (largo). Cerca de 45° no se puede separar a de c:
    en ese caso se usa a = x / (|cos| + |sin|) y c = z / (|cos| + |sin|), que es
    exacto si el objeto es cuadrado en planta, y se marca como aproximado.
    """
    th = math.radians(yaw_deg)
    C, S = abs(math.cos(th)), abs(math.sin(th))
    den = C * C - S * S
    x, y, z = size_xyz
    if abs(den) >= 0.15:
        a = (x * C - z * S) / den
        c = (z * C - x * S) / den
        if a > 0 and c > 0:
            return (a, y, c), True
    return (x / (C + S), y, z / (C + S)), False


def read_level(path):
    """Devuelve la lista de objetos del nivel como dicts simples, centrados en (0, 0)."""
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    if d.get("format") != "SceneIR":
        return None, "no es SceneIR"
    objs = d.get("objects", [])
    if not objs or not all("boundsCenter" in o and "boundsSize" in o for o in objs):
        return None, "sin boundsCenter/boundsSize (exportado con versión vieja)"

    rows, approx, tilted = [], 0, 0
    for o in objs:
        tag = o.get("tag") or "Untagged"
        c, s, r = o["boundsCenter"], o["boundsSize"], o["transform"]["rotation"]
        if angle_from_zero(r["x"]) > 0.5 or angle_from_zero(r["z"]) > 0.5:
            tilted += 1                       # la inclinación en X/Z no se representa
        yaw = r["y"] % 360.0
        if "localSize" in o:                  # niveles generados ya lo traen
            ls, ok = (o["localSize"]["x"], o["localSize"]["y"], o["localSize"]["z"]), True
        else:
            ls, ok = local_size((s["x"], s["y"], s["z"]), yaw)
        approx += (not ok)
        rows.append({"tag": tag, "x": c["x"], "z": c["z"],
                     "y": c["y"] - s["y"] / 2.0,          # base
                     "w": ls[0], "h": ls[1], "l": ls[2], "yaw": yaw,
                     "bx": s["x"], "bz": s["z"]})          # caja de mundo, para centrar

    # Centrar el nivel: centro de la caja que envuelve todo en X y Z.
    xmin = min(r["x"] - r["bx"] / 2 for r in rows); xmax = max(r["x"] + r["bx"] / 2 for r in rows)
    zmin = min(r["z"] - r["bz"] / 2 for r in rows); zmax = max(r["z"] + r["bz"] / 2 for r in rows)
    cx, cz = (xmin + xmax) / 2, (zmin + zmax) / 2
    for r in rows:
        r["x"] -= cx; r["z"] -= cz
        del r["bx"], r["bz"]
    info = {"file": Path(path).name, "levelId": d.get("levelId", Path(path).stem),
            "objects": len(rows), "approx_size": approx, "tilted": tilted,
            "width": xmax - xmin, "length": zmax - zmin}
    return rows, info


# ----------------------------------------------------------------------------- #
# 2) Aumento de datos: giros y espejo
# ----------------------------------------------------------------------------- #
def transform_level(rows, rot_deg, mirror):
    """Gira el nivel alrededor de (0, 0) y/o lo espeja en X.

    Convención de Unity: un yaw positivo gira en sentido horario visto desde arriba,
    así que girar el nivel +θ manda (x, z) -> (x cosθ + z sinθ, -x sinθ + z cosθ)
    y suma θ al yaw de cada objeto. Espejo: x -> -x, yaw -> -yaw.
    """
    th = math.radians(rot_deg)
    co, si = round(math.cos(th), 12), round(math.sin(th), 12)
    out = []
    for r in rows:
        x, z, yaw = r["x"], r["z"], r["yaw"]
        if mirror:
            x, yaw = -x, -yaw
        x, z = x * co + z * si, -x * si + z * co
        yaw = (yaw + rot_deg) % 360.0
        out.append({**r, "x": x, "z": z, "yaw": yaw})
    return out


def order_objects(rows):
    def key(r):
        pri = FIRST_TAGS.index(r["tag"]) if r["tag"] in FIRST_TAGS else len(FIRST_TAGS)
        return (pri, round(r["x"], 3), round(r["z"], 3))
    return sorted(rows, key=key)


# ----------------------------------------------------------------------------- #
# 3) Vocabulario: de valores a tokens y de vuelta
# ----------------------------------------------------------------------------- #
class Vocab:
    """Tokens especiales, luego un bloque por atributo:
        0 PAD, 1 BOS, 2 EOS, luego TAG..., X..., Z..., Y..., W..., H..., L..., YAW...
    """

    def __init__(self, tags, pos_range, base_range, size_max):
        self.tags = list(tags)
        self.pos_range = float(pos_range)              # X y Z van de -pos_range a +pos_range
        self.base_range = [float(base_range[0]), float(base_range[1])]
        self.size_max = float(size_max)
        self.sizes = {"tag": len(self.tags), "x": N_POS, "z": N_POS, "y": N_BASE,
                      "w": N_SIZE, "h": N_SIZE, "l": N_SIZE, "yaw": N_YAW}
        self.offset, o = {}, 3
        for f in FIELDS:
            self.offset[f] = o
            o += self.sizes[f]
        self.size = o

    # ---- un valor -> número de intervalo ----
    def _bin_lin(self, v, lo, hi, n):
        t = (v - lo) / (hi - lo) if hi > lo else 0.5
        return int(min(n - 1, max(0, math.floor(t * n))))

    def _unbin_lin(self, b, lo, hi, n):
        return lo + (b + 0.5) * (hi - lo) / n

    def _bin_size(self, v):
        lo, hi = math.log(SIZE_MIN), math.log(self.size_max)
        return self._bin_lin(math.log(max(v, SIZE_MIN)), lo, hi, N_SIZE)

    def _unbin_size(self, b):
        lo, hi = math.log(SIZE_MIN), math.log(self.size_max)
        return math.exp(self._unbin_lin(b, lo, hi, N_SIZE))

    def encode_object(self, r):
        bins = {
            "tag": self.tags.index(r["tag"]) if r["tag"] in self.tags else self.tags.index("Untagged"),
            "x": self._bin_lin(r["x"], -self.pos_range, self.pos_range, N_POS),
            "z": self._bin_lin(r["z"], -self.pos_range, self.pos_range, N_POS),
            "y": self._bin_lin(r["y"], *self.base_range, N_BASE),
            "w": self._bin_size(r["w"]), "h": self._bin_size(r["h"]), "l": self._bin_size(r["l"]),
            "yaw": int(round((r["yaw"] % 360.0) / (360.0 / N_YAW))) % N_YAW,
        }
        return [self.offset[f] + bins[f] for f in FIELDS]

    def decode_object(self, toks):
        b = {f: toks[i] - self.offset[f] for i, f in enumerate(FIELDS)}
        return {"tag": self.tags[b["tag"]],
                "x": self._unbin_lin(b["x"], -self.pos_range, self.pos_range, N_POS),
                "z": self._unbin_lin(b["z"], -self.pos_range, self.pos_range, N_POS),
                "y": self._unbin_lin(b["y"], *self.base_range, N_BASE),
                "w": self._unbin_size(b["w"]), "h": self._unbin_size(b["h"]),
                "l": self._unbin_size(b["l"]), "yaw": b["yaw"] * 360.0 / N_YAW}

    def encode_level(self, rows):
        seq = [1]
        for r in order_objects(rows):
            seq += self.encode_object(r)
        return seq + [2]

    def decode_level(self, seq):
        body = [t for t in seq if t not in (0, 1, 2)]
        return [self.decode_object(body[i:i + TOKENS_PER_OBJECT])
                for i in range(0, len(body) - TOKENS_PER_OBJECT + 1, TOKENS_PER_OBJECT)]

    def to_json(self):
        return {"special": {"PAD": 0, "BOS": 1, "EOS": 2}, "fields": FIELDS,
                "tokens_per_object": TOKENS_PER_OBJECT, "offset": self.offset,
                "sizes": self.sizes, "vocab_size": self.size, "tags": self.tags,
                "pos_range": self.pos_range, "base_range": self.base_range,
                "size_min": SIZE_MIN, "size_max": self.size_max,
                "n_pos": N_POS, "n_base": N_BASE, "n_size": N_SIZE, "n_yaw": N_YAW}

    @classmethod
    def from_json(cls, d):
        return cls(d["tags"], d["pos_range"], d["base_range"], d["size_max"])


# ----------------------------------------------------------------------------- #
# 4) Volver a SceneIR (para revisar en Unity que la conversión no daña el nivel)
# ----------------------------------------------------------------------------- #
def rows_to_sceneir(rows, level_id):
    objs = []
    for i, r in enumerate(rows):
        th = math.radians(r["yaw"])
        C, S = abs(math.cos(th)), abs(math.sin(th))
        bx = r["w"] * C + r["l"] * S
        bz = r["w"] * S + r["l"] * C
        objs.append({
            "id": i, "name": f'{r["tag"]}_{i}', "tag": r["tag"],
            "transform": {"position": {"x": r["x"], "y": r["y"], "z": r["z"]},
                          "rotation": {"x": 0.0, "y": r["yaw"], "z": 0.0},
                          "scale": {"x": 1.0, "y": 1.0, "z": 1.0}},
            "boundsSize": {"x": bx, "y": r["h"], "z": bz},
            "boundsCenter": {"x": r["x"], "y": r["y"] + r["h"] / 2.0, "z": r["z"]},
            "localSize": {"x": r["w"], "y": r["h"], "z": r["l"]},
        })
    return {"format": "SceneIR", "version": "0.7", "levelId": level_id,
            "label": "decoded", "objects": objs, "relations": []}


# ----------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder", help="carpeta con los JSON exportados de Unity")
    ap.add_argument("--out", default="seq_dataset.npz")
    ap.add_argument("--vocab", default="seq_vocab.json")
    ap.add_argument("--val", type=int, default=6, help="niveles apartados para validación")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--rotations", default="0,90,180,270",
                    help="giros del aumento de datos, ej. 0,180 si la dirección del río importa")
    ap.add_argument("--no-mirror", action="store_true", help="no agregar versiones espejadas")
    ap.add_argument("--decode-check", default=None,
                    help="escribe el primer nivel de validación codificado y decodificado, para importarlo en Unity")
    args = ap.parse_args()

    # ---- leer ----
    levels = []
    for p in sorted(Path(args.folder).glob("*.json")):
        rows, info = read_level(p)
        if rows is None:
            print(f"  [omitido] {p.name}: {info}")
            continue
        levels.append((rows, info))
    if len(levels) < 2:
        raise SystemExit("Hacen falta al menos 2 niveles utilizables.")
    print(f"Niveles leídos: {len(levels)}")
    for _, i in levels:
        extra = []
        if i["approx_size"]: extra.append(f'{i["approx_size"]} tamaños aproximados (giro ~45°)')
        if i["tilted"]: extra.append(f'{i["tilted"]} inclinados (se ignora la inclinación)')
        print(f'  {i["file"]:22s} {i["objects"]:4d} objetos  {i["width"]:6.1f} x {i["length"]:6.1f} m'
              + ("   " + "; ".join(extra) if extra else ""))

    # ---- separar validación ANTES de aumentar ----
    rng = random.Random(args.seed)
    idx = list(range(len(levels)))
    rng.shuffle(idx)
    n_val = min(args.val, len(levels) - 1)
    val_idx, train_idx = sorted(idx[:n_val]), sorted(idx[n_val:])

    # ---- aumentar entrenamiento ----
    rots = [float(r) for r in args.rotations.split(",") if r.strip()]
    mirrors = [False] if args.no_mirror else [False, True]
    train_rows, train_src = [], []
    for i in train_idx:
        for rot in rots:
            for m in mirrors:
                train_rows.append(transform_level(levels[i][0], rot, m))
                train_src.append(f'{levels[i][1]["file"]}|rot{int(rot)}{"|espejo" if m else ""}')
    val_rows = [levels[i][0] for i in val_idx]
    val_src = [levels[i][1]["file"] for i in val_idx]

    # ---- vocabulario (rangos medidos sobre TODO, ya girado) ----
    every = [r for lv in train_rows + val_rows for r in lv]
    tags = sorted({r["tag"] for r in every} | {"Untagged"})
    pos_range = max(max(abs(r["x"]), abs(r["z"])) for r in every) * 1.05
    ys = [r["y"] for r in every]
    base_range = (min(ys) - 0.01, max(ys) + 0.01)
    size_max = max(max(r["w"], r["h"], r["l"]) for r in every) * 1.05
    vocab = Vocab(tags, pos_range, base_range, size_max)

    # ---- codificar ----
    train_seqs = [vocab.encode_level(lv) for lv in train_rows]
    val_seqs = [vocab.encode_level(lv) for lv in val_rows]
    max_len = max(len(s) for s in train_seqs + val_seqs)

    def pad(seqs):
        a = np.zeros((len(seqs), max_len), dtype=np.int32)
        for k, s in enumerate(seqs):
            a[k, :len(s)] = s
        return a

    np.savez_compressed(args.out, train=pad(train_seqs), val=pad(val_seqs),
                        train_len=np.array([len(s) for s in train_seqs], dtype=np.int32),
                        val_len=np.array([len(s) for s in val_seqs], dtype=np.int32),
                        train_source=np.array(train_src), val_source=np.array(val_src))
    meta = vocab.to_json()
    meta["max_len"] = max_len
    meta["train_levels"] = [levels[i][1]["file"] for i in train_idx]
    meta["val_levels"] = val_src
    meta["augmentation"] = {"rotations": rots, "mirror": not args.no_mirror}
    meta["seed"] = args.seed
    Path(args.vocab).write_text(json.dumps(meta, indent=1, ensure_ascii=False), encoding="utf-8")

    # ---- resumen y error de cuantización ----
    pos_step = 2 * pos_range / N_POS
    print(f"\nEntrenamiento: {len(train_idx)} niveles -> {len(train_seqs)} secuencias "
          f"({len(rots)} giros x {len(mirrors)} espejo)")
    print(f"Validación:    {len(val_seqs)} niveles  {val_src}")
    print(f"Vocabulario:   {vocab.size} tokens  ({len(tags)} tags: {', '.join(tags)})")
    print(f"Secuencia más larga: {max_len} tokens  (~{(max_len - 2) // TOKENS_PER_OBJECT} objetos)")
    print(f"Resolución: posición {pos_step:.2f} m por intervalo, giro {360 / N_YAW:.0f}°")

    errs = []
    for lv in val_rows:
        dec = vocab.decode_level(vocab.encode_level(lv))
        for a, b in zip(order_objects(lv), dec):
            errs.append(math.hypot(a["x"] - b["x"], a["z"] - b["z"]))
    print(f"Error de posición al codificar y decodificar (validación): "
          f"medio {np.mean(errs):.2f} m, máximo {np.max(errs):.2f} m")

    if args.decode_check:
        lv = val_rows[0]
        dec = vocab.decode_level(vocab.encode_level(lv))
        Path(args.decode_check).write_text(
            json.dumps(rows_to_sceneir(dec, f"decoded_{val_src[0]}"), indent=1), encoding="utf-8")
        print(f"\nEscrito {args.decode_check}: {val_src[0]} pasado a tokens y de vuelta. "
              f"Impórtalo en Unity y compáralo con el original.")
    print(f"\nListo: {args.out} y {args.vocab}")


if __name__ == "__main__":
    main()
