using System.Collections.Generic;

/// <summary>
/// Calcula las relaciones espaciales entre TODOS los pares de objetos de un nivel.
///
/// Todas las medidas salen del centro REAL de la caja (boundsCenter) y de su
/// tamaño (boundsSize), no del pivote. La distancia entre dos objetos es el
/// HUECO entre sus cajas (surfaceDistance): 0 si se tocan o se solapan, sin
/// importar qué tan grandes sean. Así un cubo pegado al borde de un plano de
/// agua de 20 unidades mide igual que dos cubos pequeños pegados.
///
/// - Near: 1/(1 + surfaceDistance), en 0..1. Se calcula para todos los pares.
/// - Above/Below: significan "APILADO". A está Above de B cuando las caras de
///   ambos se tocan en vertical (con tolerancia) Y sus huellas en el plano XZ se
///   solapan, o sea, uno realmente descansa sobre el otro.
/// - LeftOf/RightOf: eje X del mundo. Requiere un hueco mínimo en X
///   (HorizontalThreshold) y que surfaceDistance no pase de AxisMaxDistance.
/// - InFrontOf/Behind: para CUALQUIER objeto, usando su propia rotación en Y
///   (forward geométrico), dentro de OrientationMaxDistance de hueco entre cajas.
///   No hay filtro por tag.
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

    // LeftOf/RightOf:
    public static float HorizontalThreshold = 0.5f;
    public static float AxisMaxDistance = 8f;       // medido como hueco entre cajas

    // InFrontOf/Behind:
    public static float OrientationConeAngle = 45f;
    public static float OrientationMaxDistance = 6f; // medido como hueco entre cajas

    public void Build(SceneIR scene)
    {
        var objects = scene.objects;

        for (int i = 0; i < objects.Count; i++)
        {
            var a = objects[i];

            for (int j = i + 1; j < objects.Count; j++)
            {
                var b = objects[j];

                // Diferencia entre los centros reales de las cajas.
                float cdx = a.boundsCenter.x - b.boundsCenter.x;
                float cdy = a.boundsCenter.y - b.boundsCenter.y;
                float cdz = a.boundsCenter.z - b.boundsCenter.z;

                // Suma de semitamaños por eje: a esta distancia entre centros las
                // cajas quedan justo tocándose en ese eje.
                float halfSumX = (a.boundsSize.x + b.boundsSize.x) / 2f;
                float halfSumY = (a.boundsSize.y + b.boundsSize.y) / 2f;
                float halfSumZ = (a.boundsSize.z + b.boundsSize.z) / 2f;

                // Hueco entre cajas por eje (0 si se solapan en ese eje) y total.
                float gapX = NonNegative(Abs(cdx) - halfSumX);
                float gapY = NonNegative(Abs(cdy) - halfSumY);
                float gapZ = NonNegative(Abs(cdz) - halfSumZ);
                float surfaceDistance = Sqrt(gapX * gapX + gapY * gapY + gapZ * gapZ);

                // --- Near: siempre presente, como valor continuo ---
                float proximity = 1f / (1f + surfaceDistance);
                scene.relations.Add(Make(a.id, b.id, RelationType.Near, proximity));

                // --- Above / Below: APILADO (contacto vertical + huellas solapadas) ---
                float stackGap = Abs(cdy) - halfSumY;   // negativo = se solapan en vertical
                float overlapX = halfSumX - Abs(cdx);    // positivo = se solapan en X
                float overlapZ = halfSumZ - Abs(cdz);    // positivo = se solapan en Z

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

                // --- Left / Right (eje mundial X, +X = derecha) ---
                float horizontalGap = Abs(cdx) - halfSumX;
                if (horizontalGap > HorizontalThreshold && surfaceDistance <= AxisMaxDistance)
                {
                    if (cdx > 0f)
                        scene.relations.Add(Make(a.id, b.id, RelationType.RightOf, 1f));
                    else
                        scene.relations.Add(Make(a.id, b.id, RelationType.LeftOf, 1f));
                }

                // --- In front of / Behind: CUALQUIER objeto, usando su propia rotación ---
                if (surfaceDistance <= OrientationMaxDistance)
                {
                    TryAddDirectional(scene, a, b.id, -cdx, -cdz); // desde el forward de a, hacia b
                    TryAddDirectional(scene, b, a.id, cdx, cdz);   // desde el forward de b, hacia a
                }
            }
        }
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

    private static float NonNegative(float v) => v > 0f ? v : 0f;
    private static float Abs(float v) => v < 0f ? -v : v;
    private static float Sqrt(float v) => (float)System.Math.Sqrt(v);
    private static float Sin(float v) => (float)System.Math.Sin(v);
    private static float Cos(float v) => (float)System.Math.Cos(v);
    private static float Acos(float v) => (float)System.Math.Acos(v);
    private static float Clamp(float v, float min, float max) => v < min ? min : (v > max ? max : v);
}