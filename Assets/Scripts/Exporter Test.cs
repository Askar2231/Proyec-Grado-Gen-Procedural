using NUnit.Framework;

[TestFixture]
public class Exporter_test
{
    [Test]
    public void TestExporter()
    {
        SceneIR ir = SceneExporter.ExportCurrentScene();

        SceneWriter.Save(ir, "scene.json");
    }
}
