using System;
using System.Collections.Generic;

[Serializable]
public class SceneIR
{
    public string format = "SceneIR";
    public string version = "0.5";

    // NUEVO: identidad y etiqueta manual del nivel completo (no de un objeto).
    // label: -1 = sin evaluar, 1 = aceptable, 0 = no aceptable.
    public string levelId;
    public int label = -1;

    public List<SceneObjectIR> objects = new();
    public List<SceneRelation> relations = new();
}

[Serializable]
public class SceneObjectIR
{
    public int id;

    public string name;

    public string tag;

    public int layer;

    public int parentId = -1;

    public List<int> children = new();

    public TransformIR transform = new();

    // NUEVO: tamaño real del objeto en mundo (Renderer.bounds.size), usado
    // para corregir la distancia por tamaño en SpatialRelationBuilder.
    // Queda en (0,0,0) si el objeto no tiene Renderer/Collider -- se trata
    // como punto sin volumen en ese caso (comportamiento anterior).
    public Vector3IR boundsSize = new();

    public List<string> components = new();

    public string mesh;

    public List<string> materials = new();
}

[Serializable]
public class SceneRelation
{
    public int sourceId;

    public int targetId;

    public RelationType relation;

    public float value = 1f;
}

public enum RelationType
{
    Parent,
    Child,

    Near,

    Above,
    Below,

    LeftOf,
    RightOf,

    InFrontOf,
    Behind
}

[Serializable]
public class TransformIR
{
    public Vector3IR position = new();
    public Vector3IR rotation = new();
    public Vector3IR scale = new();
}

[Serializable]
public class Vector3IR
{
    public float x;
    public float y;
    public float z;

    public Vector3IR() { }

    public Vector3IR(float x, float y, float z)
    {
        this.x = x;
        this.y = y;
        this.z = z;
    }
}