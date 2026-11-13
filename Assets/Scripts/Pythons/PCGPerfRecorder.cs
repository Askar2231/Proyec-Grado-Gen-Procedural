using System.Collections.Generic;
using System.IO;
using System.Text;
using UnityEngine;
using UnityEngine.Profiling;

/// <summary>
/// Mide el rendimiento de un nivel en Play Mode y agrega una fila a un CSV.
///
/// Uso:
///   1. Pon este componente en un objeto vacío de la escena (por ejemplo "PCGPerf").
///   2. Importa el nivel (PCG > Importar nivel generado...) o abre el nivel real.
///   3. Escribe en "Nivel" el nombre del archivo (N01, level_058, gen_agua_s0_003...).
///   4. Dale Play. Espera "Calentamiento" segundos, mide durante "Duración" y se detiene solo.
///      Si "Recorrer con la cámara" está activo, la cámara orbita el nivel a altura fija,
///      siempre con el mismo recorrido, para que todos los niveles se midan igual.
///   5. El resultado queda en  [carpeta del proyecto]/PCG_Metricas/rendimiento.csv
///
/// Para que la columna de GPU tenga datos: Project Settings > Player > Other Settings >
/// "Frame Timing Stats" activado. Medir siempre en el mismo equipo, con la misma
/// resolución y calidad, y con el Editor sin otras ventanas pesadas (o en un build).
/// </summary>
public class PCGPerfRecorder : MonoBehaviour
{
    [Header("Identificación")]
    public string nivel = "";
    public string equipo = "";

    [Header("Medición")]
    public float calentamiento = 5f;
    public float duracion = 60f;

    [Header("Recorrido de cámara")]
    public bool recorrerConCamara = true;
    public Transform raizDelNivel;          // por defecto, "SpawnedObjects"
    public float alturaCamara = 25f;
    public float radioExtra = 10f;
    public float vueltas = 1f;

    readonly List<float> frameMs = new List<float>();
    readonly List<double> gpuMs = new List<double>();
    readonly FrameTiming[] timings = new FrameTiming[1];
    float t0;
    long memMax;
    Vector3 centro;
    float radio;
    bool terminado;
    int objetos;

    void Start()
    {
        if (raizDelNivel == null)
        {
            var go = GameObject.Find("SpawnedObjects");
            if (go != null) raizDelNivel = go.transform;
        }
        if (raizDelNivel != null)
        {
            var rs = raizDelNivel.GetComponentsInChildren<Renderer>();
            objetos = raizDelNivel.childCount;
            if (rs.Length > 0)
            {
                Bounds b = rs[0].bounds;
                foreach (var r in rs) b.Encapsulate(r.bounds);
                centro = b.center;
                radio = Mathf.Max(b.extents.x, b.extents.z) + radioExtra;
            }
        }
        if (string.IsNullOrEmpty(nivel)) nivel = gameObject.scene.name;
        if (string.IsNullOrEmpty(equipo)) equipo = SystemInfo.deviceName;
        t0 = Time.realtimeSinceStartup;
    }

    void Update()
    {
        if (terminado) return;
        float t = Time.realtimeSinceStartup - t0;

        if (recorrerConCamara && Camera.main != null && radio > 0f)
        {
            float f = Mathf.Clamp01((t - 0f) / (calentamiento + duracion));
            float ang = f * vueltas * 2f * Mathf.PI;
            var cam = Camera.main.transform;
            cam.position = centro + new Vector3(Mathf.Cos(ang) * radio, alturaCamara, Mathf.Sin(ang) * radio);
            cam.LookAt(centro);
        }

        if (t < calentamiento) return;

        frameMs.Add(Time.unscaledDeltaTime * 1000f);
        FrameTimingManager.CaptureFrameTimings();
        if (FrameTimingManager.GetLatestTimings(1, timings) > 0 && timings[0].gpuFrameTime > 0)
            gpuMs.Add(timings[0].gpuFrameTime);
        memMax = System.Math.Max(memMax, Profiler.GetTotalAllocatedMemoryLong());

        if (t >= calentamiento + duracion) Terminar();
    }

    void Terminar()
    {
        terminado = true;
        if (frameMs.Count == 0) return;

        var ordenados = new List<float>(frameMs);
        ordenados.Sort();
        double suma = 0; foreach (var v in frameMs) suma += v;
        double msProm = suma / frameMs.Count;
        // 1 % más lento: promedio del 1 % de cuadros que más tardaron
        int n1 = Mathf.Max(1, ordenados.Count / 100);
        double s1 = 0; for (int i = ordenados.Count - n1; i < ordenados.Count; i++) s1 += ordenados[i];
        double ms1 = s1 / n1;
        double gpuProm = 0; foreach (var v in gpuMs) gpuProm += v;
        gpuProm = gpuMs.Count > 0 ? gpuProm / gpuMs.Count : -1;

        string dir = Path.GetFullPath(Path.Combine(Application.dataPath, "..", "PCG_Metricas"));
        Directory.CreateDirectory(dir);
        string path = Path.Combine(dir, "rendimiento.csv");
        bool nuevo = !File.Exists(path);
        var inv = System.Globalization.CultureInfo.InvariantCulture;
        var sb = new StringBuilder();
        if (nuevo)
            sb.AppendLine("fecha,nivel,equipo,objetos,cuadros,fps_promedio,fps_1pct_bajo,ms_cuadro_promedio,ms_gpu_promedio,ram_asignada_max_mb,ram_reservada_mb,resolucion,calidad");
        sb.AppendLine(string.Join(",", new[]
        {
            System.DateTime.Now.ToString("s"), nivel, equipo.Replace(",", " "), objetos.ToString(),
            frameMs.Count.ToString(),
            (1000.0 / msProm).ToString("F1", inv), (1000.0 / ms1).ToString("F1", inv),
            msProm.ToString("F2", inv), gpuProm.ToString("F2", inv),
            (memMax / 1048576.0).ToString("F1", inv),
            (Profiler.GetTotalReservedMemoryLong() / 1048576.0).ToString("F1", inv),
            $"{Screen.width}x{Screen.height}", QualitySettings.names[QualitySettings.GetQualityLevel()]
        }));
        File.AppendAllText(path, sb.ToString());
        Debug.Log($"[PCGPerfRecorder] {nivel}: {1000.0 / msProm:F1} FPS promedio, {1000.0 / ms1:F1} FPS (1 % bajo), " +
                  $"{memMax / 1048576.0:F0} MB. Guardado en {path}");
#if UNITY_EDITOR
        UnityEditor.EditorApplication.isPlaying = false;
#endif
    }
}
