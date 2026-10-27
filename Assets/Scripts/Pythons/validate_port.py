"""
validate_port.py

Comprueba que spatial_relations.py reproduce lo que calculó C#:
recalcula las relaciones a partir de los objetos de cada JSON y las compara
con las que ya trae el archivo (las que escribió SpatialRelationBuilder.cs).

Uso:
    python validate_port.py level_001.json [level_002.json ...]
    python validate_port.py carpeta_con_niveles/
"""
import json
import sys
from collections import Counter
from pathlib import Path

from spatial_relations import RELATION_NAMES, build_relations

VALUE_TOL = 1e-5   # tolerancia en 'value' (Near); el resto debe coincidir exacto
MIN_VERSION = (0, 7)   # primera versión de SceneIR con direcciones en marco local


def validate(path: Path) -> bool:
    d = json.loads(path.read_text(encoding="utf-8"))
    objects = d["objects"]

    # Las direcciones (InFrontOf/Behind/LeftOf/RightOf) cambiaron a marco local en
    # SceneIR 0.7: los JSON anteriores traen relaciones calculadas con otra lógica.
    version = tuple(int(x) for x in str(d.get("version", "0.0")).split("."))
    if version < MIN_VERSION:
        print(f"{path.name}: versión {d.get('version')} < 0.7 -> sus relaciones se calcularon con la lógica "
              f"anterior (direcciones en ejes del mundo); re-expórtalo desde Unity para poder compararlo")
        return False

    if not all("boundsCenter" in o for o in objects):
        print(f"{path.name}: SIN boundsCenter (exportado con una versión vieja) -> no se puede reproducir")
        return False

    expected = [(r["sourceId"], r["targetId"], r["relation"], r["value"]) for r in d["relations"]]
    got = build_relations(objects)

    exp_keys = Counter((s, t, r) for s, t, r, _ in expected)
    got_keys = Counter((s, t, r) for s, t, r, _ in got)
    missing = exp_keys - got_keys     # las tiene C#, el port no
    extra = got_keys - exp_keys       # las genera el port, C# no

    same_order = [(s, t, r) for s, t, r, _ in expected] == [(s, t, r) for s, t, r, _ in got]

    got_val = {(s, t, r): v for s, t, r, v in got}
    max_diff = 0.0
    for s, t, r, v in expected:
        if (s, t, r) in got_val:
            max_diff = max(max_diff, abs(v - got_val[(s, t, r)]))

    ok = not missing and not extra and max_diff <= VALUE_TOL
    print(f"{path.name}: objetos={len(objects)}  relaciones C#={len(expected)}  port={len(got)}  "
          f"-> {'COINCIDEN' if ok else 'HAY DIFERENCIAS'}")
    print(f"   mismo orden: {same_order}   max |diff| en value: {max_diff:.2e}")

    if missing or extra:
        by_type_m = Counter(RELATION_NAMES[r] for (_, _, r) in missing.elements())
        by_type_e = Counter(RELATION_NAMES[r] for (_, _, r) in extra.elements())
        print(f"   faltan en el port : {dict(by_type_m)}")
        print(f"   sobran en el port : {dict(by_type_e)}")
        for (s, t, r) in list(missing)[:5]:
            print(f"     falta  {s}->{t} {RELATION_NAMES[r]}")
        for (s, t, r) in list(extra)[:5]:
            print(f"     sobra  {s}->{t} {RELATION_NAMES[r]}")
    return ok


if __name__ == "__main__":
    paths = []
    for arg in sys.argv[1:]:
        p = Path(arg)
        paths += sorted(p.glob("level_*.json")) if p.is_dir() else [p]
    if not paths:
        print(__doc__)
        sys.exit(1)

    results = [validate(p) for p in paths]
    sys.exit(0 if all(results) else 2)
