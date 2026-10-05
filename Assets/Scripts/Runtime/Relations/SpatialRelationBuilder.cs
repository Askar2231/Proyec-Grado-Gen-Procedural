using System.Collections.Generic;

/// <summary>
/// Calcula las relaciones espaciales entre TODOS los pares de objetos de un nivel.
///
/// - Near: valor continuo de cercanía (1/(1+distancia_de_superficie), en 0..1).
///   La distancia se corrige por tamaño: se le resta a la distancia centro-a-centro
///   un radio aproximado por objeto (derivado de su boundsSize), para que objetos
///   grandes (atalayas, estructuras) no se midan como "lejos" solo por tener el
///   pivote en el centro. Sin esto, un prop pegado a la base de una torre grande
///   podía marcar como far_from solo por la distancia al centro de la torre.
/// - Above/Below y LeftOf/RightOf: ejes del MUNDO (Y y X). Corregidos por tamaño
///   (igual que Near) Y ahora con un límite MÁXIMO de distancia — antes se
///   disparaban sin importar qué tan lejos estuvieran los objetos, lo que hacía
///   que relaciones como RightOf aparecieran en la enorme mayoría de los pares
///   de un nivel grande, sin aportar información real de composición espacial.
/// - InFrontOf/Behind: solo objetos con tag marcado como orientable — la lista
///   de tags queda VACÍA a propósito, complétala tú mismo abajo.
/// </summary>
public class SpatialRelationBuilder : IRelationBuilder
{
    public static float VerticalThreshold = 0.5f;
    public static float HorizontalThreshold = 0.5f;

    // NUEVO: límite máximo de distancia para Above/Below/LeftOf/RightOf.
    // Antes no existía — por eso una estructura en una punta del mapa y otra
    // en la otra punta igual se marcaban RightOf entre sí.
    public static float AxisMaxDistance = 8f;

    public static float OrientationConeAngle = 45f;
    public static float OrientationMaxDistance = 6f;

    // Vacía a propósito -- completa aquí los tags de tus objetos orientables
    // (ej. "Cabin", "Bridge", "Stairs"...).
    private static readonly HashSet<string> OrientedTags = new()
    {
        "Structure1","Structure2","Structure3","Structure4", "Bridge", "Rocks", "Crate", "ArmorStand", "Tree", "Chest", "Enemy"
    };

    public void Build(SceneIR scene)
    {
        var objects = scene.objects;

        for (int i = 0; i < objects.Count; i++)
        {
            var a = objects[i];

            for (int j = i + 1; j < objects.Count; j++)
            {
                var b = objects[j];

                float dx = a.transform.position.x - b.transform.position.x;
                float dy = a.transform.position.y - b.transform.position.y;
                float dz = a.transform.position.z - b.transform.position.z;

                float centerDistance = Sqrt(dx * dx + dy * dy + dz * dz);

                // --- Near: corregido por tamaño (distancia de superficie aproximada) ---
                float radiusA = BoundingRadius(a);
                float radiusB = BoundingRadius(b);
                float surfaceDistance = centerDistance - radiusA - radiusB;
                if (surfaceDistance < 0f) surfaceDistance = 0f; // objetos que se solapan/tocan

                float proximity = 1f / (1f + surfaceDistance);
                scene.relations.Add(Make(a.id, b.id, RelationType.Near, proximity));

                // --- Above / Below (eje mundial Y, corregido por altura, con límite de distancia) ---
                float verticalGap = Abs(dy) - (a.boundsSize.y / 2f + b.boundsSize.y / 2f);
                if (verticalGap > VerticalThreshold && centerDistance <= AxisMaxDistance)
                {
                    if (dy > 0f)
                        scene.relations.Add(Make(a.id, b.id, RelationType.Above, 1f));
                    else
                        scene.relations.Add(Make(a.id, b.id, RelationType.Below, 1f));
                }

                // --- Left / Right (eje mundial X, +X = derecha, corregido por ancho, con límite de distancia) ---
                float horizontalGap = Abs(dx) - (a.boundsSize.x / 2f + b.boundsSize.x / 2f);
                if (horizontalGap > HorizontalThreshold && centerDistance <= AxisMaxDistance)
                {
                    if (dx > 0f)
                        scene.relations.Add(Make(a.id, b.id, RelationType.RightOf, 1f));
                    else
                        scene.relations.Add(Make(a.id, b.id, RelationType.LeftOf, 1f));
                }

                // --- In front of / Behind (solo si el ORIGEN es orientable) ---
                if (OrientedTags.Contains(a.tag) && centerDistance <= OrientationMaxDistance)
                {
                    TryAddDirectional(scene, a, b.id, -dx, -dz);
                }

                if (OrientedTags.Contains(b.tag) && centerDistance <= OrientationMaxDistance)
                {
                    TryAddDirectional(scene, b, a.id, dx, dz);
                }
            }
        }
    }

    /// <summary>
    /// Aproximación barata de un "radio" a partir del tamaño de la caja delimitadora:
    /// promedio de los 3 semi-ejes. No es geometría exacta (eso sería distancia
    /// caja-a-caja), pero corrige el grueso del problema con objetos grandes sin
    /// agregar mucho código.
    /// </summary>
    private static float BoundingRadius(SceneObjectIR obj)
    {
        var s = obj.boundsSize;
        return (s.x + s.y + s.z) / 6f;
    }

    private void TryAddDirectional(SceneIR scene, SceneObjectIR origin, int targetId, float toTargetX, float toTargetZ)
    {
        float yawRad = origin.transform.rotation.y * (3.14159265f / 180f);
        float forwardX = Sin(yawRad);
        float forwardZ = Cos(yawRad);

        float toTargetLength = Sqrt(toTargetX * toTargetX + toTargetZ * toTargetZ);
        if (toTargetLength < 0.0001f) return;

        float dot = (forwardX * toTargetX + forwardZ * toTargetZ) / toTargetLength;
        dot = Clamp(dot, -1f, 1f);
        float angle = Acos(dot) * (180f / 3.14159265f);

        if (angle <= OrientationConeAngle)
        {
            scene.relations.Add(Make(origin.id, targetId, RelationType.InFrontOf, 1f));
        }
        else if (angle >= 180f - OrientationConeAngle)
        {
            scene.relations.Add(Make(origin.id, targetId, RelationType.Behind, 1f));
        }
    }

    private static SceneRelation Make(int source, int target, RelationType type, float value)
    {
        return new SceneRelation { sourceId = source, targetId = target, relation = type, value = value };
    }

    private static float Abs(float v) => v < 0f ? -v : v;
    private static float Sqrt(float v) => (float)System.Math.Sqrt(v);
    private static float Sin(float v) => (float)System.Math.Sin(v);
    private static float Cos(float v) => (float)System.Math.Cos(v);
    private static float Acos(float v) => (float)System.Math.Acos(v);
    private static float Clamp(float v, float min, float max) => v < min ? min : (v > max ? max : v);
}