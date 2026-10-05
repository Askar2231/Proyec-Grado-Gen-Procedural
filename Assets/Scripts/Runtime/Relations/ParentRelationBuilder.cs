/// <summary>
/// Convierte la jerarquía padre-hijo que ya captura SceneExporter
/// (SceneObjectIR.parentId) en relaciones explícitas Parent/Child
/// dentro de scene.relations.
/// </summary>
public class ParentRelationBuilder : IRelationBuilder
{
    public void Build(SceneIR scene)
    {
        foreach (var obj in scene.objects)
        {
            if (obj.parentId < 0) continue;

            scene.relations.Add(new SceneRelation
            {
                sourceId = obj.parentId,
                targetId = obj.id,
                relation = RelationType.Parent,
                value = 1f
            });

            scene.relations.Add(new SceneRelation
            {
                sourceId = obj.id,
                targetId = obj.parentId,
                relation = RelationType.Child,
                value = 1f
            });
        }
    }
}

