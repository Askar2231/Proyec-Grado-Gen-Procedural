import json
import sys
from pathlib import Path

import numpy as np

import fit_statistics as fs


def family_of(level):
    tags = level["tags"] if level.get("_npz") else [o["tag"] for o in level["objects"]]
    return "agua" if "Water" in tags else "sin_agua"


STRUCT_TAGS = ("Water", "Puente", "Untagged")   # agua + puentes (con tag Puente o sin tag): se copian, no se sortean


def river_templates(arrs):
    """Por cada nivel con agua (solo los que vienen de JSON): posición, giro y tamaño
    del agua y los puentes, ya centrados. El generador los copia con variaciones."""
    out = []
    for k, a in enumerate(arrs):
        if a.get("npz") or "Water" not in a["tags"]:
            continue
        objs = []
        for i, t in enumerate(a["tags"]):
            if t not in STRUCT_TAGS:
                continue
            size, rot, c = a["size"][i], a["rot"][i], a["center"][i]
            ls = fs.local_size(size, rot) or tuple(size)
            objs.append({"tag": t, "x": float(c[0]), "z": float(c[2]), "yaw": float(rot[1]),
                         "local": [float(v) for v in ls],
                         "base_y": float(c[1] - size[1] / 2)})
        water = [o for o in objs if o["tag"] == "Water"]
        # eje del río: en el que se reparten los tramos de agua
        spread_x = max(o["x"] for o in water) - min(o["x"] for o in water)
        spread_z = max(o["z"] for o in water) - min(o["z"] for o in water)
        out.append({"level_index": k, "axis": "x" if spread_x > spread_z else "z", "objects": objs})
    return out


def fit_models(levels, out_dir, all_tags=None, verbose=True):
    """Ajusta un modelo por familia con los niveles dados y los escribe en out_dir.
    all_tags: lista de tags a incluir en el modelo (por defecto, los de estos niveles).
    Devuelve {familia: ruta_del_modelo}."""
    all_arrs = [fs.level_arrays(l) for l in levels]
    if all_tags is None:
        all_tags = sorted({t for a in all_arrs for t in a["tags"]})

    # propiedades del prefab, con todos los niveles que las traen
    zone_all = {"width_median": float(np.median([a["width"] for a in all_arrs])),
                "length_median": float(np.median([a["length"] for a in all_arrs]))}
    global_types = fs.fit_types(all_arrs, all_tags, zone_all["width_median"], zone_all["length_median"])

    Path(out_dir).mkdir(parents=True, exist_ok=True)
    paths = {}
    for fam in ("agua", "sin_agua"):
        sel = [(l, a) for l, a in zip(levels, all_arrs) if family_of(l) == fam]
        arrs = [a for _, a in sel]
        if not arrs:
            if verbose:
                print(f"{fam}: sin niveles, se omite")
            continue
        zone = {"width_median": float(np.median([a["width"] for a in arrs])),
                "length_median": float(np.median([a["length"] for a in arrs])),
                "width_max": float(max(a["width"] for a in arrs)),
                "length_max": float(max(a["length"] for a in arrs))}
        types = fs.fit_types(arrs, all_tags, zone["width_median"], zone["length_median"])
        for t in all_tags:  # tamaño local / base compartidos
            types[t]["local_size"] = global_types[t]["local_size"]
            types[t]["base_y"] = global_types[t]["base_y"]
            types[t]["tilted_fraction"] = global_types[t]["tilted_fraction"]
        pairs, _ = fs.fit_pairs(arrs, all_tags, report=verbose)
        templates = river_templates(arrs) if fam == "agua" else []
        model = {"format": "PCGStatModel", "version": "0.2", "family": fam,
                 "meta": {"n_levels": len(arrs), "tags": all_tags,
                          "level_files": [l["_file"] for l, _ in sel],
                          "gap_edges": [e if e != float("inf") else "inf" for e in fs.GAP_EDGES],
                          "sectors": fs.SECTOR_NAMES},
                 "zone": zone, "types": types, "pairs": pairs,
                 "river_templates": templates}
        p = Path(out_dir) / f"model_{fam}.json"
        p.write_text(json.dumps(model, indent=1, ensure_ascii=False), encoding="utf-8")
        paths[fam] = p
        if verbose:
            print(f"{fam}: {len(arrs)} niveles -> {p}")
            for t in all_tags:
                c = types[t]["count"]
                if c["max"] > 0:
                    print(f"   {t:11s} {c['mean']:5.1f} ({c['min']}..{c['max']})")
    return paths


def main(folder, out_dir, npz=None, vocab=None):
    levels = fs.load_levels(folder)
    if npz:
        have = {l["levelId"] for l in levels}
        levels += fs.load_npz_levels(npz, vocab, have)
    fit_models(levels, out_dir)


if __name__ == "__main__":
    if len(sys.argv) not in (3, 5):
        print(__doc__); sys.exit(1)
    main(*sys.argv[1:])
