# ----------------------------------------------
# Script Recorded by Ansys Electronics Desktop Version 2024.1.0
# 14:18:31  Nov 13, 2026
# ----------------------------------------------
import ScriptEnv
ScriptEnv.Initialize("Ansoft.ElectronicsDesktop")
oDesktop.RestoreWindow()
oProject = oDesktop.SetActiveProject("base")
oDesign = oProject.SetActiveDesign("VM_6_28")
oDesign.ChangeProperty(
	[
		"NAME:AllTabs",
		[
			"NAME:LocalVariableTab",
			[
				"NAME:PropServers",
				"LocalVariables"
			],
			[
				"NAME:ChangedProps",
				[
					"NAME:Dshaft",
					"Value:="		, "27.6mm"
				]
			]
		]
	])
oProject.Save()
oDesign.Analyze("Setup1")
oModule = oDesign.GetModule("ReportSetup")
oModule.ExportToFile("Torque", "D:/Project python/2026/adaptive pareto_Intermag 2027/Verinier Ansys/Torque.csv", False)
