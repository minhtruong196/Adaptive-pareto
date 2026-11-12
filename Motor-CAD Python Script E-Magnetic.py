# Import the relevant packages - these must be installed first
# See the Motor-CAD ActiveX tutorial section 7 for more information
import win32com.client
import matplotlib.pyplot as plt

# Retain pyqt4 compatibility
import os
if "QT_API" in os.environ:
    os.environ["QT_API"] = "pyqt"

## User setup
# Change this to a location on your PC where you would like to save the model/results files.
# This folder must exist
# Make sure the folder path ends in \\
workingFolder = "C:\\Workspace\\ActiveX Scripting in Motor-CAD\\"

if os.path.isdir(workingFolder) == False:
    print('Working folder does not exist. Please choose a folder that exists and try again.')
    print(workingFolder)
    exit()

# Initialise ActiveX automation and launch Motor-CAD
print('Start Initialisation')
mcad = win32com.client.Dispatch("MotorCAD.AppAutomation")

# Disable all popup messages from Motor-CAD
mcad.SetVariable('MessageDisplayState', 2)
print('Initialisation Complete')
print('Running Simulation')

# Show magnetic context
mcad.ShowMagneticContext()

# Display scripting tab
mcad.DisplayScreen('Scripting')

# Set Geometry
mcad.SetVariable('Slot_Number', 24)
mcad.SetVariable('Tooth_Width', 6)
mcad.SetVariable('Magnet_Thickness', 4.5)

# Custom Winding Example
# This gives an example of the commands needed to create a custom winding pattern
# This will not create a full winding pattern - need to specify parameters for all coils
## Set the winding type to custom
#mcad.SetVariable('MagWindingType', 1)
## Set the Path type to Upper and Lower
#mcad.SetVariable('MagPathType', 1)
## Set the number of phases, parallel paths and winding layers:
#mcad.SetVariable('MagPhases', 3)
#mcad.SetVariable('ParallelPaths', 1)
#mcad.SetVariable('WindingLayers', 2)
## Define a coil's parameters
## SetWindingCoil(Phase, Path, Coil, Goslot, GoPosition, ReturnSlot, ReturnPoisition, Turns)
#mcad.SetWindingCoil(2, 1, 3, 4, 'b', 18, 'a', 60)


# Set the stator/rotor lamination materials
mcad.SetComponentMaterial('Stator Lam (Back Iron', 'M250-35A')
mcad.SetComponentMaterial('Rotor Lam (Back Iron)', 'M250-35A')

# Set the torque calculation options
PointsPerCycle = 30
NumberCycles = 1
mcad.SetVariable('TorquePointsPerCycle', PointsPerCycle)
mcad.SetVariable('TorqueNumberCycles', NumberCycles)

# Disable all performance tests except for transient torque
mcad.SetVariable('BackEMFCalculation', False)
mcad.SetVariable('CoggingTorqueCalculation', False)
mcad.SetVariable('ElectromagneticForcesCalc_OC', False)
mcad.SetVariable('TorqueSpeedCalculation', False)
mcad.SetVariable('DemagnetizationCalc', False)
mcad.SetVariable('ElectromagneticForcesCalc_Load', False)
mcad.SetVariable('InductanceCalc', False)
mcad.SetVariable('BPMShortCircuitCalc', False)
# Enable transient torque
mcad.SetVariable('TorqueCalculation', True)

# Set the operating point
mcad.SetVariable('Shaft_Speed_[RPM]', 1000)
mcad.SetVariable('CurrentDefinition', 0)
mcad.SetVariable('PeakCurrent', 3)
mcad.SetVariable('DCBusVoltage', 350)
mcad.SetVariable('PhaseAdvance', 45)

# Save the file
filename = workingFolder + 'ActiveX_Scripting_EMagnetic.mot'
mcad.SaveToFile(filename)

# Run the simulation and report success
success = mcad.DoMagneticCalculation()
if success == 0:
    mcad.ShowMessage("Magnetic calculation successfully completed")
else:
    mcad.ShowMessage("Magnetic calculation failed")

# Export data to csv file
exportFile = workingFolder + 'Export_EMag_Results.csv'
success = mcad.ExportResults('EMagnetic', exportFile)
if success == 0:
    mcad.ShowMessage("Results successfully exported")
else:
    mcad.ShowMessage("Results failed to export")

# Get results
success, ShaftTorque = mcad.GetVariable("ShaftTorque")
success, LineVoltage = mcad.GetVariable("PeakLineLineVoltage")

# Torque graph data
NumTorquePoints = (PointsPerCycle * NumberCycles) + 1
RotorPosition = []
TorqueVW = []
for n in range(NumTorquePoints):
    (success, x, y) = mcad.GetMagneticGraphPoint("TorqueVW", n)
    if success == 0:
        RotorPosition.append(x)
        TorqueVW.append(y)

# Airgap flux density graph data
loop = 0
success = 0
MechAngle = []
AirgapFluxDensity = []
# Keep looking until we cannot find the point
while success == 0:
    (success, x, y) = mcad.GetFEAGraphPoint('B Gap (on load)', 1, loop, 0)
    if success == 0:
        MechAngle.append(x)
        AirgapFluxDensity.append(y)
    loop = loop + 1


# Harmonics
mcad.InitialiseTabNames()
mcad.DisplayScreen('Graphs;Harmonics;Torque')

NumHarmonicPoints = (PointsPerCycle * NumberCycles) + 1
DataPoint = []
Torque = []
for n in range(NumHarmonicPoints):
    (success, x, y) = mcad.GetMagneticGraphPoint("HarmonicDataCycle", n)
    if success == 0:
        DataPoint.append(x)
        Torque.append(y)


print('Simulation Complete')

# Create Graph
plt.figure(1)
plt.subplot(211)
plt.plot(MechAngle, AirgapFluxDensity)
plt.xlabel('Mech Angle')
plt.ylabel('Airgap Flux Density')
plt.subplot(212)
plt.plot(RotorPosition, TorqueVW)
plt.xlabel('Rotor Position')
plt.ylabel('TorqueVW')
plt.figure(2)
plt.plot(DataPoint, Torque)
plt.xlabel('DataPoint')
plt.ylabel('Torque (Nm)')
plt.show()

# Close Motor-CAD
mcad.Quit()
# If you wish to continue working with this instance of Motor-CAD, use the
# following line instead of Quit:
#mcad.SetVariable('MessageDisplayState', 0)
