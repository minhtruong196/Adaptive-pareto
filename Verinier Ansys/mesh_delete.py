# ----------------------------------------------
# Script Recorded by Ansys Electronics Desktop Version 2024.1.0
# 20:44:03  Nov 13, 2026
# ----------------------------------------------
import ScriptEnv
ScriptEnv.Initialize("Ansoft.ElectronicsDesktop")
oDesktop.RestoreWindow()
oProject = oDesktop.SetActiveProject("base_backup")
oDesign = oProject.SetActiveDesign("VM_6_28")
oModule = oDesign.GetModule("MeshSetup")
oModule.DeleteOp(["CylindricalGap1"])
