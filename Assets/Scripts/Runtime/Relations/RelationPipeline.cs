using System.Collections.Generic;
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