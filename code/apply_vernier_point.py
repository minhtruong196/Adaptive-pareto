"""Paste a point below, then Run Python File in VS Code. No solve by default.

Updates the disposable base_half test model and leaves it open for inspection.
Unspecified design variables reset to the saved base values, not the previous test.
"""
from pathlib import Path
import math

from vernier_model import K_FILL,BOUNDS,source_variables,design_values,number,change,clear_auto_mesh,open_project

ROOT=Path(__file__).resolve().parents[1]

# ------------------------- EDIT HERE -------------------------
POINT_ID=356                     # 356, 491, 543, 718, or 'custom'
TARGET_MODEL=ROOT/'inspection'/'vernier_pilot_20261113'/'work'/'test_point'/'base_half.aedt'
REFERENCE_MODEL=ROOT/'Verinier Ansys'/'base.aedt' # Read-only geometry anchor; never edited.
DESIGN='VM_6_28'
SAVE_MODEL=False                 # False: leave edits in memory for inspection.
RUN_FEA=False                    # True also saves the test model before solving.

# Paste your own point here, then set POINT_ID='custom'.
# Numeric values use mm, deg and A as appropriate. Partial dictionaries are OK.
# Three dependent variables are calculated automatically unless explicitly given.
# Omit I_rms to calculate it from the actual coil areas (J <= 5.5 A/mm2).
CUSTOM_POINT={
    'Dshaft':27.6,
    'Dsin':72.6,
    'Dsout':94.6,
    'k_w_axin':0.56,
    'k_w_axout':0.37,
    'slot_thickin':7,
    'slot_thickout':16.8,
    'sta_yoke_thickout':6,
    'slot_d_axin':3.5,
    'slot_d_axout':3.9,
    'slot_ang_axin':14.8,
    'slot_ang_axout':52,
    'd_pm':3.3,
}
# -------------------------------------------------------------

POINTS={
    # NSGA-II kfill=0.3: solver could not find the perimeter of a closed object.
    # Point 356: exact applied dimensions/current from the completed NSGA-II ledger.
    356:{'k_w_axin': '0.162234731087',
     'k_w_axout': '0.248248283409',
     'slot_thickin': '3.98304085846mm',
     'slot_thickout': '25.2946075749mm',
     'sta_yoke_thickout': '7.16737883663mm',
     'Dshaft': '30.2556698572mm',
     'Dsin': '68.4970281533mm',
     'Dsout': '106.648850684mm',
     'slot_d_axin': '2.77449764473mm',
     'slot_d_axout': '6.05693044612mm',
     'slot_ang_axin': '16.4495674955deg',
     'slot_ang_axout': '53.5183102647deg',
     'd_pm': '6.80987716914mm',
     'sta_yoke_thickin': '4.7721650714mm',
     'slot_tipin': '5.32550235527mm',
     'slot_tipout': '1.44306955388mm',
     'I_rms': '1.1828251456424A',
     'kfill': '0.3'},
    # Point 491: exact applied dimensions/current from the completed NSGA-II ledger.
    491:{'k_w_axin': '0.42804402006',
     'k_w_axout': '0.350007245667',
     'slot_thickin': '3.85951888141mm',
     'slot_thickout': '13.5227692423mm',
     'sta_yoke_thickout': '6.8440304859mm',
     'Dshaft': '21.0054033295mm',
     'Dsin': '72.8309878949mm',
     'Dsout': '107.238464866mm',
     'slot_d_axin': '2.3813624812mm',
     'slot_d_axout': '5.44368935134mm',
     'slot_ang_axin': '17.0448577397deg',
     'slot_ang_axout': '53.6932859209deg',
     'd_pm': '6.70513656581mm',
     'sta_yoke_thickin': '9.39729833525mm',
     'slot_tipin': '5.7186375188mm',
     'slot_tipout': '2.05631064866mm',
     'I_rms': '1.1951269380418A',
     'kfill': '0.3'},
    # Point 543: exact applied dimensions/current from the completed NSGA-II ledger.
    543:{'k_w_axin': '0.438063570223',
     'k_w_axout': '0.357670592421',
     'slot_thickin': '10.81729157mm',
     'slot_thickout': '20.6233213349mm',
     'sta_yoke_thickout': '6.83348637917mm',
     'Dshaft': '30.1466465668mm',
     'Dsin': '68.4456861633mm',
     'Dsout': '107.28980866mm',
     'slot_d_axin': '5.36735693822mm',
     'slot_d_axout': '4.52273020378mm',
     'slot_ang_axin': '17.7233774808deg',
     'slot_ang_axout': '53.9381420836deg',
     'd_pm': '6.70535111535mm',
     'sta_yoke_thickin': '4.8266767166mm',
     'slot_tipin': '2.73264306178mm',
     'slot_tipout': '2.97726979622mm',
     'I_rms': '1.1283427411951A',
     'kfill': '0.3'},
    # Point 718: exact applied dimensions/current from the completed NSGA-II ledger.
    718:{'k_w_axin': '0.492345393649',
     'k_w_axout': '0.327277163793',
     'slot_thickin': '4.45800406305mm',
     'slot_thickout': '20.4024194698mm',
     'sta_yoke_thickout': '6.82204905631mm',
     'Dshaft': '21.7342225915mm',
     'Dsin': '68.2621512862mm',
     'Dsout': '107.307603356mm',
     'slot_d_axin': '5.32871623363mm',
     'slot_d_axout': '4.49134673097mm',
     'slot_ang_axin': '12.764847008deg',
     'slot_ang_axout': '53.5168723851deg',
     'd_pm': '7.00715893199mm',
     'sta_yoke_thickin': '9.03288870425mm',
     'slot_tipin': '2.77128376637mm',
     'slot_tipout': '3.00865326903mm',
     'I_rms': '1.2081955909539A',
     'kfill': '0.3'},
}



def normalize(value,unit):
    text=str(value).strip()
    if unit and text.endswith(unit):text=text[:-len(unit)]
    try:n=float(text)
    except ValueError:raise ValueError(f'Expected a number in {unit or "dimensionless units"}: {value!r}')
    if not math.isfinite(n):raise ValueError('Point values must be finite')
    return f'{n:.14g}{unit}'


def build_values(point,base):
    extra={'sta_yoke_thickin':'mm','slot_tipin':'mm','slot_tipout':'mm','I_rms':'A','kfill':''}
    unknown=set(point)-set(BOUNDS)-set(extra)-{'Ip'}
    if unknown:raise ValueError(f'Unknown point variables: {sorted(unknown)}')
    independent={n:normalize(v,BOUNDS[n][2]) for n,v in point.items() if n in BOUNDS}
    values=design_values(base,independent)
    for n,unit in extra.items():
        if n in point:values[n]=normalize(point[n],unit)
    values['kfill']=str(K_FILL)
    if 'kfill' in point and float(point['kfill'])!=K_FILL:raise ValueError(f'kfill must remain {K_FILL}')
    if 'Ip' in point and str(point['Ip']).replace(' ','')!='I_rms*sqrt(2)':
        raise ValueError('Use I_rms; keep Ip = I_rms*sqrt(2)')
    values['Ip']='I_rms * sqrt(2)'
    if 'I_rms' not in point:values.pop('I_rms',None)
    elif number(values['I_rms'])<=0:raise ValueError('I_rms must be positive')
    return values


def target_model():
    target=Path(TARGET_MODEL).resolve()
    if not target.is_file():raise FileNotFoundError(f'Test model is missing: {target}')
    return target


def main():
    point=CUSTOM_POINT if POINT_ID=='custom' else POINTS[POINT_ID]
    target=target_model();reference=Path(REFERENCE_MODEL).resolve()
    if target==reference:raise ValueError('Test target must not be the reference base.aedt')
    values=build_values(point,source_variables(reference))
    import win32com.client
    desk=win32com.client.Dispatch('Ansoft.ElectronicsDesktop.2024.1').GetAppDesktop()
    if desk.AreThereSimulationsRunning():raise RuntimeError('Wait until the active Ansys simulations finish before editing a model')
    name=target.stem
    project=open_project(desk,target)
    design=project.SetActiveDesign(DESIGN)
    if design is None:design=project.GetActiveDesign()
    change(design,values)
    print(f'Applied point {POINT_ID} to {name}/{DESIGN} ({target})',flush=True)
    for n,v in values.items():print(f'  {n} = {v}')
    # Do not reject bad CAD here: this tool is specifically for inspecting failed points.
    try:
        editor=design.SetActiveEditor('3D Modeler')
        if editor.GetModelUnits()!='mm':raise ValueError('Expected modeler units mm')
        areas={}
        for obj in ['coil_in_1','Circle12','coil_out_1','Circle10_Separate1']:
            faces=list(editor.GetFaceIDs(obj));area=sum(float(editor.GetFaceArea(int(f))) for f in faces)
            if not faces or not math.isfinite(area) or area<=0:raise ValueError(f'Invalid area: {obj}')
            areas[obj]=area
        ain=2*areas['coil_in_1']+areas['Circle12'];aout=2*areas['coil_out_1']+areas['Circle10_Separate1']
        ni=number(design.GetVariableValue('Ntc'));no=number(design.GetVariableValue('Ntc_out'))
        current=number(values['I_rms']) if 'I_rms' in values else min(5.5*K_FILL*ain/(2*ni),5.5*K_FILL*aout/(2*no))
        change(design,{'I_rms':normalize(current,'A')})
        print(f'Irms={current:.12g} A; Jin={2*ni*current/(K_FILL*ain):.8f}; Jout={2*no*current/(K_FILL*aout):.8f} A/mm2')
    except Exception as exc:
        print(f'Area/current check failed; the geometry is left open for inspection: {exc}',flush=True)
        if RUN_FEA:raise RuntimeError('No FEA started because area/current checking failed') from exc
    removed=clear_auto_mesh(design)
    print('Removed CylindricalGap1' if removed else 'CylindricalGap1 is absent')
    if SAVE_MODEL or RUN_FEA:
        project.Save();clear_auto_mesh(design);project.Save()
    desk.RestoreWindow()
    if RUN_FEA:
        print('Starting Setup1 on the selected test model...',flush=True)
        design.Analyze('Setup1')
    else:print('No FEA started. Model stays open. Save it manually if you want to keep these edits.',flush=True)


if __name__=='__main__':main()
