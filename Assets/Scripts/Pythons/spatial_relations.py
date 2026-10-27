"""
spatial_relations.py

Port a Python de ParentRelationBuilder + SpatialRelationBuilder (C#), versión
SceneIR 0.7: InFrontOf/Behind/LeftOf/RightOf se miden en el marco LOCAL de cada
objeto (su propio delante y derecha, desde su rotación en Y), no en los ejes del
mundo.
Recibe la lista de objetos de un SceneIR (ya leída del JSON) y devuelve las
relaciones en el mismo formato y orden que RelationPipeline.Build().

Se calcula en float32 en cada operación para reproducir lo que hace C#
(float), así los valores y los umbrales de borde coinciden.

MANTENER SINCRONIZADO con SpatialRelationBuilder.cs: si cambian una fórmula o
un umbral allá, hay que cambiarlo aquí y volver a correr validate_port.py.
"""

import math
from dataclasses import dataclass

import numpy as np

F = np.float32

# Mismo orden que el enum RelationType de SceneIR.cs
PARENT, CHILD, NEAR, ABOVE, BELOW, LEFTOF, RIGHTOF, INFRONTOF, BEHIND = range(9)
RELATION_NAMES = ["Parent", "Child", "Near", "Above", "Below",
                  "LeftOf", "RightOf", "InFrontOf", "Behind"]


@dataclass
class Params:
    # Above/Below (apilado)
    stack_contact_tolerance: float = 0.2
    stack_penetration_tolerance: float = 0.3
    footprint_min_overlap: float = 0.05
    # Direcciones en marco local: medio ángulo de los sectores delante/detrás
    orientation_cone_angle: float = 45.0
    # Distancias máximas (hueco entre cajas)
    orientation_max_distance: float = 6.0   # InFrontOf / Behind
    axis_max_distance: float = 8.0          # LeftOf / RightOf


def _sqrt(v):
    return F(math.sqrt(float(v)))


def _acos(v):
    return F(math.acos(float(v)))


def _sin(v):
    return F(math.sin(float(v)))


def _cos(v):
    return F(math.cos(float(v)))


def _abs(v):
    return -v if v < 0 else v


def _nonneg(v):
    return v if v > 0 else F(0)


def _clamp(v, lo, hi):
    return lo if v < lo else (hi if v > hi else v)


_PI = F(3.14159265)
_DEG2RAD = F(_PI / F(180))
_RAD2DEG = F(F(180) / _PI)


class _Obj:
    """Datos de un objeto ya convertidos a float32."""
    __slots__ = ("id", "cx", "cy", "cz", "sx", "sy", "sz", "yaw")

    def __init__(self, o):
        self.id = o["id"]
        c, s = o["boundsCenter"], o["boundsSize"]
        self.cx, self.cy, self.cz = F(c["x"]), F(c["y"]), F(c["z"])
        self.sx, self.sy, self.sz = F(s["x"]), F(s["y"]), F(s["z"])
        self.yaw = F(o["transform"]["rotation"]["y"])


def parent_relations(objects):
    """ParentRelationBuilder: Parent(padre->hijo) y Child(hijo->padre)."""
    out = []
    for o in objects:
        if o["parentId"] < 0:
            continue
        out.append((o["parentId"], o["id"], PARENT, 1.0))
        out.append((o["id"], o["parentId"], CHILD, 1.0))
    return out


def _directional(origin, target, tx, tz, surface, p, out):
    """Ubica al destino en el marco local del origen.

    tx, tz: vector origen -> destino en el plano XZ del mundo.
    Delante local = (sin yaw, cos yaw); derecha local = (cos yaw, -sin yaw).
    """
    yaw_rad = F(origin.yaw * _DEG2RAD)
    fx, fz = _sin(yaw_rad), _cos(yaw_rad)
    rx, rz = _cos(yaw_rad), F(-_sin(yaw_rad))

    length = _sqrt(F(tx * tx) + F(tz * tz))
    if length < F(0.0001):
        return

    dot = F(F(F(fx * tx) + F(fz * tz)) / length)
    dot = _clamp(dot, F(-1), F(1))
    angle = F(_acos(dot) * _RAD2DEG)

    cone = F(p.orientation_cone_angle)
    orient_max = F(p.orientation_max_distance)
    axis_max = F(p.axis_max_distance)

    if angle <= cone:
        if surface <= orient_max:
            out.append((origin.id, target.id, INFRONTOF, 1.0))
    elif angle >= F(F(180) - cone):
        if surface <= orient_max:
            out.append((origin.id, target.id, BEHIND, 1.0))
    elif surface <= axis_max:
        lateral = F(F(rx * tx) + F(rz * tz))
        out.append((origin.id, target.id, RIGHTOF if lateral > 0 else LEFTOF, 1.0))


def spatial_relations(objects, p: Params = Params()):
    """SpatialRelationBuilder: todos los pares, una vez cada uno (j = i + 1)."""
    objs = [_Obj(o) for o in objects]
    out = []
    two = F(2)

    stack_contact = F(p.stack_contact_tolerance)
    stack_pen = F(p.stack_penetration_tolerance)
    foot_min = F(p.footprint_min_overlap)
    max_directional = F(max(p.orientation_max_distance, p.axis_max_distance))

    n = len(objs)
    for i in range(n):
        a = objs[i]
        for j in range(i + 1, n):
            b = objs[j]

            cdx = F(a.cx - b.cx)
            cdy = F(a.cy - b.cy)
            cdz = F(a.cz - b.cz)

            half_x = F(F(a.sx + b.sx) / two)
            half_y = F(F(a.sy + b.sy) / two)
            half_z = F(F(a.sz + b.sz) / two)

            gap_x = _nonneg(F(_abs(cdx) - half_x))
            gap_y = _nonneg(F(_abs(cdy) - half_y))
            gap_z = _nonneg(F(_abs(cdz) - half_z))
            surface = _sqrt(F(F(gap_x * gap_x) + F(gap_y * gap_y)) + F(gap_z * gap_z))

            # Near
            near = F(F(1) / F(F(1) + surface))
            out.append((a.id, b.id, NEAR, float(near)))

            # Above / Below (apilado)
            stack_gap = F(_abs(cdy) - half_y)
            overlap_x = F(half_x - _abs(cdx))
            overlap_z = F(half_z - _abs(cdz))
            touching = (stack_gap <= stack_contact) and (stack_gap >= -stack_pen)
            footprints = (overlap_x > foot_min) and (overlap_z > foot_min)
            if touching and footprints:
                out.append((a.id, b.id, ABOVE if cdy > 0 else BELOW, 1.0))

            # InFrontOf / Behind / LeftOf / RightOf: marco local de cada objeto
            if surface <= max_directional:
                _directional(a, b, F(-cdx), F(-cdz), surface, p, out)  # desde a, hacia b
                _directional(b, a, cdx, cdz, surface, p, out)           # desde b, hacia a

    return out


def build_relations(objects, p: Params = Params()):
    """Equivalente a RelationPipeline.Build(): primero jerarquía, luego espacial."""
    return parent_relations(objects) + spatial_relations(objects, p)
