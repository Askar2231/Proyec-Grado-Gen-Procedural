using System;
using System.Collections.Generic;
using UnityEngine;

/// <summary>
/// Tabla "tag -> prefabs" y ajustes de tamaño para el importador de niveles generados.
///
/// Crear: clic derecho en Project > Create > PCG > Prefab Registry.
/// Una entrada por tag (Tree, Crate, ...), con uno o más prefabs (si hay varios, el
/// importador elige uno al azar por objeto). "Untagged" sirve para objetos sin tag.
///
/// TAMAÑO (por entrada):
///   keepOriginalSize = apagado -> el prefab se escala para medir lo que dice el JSON.
///   keepOriginalSize = encendido -> se respeta el tamaño del prefab, y a cada objeto se
///                      le aplica un factor al azar dentro de estos rangos:
///                        widthRange  (ancho  = eje X del objeto)
///                        heightRange (altura = eje Y)
///                        lengthRange (largo  = eje Z)
///                      (1, 1) = sin variación. (0.8, 1.2) = entre 80 % y 120 %.
///                      keepProportions = un solo factor (widthRange) para los tres ejes.
/// Va en Assets/ (no en una carpeta Editor); solo la lee LevelImportMenu.
/// </summary>
[CreateAssetMenu(fileName = "PCGPrefabRegistry", menuName = "PCG/Prefab Registry")]
public class PCGPrefabRegistry : ScriptableObject
{
    [Serializable]
    public class Entry
    {
        public string tag;
        public List<GameObject> prefabs = new List<GameObject>();

        [Tooltip("Apagado: se escala al tamaño del JSON. Encendido: se respeta el del prefab.")]
        public bool keepOriginalSize = false;

        [Tooltip("Factores (mín, máx) sobre el tamaño del prefab. Solo con keepOriginalSize.")]
        public Vector2 widthRange = Vector2.one;
        public Vector2 heightRange = Vector2.one;
        public Vector2 lengthRange = Vector2.one;

        [Tooltip("Un solo factor (el de widthRange) para ancho, alto y largo.")]
        public bool keepProportions = false;

        /// <summary>Factor de escala al azar por eje (ancho, alto, largo).</summary>
        public Vector3 RandomFactor()
        {
            float w = Roll(widthRange);
            if (keepProportions) return new Vector3(w, w, w);
            return new Vector3(w, Roll(heightRange), Roll(lengthRange));
        }

        private static float Roll(Vector2 r)
        {
            float lo = Mathf.Min(r.x, r.y), hi = Mathf.Max(r.x, r.y);
            return Mathf.Approximately(lo, hi) ? lo : UnityEngine.Random.Range(lo, hi);
        }
    }

    public List<Entry> entries = new List<Entry>();

    /// <summary>Un prefab al azar de la entrada con ese tag (y la entrada), o false.</summary>
    public bool TryPick(string tag, out GameObject prefab, out Entry entry)
    {
        prefab = null;
        entry = null;
        foreach (Entry e in entries)
        {
            if (!string.Equals(e.tag, tag, StringComparison.OrdinalIgnoreCase)) continue;
            var valid = e.prefabs.FindAll(p => p != null);
            if (valid.Count == 0) return false;
            prefab = valid[UnityEngine.Random.Range(0, valid.Count)];
            entry = e;
            return true;
        }
        return false;
    }
}
