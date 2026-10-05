/// <summary>
/// Contrato para cualquier "constructor de relaciones" (jerarquía, espacial,
/// y las que agreguen después). Clases planas — nada de MonoBehaviour aquí,
/// porque RelationPipeline las instancia con "new".
/// </summary>
public interface IRelationBuilder
{
    void Build(SceneIR scene);
}