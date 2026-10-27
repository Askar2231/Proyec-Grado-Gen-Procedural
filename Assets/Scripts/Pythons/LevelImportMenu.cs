#if UNITY_EDITOR
using System.Collections.Generic;
using System.IO;
using Newtonsoft.Json.Linq;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

/// <summary>
/// PCG > Importar nivel generado...
///
/// Lee un JSON producido por generate_level.py y arma el nivel en la escena
/// activa, bajo "SpawnedObjects" (la misma raíz que usa LevelExportMenu).
///
/// Para cada objeto del JSON:
///   0. Si existe un PCGPrefabRegistry en el proyecto, usa sus prefabs primero.
///   1. Si no, busca un prefab cuyo TAG sea el del objeto (Tree, Crate, ...), sin importar
///      cómo se llame el prefab. Si no lo hay,
///      pone un cubo gris del tamaño correcto (graybox) para que el nivel se vea igual.
///      Los objetos sin tag (puentes) también salen como cubo gris. A cada cubo se le
///      asigna el material cuyo nombre sea el tag (Tree, Crate, ...) si existe.
///   2. Lo escala para que su caja mida el tamaño local que el generador eligió.
///   3. Lo gira en Y.
///   4. Lo mueve para que el CENTRO de su caja y su BASE queden donde dice el JSON
///      (así no importa dónde tenga el pivote cada prefab).
///
/// Como el resultado queda bajo "SpawnedObjects", puedes volver a correr
/// PCG > Exportar nivel actual... para exportarlo de nuevo desde Unity.
/// </summary>
public static class LevelImportMenu
{
    private const string RootObjectName = "SpawnedObjects";

    [MenuItem("PCG/Importar nivel generado...")]
    public static void ImportGeneratedLevel()
    {
        string startDir = Path.GetFullPath(Path.Combine(Application.dataPath, ".."));
        string path = EditorUtility.OpenFilePanel("Nivel generado (JSON)", startDir, "json");
        if (string.IsNullOrEmpty(path)) return;

        JObject level;
        try
        {
            level = JObject.Parse(File.ReadAllText(path));
        }
        catch (System.Exception e)
        {
            EditorUtility.DisplayDialog("JSON inválido", e.Message, "OK");
            return;
        }

        JArray objects = level["objects"] as JArray;
        if (objects == null || objects.Count == 0)
        {
            EditorUtility.DisplayDialog("Nivel vacío", "El JSON no tiene 'objects'.", "OK");
            return;
        }

        GameObject root = GameObject.Find(RootObjectName);
        if (root == null)
        {
            root = new GameObject(RootObjectName);
            Undo.RegisterCreatedObjectUndo(root, "Crear " + RootObjectName);
        }
        else if (root.transform.childCount > 0)
        {
            bool replace = EditorUtility.DisplayDialog(
                "Reemplazar nivel actual",
                $"'{RootObjectName}' ya tiene {root.transform.childCount} objetos. ¿Borrarlos antes de importar?",
                "Reemplazar", "Cancelar");
            if (!replace) return;

            for (int i = root.transform.childCount - 1; i >= 0; i--)
                Undo.DestroyObjectImmediate(root.transform.GetChild(i).gameObject);
        }

        prefabsByTag = null;   // se vuelve a indexar en cada importación
        PCGPrefabRegistry registry = FindRegistry();
        var prefabCache = new Dictionary<string, GameObject>();
        var usedPrefab = new Dictionary<string, string>();     // tag -> nombre del prefab usado
        var placeholders = new Dictionary<string, int>();      // tag -> cuántos cubos grises
        var badTags = new HashSet<string>();
        var matCache = new Dictionary<string, Material>();

        foreach (JToken o in objects)
        {
            string tag = (string)o["tag"] ?? "";
            string name = (string)o["name"] ?? tag;

            float yaw = (float)o["transform"]["rotation"]["y"];
            Vector3 bSize = ReadVector(o["boundsSize"]);
            Vector3 bCenter = ReadVector(o["boundsCenter"]);
            Vector3 localSize = o["localSize"] != null ? ReadVector(o["localSize"]) : bSize;

            string lookupTag = tag.Length > 0 ? tag : "Untagged";
            GameObject prefab = null;
            PCGPrefabRegistry.Entry entry = null;
            if (registry != null) registry.TryPick(lookupTag, out prefab, out entry);   // 1) registro
            if (prefab == null && tag.Length > 0)
                prefab = FindPrefab(tag, prefabCache);                                // 2) tag / nombre
            GameObject go;

            if (prefab != null)
            {
                go = (GameObject)PrefabUtility.InstantiatePrefab(prefab, root.transform);
                usedPrefab[lookupTag] = prefab.name;
            }
            else
            {
                go = GameObject.CreatePrimitive(PrimitiveType.Cube);
                go.transform.SetParent(root.transform, false);
                Material mat = tag.Length > 0 ? FindMaterial(tag, matCache) : null;
                if (mat != null) go.GetComponent<Renderer>().sharedMaterial = mat;
                string key = tag.Length > 0 ? tag : "(sin tag)";
                placeholders[key] = placeholders.TryGetValue(key, out int c) ? c + 1 : 1;
            }

            Undo.RegisterCreatedObjectUndo(go, "Importar " + name);
            go.name = name;

            if (tag.Length > 0 && go.tag != tag)
            {
                try { go.tag = tag; }
                catch (UnityException) { badTags.Add(tag); }   // el tag no existe en Unity
            }

            // 1) escala
            go.transform.SetPositionAndRotation(Vector3.zero, Quaternion.identity);
            Vector3 s = go.transform.localScale;
            if (entry != null && entry.keepOriginalSize)
            {
                // se respeta el tamaño del prefab; solo varía dentro de los rangos del registro
                go.transform.localScale = Vector3.Scale(s, entry.RandomFactor());
            }
            else
            {
                // que la caja sin rotar mida lo que dice localSize (tamaño del JSON)
                Bounds b = GetBounds(go);
                go.transform.localScale = new Vector3(
                    FitAxis(s.x, b.size.x, localSize.x),
                    FitAxis(s.y, b.size.y, localSize.y),
                    FitAxis(s.z, b.size.z, localSize.z));
            }

            // 2) giro en Y
            go.transform.rotation = Quaternion.Euler(0f, yaw, 0f);

            // 3) posición: centro de la caja en X/Z y base en Y, como pide el JSON
            Bounds b2 = GetBounds(go);
            float targetBaseY = bCenter.y - bSize.y * 0.5f;
            go.transform.position += new Vector3(
                bCenter.x - b2.center.x,
                targetBaseY - b2.min.y,
                bCenter.z - b2.center.z);
        }

        EditorSceneManager.MarkSceneDirty(root.scene);
        Selection.activeGameObject = root;

        // ---- resumen ----
        var sb = new System.Text.StringBuilder();
        sb.AppendLine($"[LevelImportMenu] Importados {objects.Count} objetos desde {Path.GetFileName(path)}");
        foreach (var kv in usedPrefab) sb.AppendLine($"  {kv.Key}  ->  prefab '{kv.Value}'");
        foreach (var kv in placeholders) sb.AppendLine($"  {kv.Key}  ->  {kv.Value} cubo(s) gris (no hay prefab con ese nombre)");
        foreach (string t in badTags) sb.AppendLine($"  AVISO: el tag '{t}' no existe en Unity (Edit > Project Settings > Tags and Layers)");
        Debug.Log(sb.ToString());
    }

    // ------------------------------------------------------------------ //
    private static Vector3 ReadVector(JToken v)
    {
        return new Vector3((float)v["x"], (float)v["y"], (float)v["z"]);
    }

    /// <summary>Factor de escala para que la medida actual pase a la deseada.</summary>
    private static float FitAxis(float currentScale, float currentSize, float wantedSize)
    {
        if (currentSize < 1e-4f || wantedSize < 1e-4f) return currentScale;
        float factor = wantedSize / currentSize;
        return Mathf.Abs(factor - 1f) < 0.02f ? currentScale : currentScale * factor;
    }

    /// <summary>Misma regla que SceneExporter: Renderer primero, si no Collider.</summary>
    private static Bounds GetBounds(GameObject go)
    {
        Renderer[] renderers = go.GetComponentsInChildren<Renderer>();
        if (renderers.Length > 0)
        {
            Bounds b = renderers[0].bounds;
            for (int i = 1; i < renderers.Length; i++) b.Encapsulate(renderers[i].bounds);
            return b;
        }

        Physics.SyncTransforms();
        Collider[] colliders = go.GetComponentsInChildren<Collider>();
        if (colliders.Length > 0)
        {
            Bounds b = colliders[0].bounds;
            for (int i = 1; i < colliders.Length; i++) b.Encapsulate(colliders[i].bounds);
            return b;
        }

        return new Bounds(go.transform.position, Vector3.zero);
    }

    /// <summary>Material cuyo nombre es el tag (para los cubos grises sin prefab).</summary>
    private static Material FindMaterial(string tag, Dictionary<string, Material> cache)
    {
        if (cache.TryGetValue(tag, out Material cached)) return cached;
        Material found = null;
        foreach (string guid in AssetDatabase.FindAssets("t:Material " + tag))
        {
            string assetPath = AssetDatabase.GUIDToAssetPath(guid);
            if (string.Equals(Path.GetFileNameWithoutExtension(assetPath), tag,
                              System.StringComparison.OrdinalIgnoreCase))
            {
                found = AssetDatabase.LoadAssetAtPath<Material>(assetPath);
                break;
            }
        }
        cache[tag] = found;
        return found;
    }

    private static PCGPrefabRegistry FindRegistry()
    {
        string[] guids = AssetDatabase.FindAssets("t:PCGPrefabRegistry");
        return guids.Length == 0
            ? null
            : AssetDatabase.LoadAssetAtPath<PCGPrefabRegistry>(AssetDatabase.GUIDToAssetPath(guids[0]));
    }

    private static Dictionary<string, GameObject> prefabsByTag;

    /// <summary>
    /// Prefab cuyo tag (el de su objeto raíz) es el tag pedido. Así no importa cómo se
    /// llame el prefab. Si ninguno tiene ese tag, prueba con uno cuyo nombre lo contenga.
    /// El índice se arma una sola vez por importación (recorre los prefabs del proyecto).
    /// </summary>
    private static GameObject FindPrefab(string tag, Dictionary<string, GameObject> cache)
    {
        if (cache.TryGetValue(tag, out GameObject cached)) return cached;

        if (prefabsByTag == null)
        {
            prefabsByTag = new Dictionary<string, GameObject>();
            foreach (string guid in AssetDatabase.FindAssets("t:Prefab", new[] { "Assets" }))
            {
                string assetPath = AssetDatabase.GUIDToAssetPath(guid);
                GameObject prefab = AssetDatabase.LoadAssetAtPath<GameObject>(assetPath);
                if (prefab == null) continue;

                string t = prefab.tag;
                if (t == "Untagged") continue;
                // si hay varios prefabs con el mismo tag, se queda el primero por ruta
                if (!prefabsByTag.ContainsKey(t)) prefabsByTag[t] = prefab;
            }
        }

        GameObject found;
        if (!prefabsByTag.TryGetValue(tag, out found))
        {
            foreach (string guid in AssetDatabase.FindAssets("t:Prefab " + tag))
            {
                string assetPath = AssetDatabase.GUIDToAssetPath(guid);
                string n = Path.GetFileNameWithoutExtension(assetPath);
                if (n.IndexOf(tag, System.StringComparison.OrdinalIgnoreCase) >= 0)
                {
                    found = AssetDatabase.LoadAssetAtPath<GameObject>(assetPath);
                    break;
                }
            }
        }

        cache[tag] = found;
        return found;
    }
}
#endif