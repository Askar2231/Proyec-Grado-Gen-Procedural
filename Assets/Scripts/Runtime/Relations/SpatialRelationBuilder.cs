using System.Collections.Generic;

/// <summary>
/// Calcula las relaciones espaciales entre TODOS los pares de objetos de un nivel.
///
/// - Near: valor continuo de cercanía (1/(1+distancia_de_superficie), en 0..1).
///   La distancia se corrige por tamaño: se le resta a la distancia centro-a-centro
///   un radio aproximado por objeto (derivado de su boundsSize), para que objetos
///   grandes (atalayas, estructuras) no se midan como "lejos" solo por tener el
///   pivote en el centro.
/// - Above/Below: significan "APILADO". A está Above de B cuando las caras de
///   ambos se tocan en vertical (con tolerancia) Y sus huellas en el plano XZ se
///   solapan, o sea, uno realmente descansa sobre el otro. Usa el centro REAL de
///   la caja (boundsCenter), no el pivote. Un objeto más alto pero desplazado a un
///   lado, o flotando lejos, ya NO genera Above.
/// - LeftOf/RightOf: ejes del MUNDO (X). Corregidos por tamaño y con un límite
///   MÁXIMO de distancia (AxisMaxDistance), para que no se disparen entre objetos
///   en puntas opuestas de un nivel grande.
/// - InFrontOf/Behind: para CUALQUIER objeto, usando su propia rotación
///   (forward geométrico). Todo objeto tiene una "cara frontal" técnica,
///   aunque no tenga un frente semántico obvio (un árbol también cuenta) —
///   no hay filtro por tag.
/// </summary>
public class SpatialRelationBuilder : IRelationBuilder
{
    // Above/Below (apilado):
    // StackContactTolerance: separación máxima entre la cara de arriba de uno y la
    //   de abajo del otro para seguir contando como "en contacto".
    // StackPenetrationTolerance: cuánto puede estar hundido uno en el otro (una
    //   roca a medio enterrar en el suelo, un árbol clavado en un plano de agua).
    // FootprintMinOverlap: solape mínimo en X y en Z para que cuente como apoyado.
    public static float StackContactTolerance = 0.2f;
    public static float StackPenetrationTolerance = 0.3f;
    public static float FootprintMinOverlap = 0.05f;

    public static float HorizontalThreshold = 0.5f;
    public static float AxisMaxDistance = 8f;

    public static float OrientationConeAngle = 45f;
    public static float OrientationMaxDistance = 6f;

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
                if (surfaceDistance < 0f) surfaceDistance = 0f;

                float proximity = 1f / (1f + surfaceDistance);
                scene.relations.Add(Make(a.id, b.id, RelationType.Near, proximity));

                // --- Above / Below: APILADO (contacto vertical + huellas solapadas) ---
                float cdx = a.boundsCenter.x - b.boundsCenter.x;
                float cdy = a.boundsCenter.y - b.boundsCenter.y;
                float cdz = a.boundsCenter.z - b.boundsCenter.z;

                // Espacio libre entre las caras (negativo = se solapan en vertical).
                float stackGap = Abs(cdy) - (a.boundsSize.y / 2f + b.boundsSize.y / 2f);

                // Solape de las huellas en X y en Z (positivo = se solapan).
                float overlapX = (a.boundsSize.x + b.boundsSize.x) / 2f - Abs(cdx);
                float overlapZ = (a.boundsSize.z + b.boundsSize.z) / 2f - Abs(cdz);

                bool touchingVertically =
                    stackGap <= StackContactTolerance &&
                    stackGap >= -StackPenetrationTolerance;

                bool footprintsOverlap =
                    overlapX > FootprintMinOverlap &&
                    overlapZ > FootprintMinOverlap;

                if (touchingVertically && footprintsOverlap)
                {
                    if (cdy > 0f)
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

                // --- In front of / Behind: CUALQUIER objeto, usando su propia rotación ---
                if (centerDistance <= OrientationMaxDistance)
                {
                    TryAddDirectional(scene, a, b.id, -dx, -dz); // desde el forward de a, hacia b
                    TryAddDirectional(scene, b, a.id, dx, dz);   // desde el forward de b, hacia a
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