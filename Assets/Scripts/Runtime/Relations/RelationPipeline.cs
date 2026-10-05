using System.Collections.Generic;

/// <summary>
/// Corre todos los IRelationBuilder registrados sobre el SceneIR, en orden.
/// Este archivo reemplaza tanto al antiguo "RelationBuilder.cs" (que tenía
/// el código pero le faltaba el using) como al stub vacío "RelationPipeline.cs"
/// generado por Unity — solo debe quedar UNO de los dos nombres de archivo,
/// usa este.
/// </summary>
public static class RelationPipeline
{
    private static readonly List<IRelationBuilder> builders = new()
    {
        new ParentRelationBuilder(),
        new SpatialRelationBuilder()
    };

    public static void Build(SceneIR scene)
    {
        foreach (var builder in builders)
            builder.Build(scene);
    }
}