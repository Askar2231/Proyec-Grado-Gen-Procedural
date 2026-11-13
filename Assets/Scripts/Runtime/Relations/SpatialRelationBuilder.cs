using System.Collections.Generic;

public class SpatialRelationBuilder : IRelationBuilder
{
    public static float StackContactTolerance = 0.2f;
    public static float StackPenetrationTolerance = 0.3f;
    public static float FootprintMinOverlap = 0.05f;
    public static float OrientationConeAngle = 45f;
    public static float OrientationMaxDistance = 6f;   // InFrontOf / Behind
    public static float AxisMaxDistance = 8f;          // LeftOf / RightOf

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

                // --- InFrontOf / Behind / LeftOf / RightOf: marco local de cada objeto ---
                float maxDirectional = OrientationMaxDistance > AxisMaxDistance
                    ? OrientationMaxDistance
                    : AxisMaxDistance;

                if (surfaceDistance <= maxDirectional)
                {
                    TryAddDirectional(scene, a, b.id, -cdx, -cdz, surfaceDistance); // desde a, hacia b
                    TryAddDirectional(scene, b, a.id, cdx, cdz, surfaceDistance);   // desde b, hacia a
                }
            }
        }
    }

    /// <summary>
    /// Ubica al destino en el marco local del origen. toTargetX/Z es el vector
    /// origen -> destino en el plano XZ del mundo; el delante y la derecha del
    /// origen salen de su rotación en Y (Unity: delante = (sin yaw, cos yaw),
    /// derecha = (cos yaw, -sin yaw)).
    /// </summary>
    private void TryAddDirectional(
        SceneIR scene,
        SceneObjectIR origin,
        int targetId,
        float toTargetX,
        float toTargetZ,
        float surfaceDistance)
    {
        float yawRad = origin.transform.rotation.y * (3.14159265f / 180f);
        float forwardX = Sin(yawRad);
        float forwardZ = Cos(yawRad);
        float rightX = Cos(yawRad);
        float rightZ = -Sin(yawRad);

        float toTargetLength = Sqrt(toTargetX * toTargetX + toTargetZ * toTargetZ);
        if (toTargetLength < 0.0001f) return;

        float dot = (forwardX * toTargetX + forwardZ * toTargetZ) / toTargetLength;
        dot = Clamp(dot, -1f, 1f);
        float angle = Acos(dot) * (180f / 3.14159265f);

        if (angle <= OrientationConeAngle)
        {
            if (surfaceDistance <= OrientationMaxDistance)
                scene.relations.Add(Make(origin.id, targetId, RelationType.InFrontOf, 1f));
        }
        else if (angle >= 180f - OrientationConeAngle)
        {
            if (surfaceDistance <= OrientationMaxDistance)
                scene.relations.Add(Make(origin.id, targetId, RelationType.Behind, 1f));
        }
        else if (surfaceDistance <= AxisMaxDistance)
        {
            // Sector lateral: el signo de la componente a lo largo de la derecha
            // local decide si el destino queda a la derecha o a la izquierda.
            float lateral = rightX * toTargetX + rightZ * toTargetZ;

            if (lateral > 0f)
                scene.relations.Add(Make(origin.id, targetId, RelationType.RightOf, 1f));
            else
                scene.relations.Add(Make(origin.id, targetId, RelationType.LeftOf, 1f));
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