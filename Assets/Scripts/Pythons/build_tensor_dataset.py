import json
import math
import sys
from pathlib import Path

import numpy as np  # pyright: ignore[reportMissingImports]

# Debe mantenerse sincronizado con el enum RelationType de SceneIR.cs.
# Si agregan un tipo de relación nuevo en C#, agréguenlo aquí también,
# EN EL MISMO ORDEN (el índice es lo que importa, no el nombre).
RELATION_NAMES = [
    "Parent", "Child", "Near", "Above", "Below",
    "LeftOf", "RightOf", "InFrontOf", "Behind",
]
N_RELATIONS = len(RELATION_NAMES)

FEATURE_NAMES = [
    "token_id", "x", "y", "z",
    "size_x", "size_y", "size_z",
    "yaw_sin", "yaw_cos",
]
N_FEATURES = len(FEATURE_NAMES)


def load_levels(dataset_folder: Path) -> list[dict]:
    """Carga todos los level_*.json de la carpeta, en orden por nombre de archivo."""
    paths = sorted(dataset_folder.glob("level_*.json"))
    if not paths:
        raise FileNotFoundError(
            f"No se encontraron archivos 'level_*.json' en {dataset_folder}"
        )

    levels = []
    for p in paths:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        data["_source_file"] = p.name
        levels.append(data)

    return levels


def build_vocabulary(levels: list[dict]) -> dict[str, int]:
    """
    Escanea todos los niveles y arma el vocabulario tag -> token_id.
    Token 0 queda reservado para "desconocido/sin tag" (padding también usa 0,
    así que un objeto real nunca debería tener token_id == 0 a propósito --
    si ven token_id == 0 en una fila que SÍ es real según la máscara, revisen
    que ese objeto tenga tag asignado en Unity).
    """
    tags = set()
    for level in levels:
        for obj in level["objects"]:
            tag = obj.get("tag", "")
            if tag and tag != "Untagged":
                tags.add(tag)

    # Orden alfabético para que el vocabulario sea determinístico entre corridas.
    sorted_tags = sorted(tags)
    vocab = {"<unknown>": 0}
    for i, tag in enumerate(sorted_tags, start=1):
        vocab[tag] = i

    return vocab


def compute_max_objects(levels: list[dict]) -> int:
    return max(len(level["objects"]) for level in levels)


def level_to_tensors(level: dict, vocab: dict[str, int], max_objects: int):
    objects = level["objects"]
    n_objects = len(objects)

    if n_objects > max_objects:
        raise ValueError(
            f"Nivel {level.get('levelId', level['_source_file'])} tiene "
            f"{n_objects} objetos, más que max_objects={max_objects}. "
            f"Esto no debería pasar si max_objects se calculó del dataset."
        )

    object_features = np.zeros((max_objects, N_FEATURES), dtype=np.float32)
    mask = np.zeros((max_objects,), dtype=np.float32)

    # id de objeto (del JSON) -> fila dentro del tensor de este nivel.
    id_to_row = {}

    for row, obj in enumerate(objects):
        id_to_row[obj["id"]] = row
        mask[row] = 1.0

        tag = obj.get("tag", "")
        token_id = vocab.get(tag, vocab["<unknown>"])

        pos = obj["transform"]["position"]
        size = obj.get("boundsSize", {"x": 0.0, "y": 0.0, "z": 0.0})
        yaw_deg = obj["transform"]["rotation"]["y"]
        yaw_rad = math.radians(yaw_deg)

        object_features[row] = [
            token_id,
            pos["x"], pos["y"], pos["z"],
            size["x"], size["y"], size["z"],
            math.sin(yaw_rad), math.cos(yaw_rad),
        ]

    adjacency = np.zeros((max_objects, max_objects, N_RELATIONS), dtype=np.float32)

    for rel in level["relations"]:
        src_row = id_to_row.get(rel["sourceId"])
        tgt_row = id_to_row.get(rel["targetId"])

        if src_row is None or tgt_row is None:
            # Relación que apunta a un objeto que no está en 'objects'
            # (no debería pasar con un export bien formado -- se avisa).
            print(
                f"  [aviso] relación ignorada en {level.get('levelId', '?')}: "
                f"sourceId={rel['sourceId']} targetId={rel['targetId']} "
                f"no encontrados entre los objetos del nivel."
            )
            continue

        adjacency[src_row, tgt_row, rel["relation"]] = rel["value"]

    label = level.get("label", -1)

    return object_features, adjacency, mask, label


def build_dataset(dataset_folder: str, output_folder: str):
    dataset_folder = Path(dataset_folder)
    output_folder = Path(output_folder)
    output_folder.mkdir(parents=True, exist_ok=True)

    print(f"Cargando niveles desde {dataset_folder} ...")
    levels = load_levels(dataset_folder)
    print(f"  {len(levels)} niveles encontrados.")

    vocab = build_vocabulary(levels)
    print(f"  Vocabulario: {len(vocab)} tipos de objeto (incluye <unknown>).")
    for tag, token in vocab.items():
        print(f"    {token:3d} -> {tag}")

    max_objects = compute_max_objects(levels)
    print(f"  max_objects (calculado del dataset): {max_objects}")

    all_object_features = []
    all_adjacency = []
    all_mask = []
    all_labels = []
    all_level_ids = []

    n_unlabeled = 0

    for level in levels:
        of, adj, mask, label = level_to_tensors(level, vocab, max_objects)

        all_object_features.append(of)
        all_adjacency.append(adj)
        all_mask.append(mask)
        all_labels.append(label)
        all_level_ids.append(level.get("levelId", level["_source_file"]))

        if label == -1:
            n_unlabeled += 1

    if n_unlabeled > 0:
        print(
            f"\n  [AVISO] {n_unlabeled} nivel(es) tienen label=-1 (sin evaluar). "
            f"Van a quedar en el dataset igual, pero no sirven como ejemplo de "
            f"entrenamiento hasta que los etiqueten."
        )

    object_features = np.stack(all_object_features)   # (n_levels, max_objects, N_FEATURES)
    adjacency = np.stack(all_adjacency)                # (n_levels, max_objects, max_objects, N_RELATIONS)
    mask = np.stack(all_mask)                          # (n_levels, max_objects)
    labels = np.array(all_labels, dtype=np.int32)
    level_ids = np.array(all_level_ids)

    npz_path = output_folder / "dataset.npz"
    np.savez_compressed(
        npz_path,
        object_features=object_features,
        adjacency=adjacency,
        mask=mask,
        labels=labels,
        level_ids=level_ids,
    )
    print(f"\nGuardado: {npz_path}")
    print(f"  object_features: {object_features.shape}")
    print(f"  adjacency      : {adjacency.shape}")
    print(f"  mask           : {mask.shape}")
    print(f"  labels         : {labels.shape}")

    vocab_path = output_folder / "vocab.json"
    with open(vocab_path, "w", encoding="utf-8") as f:
        json.dump(
            {"tag_to_id": vocab, "id_to_tag": {v: k for k, v in vocab.items()}},
            f, indent=2, ensure_ascii=False,
        )
    print(f"Guardado: {vocab_path}")

    meta_path = output_folder / "dataset_meta.json"
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "n_levels": len(levels),
                "max_objects": max_objects,
                "n_features": N_FEATURES,
                "feature_names": FEATURE_NAMES,
                "n_relations": N_RELATIONS,
                "relation_names": RELATION_NAMES,
                "n_unlabeled": n_unlabeled,
            },
            f, indent=2, ensure_ascii=False,
        )
    print(f"Guardado: {meta_path}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Uso: python build_tensor_dataset.py <carpeta_dataset> <carpeta_salida>")
        sys.exit(1)

    build_dataset(sys.argv[1], sys.argv[2])
