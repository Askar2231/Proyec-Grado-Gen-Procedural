using UnityEngine;
using UnityEngine.SceneManagement;

public static class SceneExporter
{
    private static int currentId;

    public static SceneIR ExportCurrentScene()
    {
        currentId = 0;

        SceneIR scene = new();

        foreach (GameObject root in SceneManager.GetActiveScene().GetRootGameObjects())
        {
            Parse(root.transform, scene, -1);
        }

        RelationPipeline.Build(scene);

        return scene;
    }

    /// <summary>
    /// NUEVO: exporta solo el subárbol bajo 'root' (ej. el nodo "SpawnedObjects"),
    /// en vez de la escena completa. Úsalo para el flujo real de los 100 niveles,
    /// así la cámara, la luz, el marcador "Zone", etc. no terminan en el dataset.
    /// </summary>
    public static SceneIR ExportFromRoot(Transform root)
    {
        currentId = 0;

        SceneIR scene = new();

        // Se parsean los HIJOS de 'root', no 'root' mismo -- así el contenedor
        // "SpawnedObjects" (que no es un objeto semántico) no termina como una
        // entrada más en scene.objects.
        foreach (Transform child in root)
        {
            Parse(child, scene, -1);
        }

        RelationPipeline.Build(scene);

        return scene;
    }

    static void Parse(Transform tr, SceneIR scene, int parent)
    {
        SceneObjectIR obj = new();

        obj.id = currentId++;

        obj.name = tr.name;
        obj.tag = tr.tag;
        obj.layer = tr.gameObject.layer;

        obj.parentId = parent;

        obj.transform.position = ToVector3IR(tr.position);
        obj.transform.rotation = ToVector3IR(tr.eulerAngles);
        obj.transform.scale = ToVector3IR(tr.localScale);

        // NUEVO: tamaño real en mundo, para que SpatialRelationBuilder pueda
        // corregir la distancia por tamaño (atalayas/estructuras grandes vs
        // props chicos). Prioridad: Renderer.bounds; si no hay, Collider.bounds;
        // si tampoco, queda en (0,0,0) -- se trata como punto, igual que antes.
        obj.boundsSize = GetBoundsSize(tr);

        foreach (Component c in tr.GetComponents<Component>())
        {
            obj.components.Add(c.GetType().Name);
        }

        MeshFilter mf = tr.GetComponent<MeshFilter>();

        if (mf != null && mf.sharedMesh != null)
            obj.mesh = mf.sharedMesh.name;

        MeshRenderer mr = tr.GetComponent<MeshRenderer>();

        if (mr != null)
        {
            foreach (Material mat in mr.sharedMaterials)
            {
                if (mat != null)
                    obj.materials.Add(mat.name);
            }
        }

        scene.objects.Add(obj);

        foreach (Transform child in tr)
        {
            int childId = currentId;

            obj.children.Add(childId);

            Parse(child, scene, obj.id);
        }
    }

    private static Vector3IR GetBoundsSize(Transform tr)
    {
        Renderer renderer = tr.GetComponent<Renderer>();
        if (renderer != null)
        {
            return ToVector3IR(renderer.bounds.size);
        }

        Collider collider = tr.GetComponent<Collider>();
        if (collider != null)
        {
            return ToVector3IR(collider.bounds.size);
        }

        return new Vector3IR(0f, 0f, 0f);
    }

    private static Vector3IR ToVector3IR(Vector3 v)
    {
        return new Vector3IR(v.x, v.y, v.z);
    }
}