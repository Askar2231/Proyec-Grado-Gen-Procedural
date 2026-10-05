using UnityEditor;
using UnityEngine;

public static class SceneIRMenu
{
	[MenuItem("Tools/SceneIR/Export Current Scene")]
	public static void Export()
	{
		SceneIR ir = SceneExporter.ExportCurrentScene();

		SceneWriter.Save(ir, "scene.json");

		Debug.Log("Scene exported!");
	}
}

