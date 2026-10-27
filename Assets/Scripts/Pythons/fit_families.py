"""
fit_families.py

Ajusta UN modelo por familia de niveles. La familia se decide por el contenido:
  "agua"     -> niveles que tienen objetos Water
  "sin_agua" -> niveles sin Water
Los tamaños locales y la altura de base son propiedades del prefab (no del nivel),
así que se calculan con TODOS los niveles que las traen (los JSON) y se comparten
entre familias; así la familia que solo se conoce por el npz también los tiene.

Uso:
    python fit_families.py <carpeta_json> <carpeta_salida> <dataset.npz> <vocab.json>
Salida: <carpeta_salida>/model_agua.json  y  model_sin_agua.json
"""
import json
import sys
from pathlib import Path

import numpy as np

import fit_statistics as fs


def family_of(level):
    tags = level["tags"] if level.get("_npz") else [o["tag"] for o in level["objects"]]
    return "agua" if "Water" in tags else "sin_agua"


def main(folder, out_dir, npz, vocab):
    levels = fs.load_levels(folder)
    have = {l["levelId"] for l in levels}
    levels += fs.load_npz_levels(npz, vocab, have)

    all_arrs = [fs.level_arrays(l) for l in levels]
    all_tags = sorted({t for a in all_arrs for t in a["tags"]})

    # propiedades del prefab, con todos los niveles que las traen
    zone_all = {"width_median": float(np.median([a["width"] for a in all_arrs])),
                "length_median": float(np.median([a["length"] for a in all_arrs]))}
    global_types = fs.fit_types(all_arrs, all_tags, zone_all["width_median"], zone_all["length_median"])

    Path(out_dir).mkdir(parents=True, exist_ok=True)
    for fam in ("agua", "sin_agua"):
        sel = [(l, a) for l, a in zip(levels, all_arrs) if family_of(l) == fam]
        arrs = [a for _, a in sel]
        zone = {"width_median": float(np.median([a["width"] for a in arrs])),
                "length_median": float(np.median([a["length"] for a in arrs])),
                "width_max": float(max(a["width"] for a in arrs)),
                "length_max": float(max(a["length"] for a in arrs))}
        types = fs.fit_types(arrs, all_tags, zone["width_median"], zone["length_median"])
        for t in all_tags:  # tamaño local / base compartidos
            types[t]["local_size"] = global_types[t]["local_size"]
            types[t]["base_y"] = global_types[t]["base_y"]
            types[t]["tilted_fraction"] = global_types[t]["tilted_fraction"]
        pairs, _ = fs.fit_pairs(arrs, all_tags)
        model = {"format": "PCGStatModel", "version": "0.2", "family": fam,
                 "meta": {"n_levels": len(arrs), "tags": all_tags,
                          "level_files": [l["_file"] for l, _ in sel],
                          "gap_edges": [e if e != float("inf") else "inf" for e in fs.GAP_EDGES],
                          "sectors": fs.SECTOR_NAMES},
                 "zone": zone, "types": types, "pairs": pairs}
        p = Path(out_dir) / f"model_{fam}.json"
        p.write_text(json.dumps(model, indent=1, ensure_ascii=False), encoding="utf-8")
        print(f"{fam}: {len(arrs)} niveles -> {p}")
        for t in all_tags:
            c = types[t]["count"]
            if c["max"] > 0:
                print(f"   {t:11s} {c['mean']:5.1f} ({c['min']}..{c['max']})")


if __name__ == "__main__":
    if len(sys.argv) != 5:
        print(__doc__); sys.exit(1)
    main(*sys.argv[1:])
