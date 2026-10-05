#if UNITY_EDITOR
using System.IO;
using UnityEditor;
using UnityEngine;

/// <summary>
/// PCG > Exportar nivel actual...
///
/// Exporta solo lo que está bajo el GameObject "SpawnedObjects" de la escena
/// activa, pregunta si el nivel es aceptable/no aceptable, y lo guarda como
/// un archivo nuevo (level_001.json, level_002.json, ...) en una carpeta
/// "Dataset" fuera de Assets/ -- así Unity no reimporta cada JSON como asset
/// mientras etiquetan 10 niveles al día.
///
/// Flujo esperado: arman el nivel a mano bajo "SpawnedObjects" -> corren este
/// menú -> responden el diálogo -> limpian "SpawnedObjects" -> arman el
/// siguiente nivel.
/// </summary>
public static class LevelExportMenu
{
    private const string RootObjectName = "SpawnedObjects";

    private static string DatasetFolder =>
        Path.Combine(Application.dataPath, "Dataset");

    [MenuItem("PCG/Exportar nivel actual...")]
    public static void ExportCurrentLevel()
    {
        GameObject root = GameObject.Find(RootObjectName);

        if (root == null)
        {
            EditorUtility.DisplayDialog(
                "No se encontró la raíz",
                $"No hay ningún GameObject llamado '{RootObjectName}' en la escena activa.",
                "OK");
            return;
        }

        if (root.transform.childCount == 0)
        {
            EditorUtility.DisplayDialog(
                "Nivel vacío",
                $"'{RootObjectName}' no tiene objetos hijos -- no hay nada que exportar.",
                "OK");
            return;
        }

        SceneIR ir = SceneExporter.ExportFromRoot(root.transform);

        // 0 = Aceptable, 1 = Cancelar, 2 = No aceptable
        int choice = EditorUtility.DisplayDialogComplex(
            "Evaluación del nivel",
            $"Se detectaron {ir.objects.Count} objetos y {ir.relations.Count} relaciones.\n\n¿Este nivel es aceptable?",
            "Aceptable",
            "Cancelar (no guardar)",
            "No aceptable");

        if (choice == 1) return;

        ir.label = (choice == 0) ? 1 : 0;

        if (!Directory.Exists(DatasetFolder))
            Directory.CreateDirectory(DatasetFolder);

        int index = GetNextLevelIndex(DatasetFolder);
        ir.levelId = $"level_{index:D3}";

        string path = Path.Combine(DatasetFolder, ir.levelId + ".json");
        SceneWriter.Save(ir, path);

        Debug.Log($"[LevelExportMenu] Guardado: {path}  (label={ir.label}, objetos={ir.objects.Count}, relaciones={ir.relations.Count})");
    }

    private static int GetNextLevelIndex(string folder)
    {
        int max = 0;

        foreach (string file in Directory.GetFiles(folder, "level_*.json"))
        {
            string name = Path.GetFileNameWithoutExtension(file); // "level_007"
            string[] parts = name.Split('_');

            if (parts.Length == 2 && int.TryParse(parts[1], out int n) && n > max)
            {
                max = n;
            }
        }

        return max + 1;
    }
}
#endif