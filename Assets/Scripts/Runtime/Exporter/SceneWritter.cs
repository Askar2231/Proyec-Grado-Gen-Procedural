using Newtonsoft.Json;
using System.IO;


public static class SceneWriter
{
    public static void Save(SceneIR scene, string path)
    {
        string json = JsonConvert.SerializeObject(scene, Formatting.Indented);

        File.WriteAllText(path, json);
    }
    
    
}

