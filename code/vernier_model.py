"""Vernier geometry, bounded worker pool, and SI waveform postprocessing."""
import hashlib
import json
import math
import re
import shutil
import numpy as np
from pathlib import Path

K_FILL=0.3  # Campaign fill factor; override the saved template before every evaluation.
CONSTRAINTS_VERSION=7  # Winding reserve 1 mm; magnet d_pm width reserve 0.1 mm.
MESH_POLICY_VERSION=2  # Check actual operations, not only an initialization flag.
MODEL_REVISION='vernier-half-maxwell2024.1-si-v1'

BOUNDS={
    'k_w_axin':(.30,.80,''),'k_w_axout':(.20,.45,''),
    'slot_thickin':(5,9,'mm'),'slot_thickout':(12,22,'mm'),
    'sta_yoke_thickout':(4,8,'mm'),'Dshaft':(22,34,'mm'),
    'Dsin':(66,80,'mm'),'Dsout':(88,102,'mm'),
    'slot_d_axin':(2,5.5,'mm'),'slot_d_axout':(2,6,'mm'),
    'slot_ang_axin':(10,22,'deg'),'slot_ang_axout':(42,56,'deg'),'d_pm':(3,7,'mm')}
RESET=tuple(BOUNDS)+('sta_yoke_thickin','slot_tipin','slot_tipout','I_rms','kfill')


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def number(value):
    m=re.fullmatch(r'\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s*(?:mm|deg|A|Hz)?\s*',str(value))
    if not m:raise ValueError(f'Expected a numeric model value, got {value!r}')
    result=float(m[1])
    if not math.isfinite(result):raise ValueError('Model value must be finite')
    return result


def source_variables(path):
    values=dict(re.findall(r"VariableProp\('([^']+)',\s*'[^']*',\s*'[^']*',\s*'([^']*)'\)",Path(path).read_text(errors='replace')))
    if not values:raise ValueError(f'No model variables found in {path}')
    return values


def _configuration(base):
    """Saved optimized values vary; the three physical coupling anchors do not."""
    anchors=dict(inner_shaft_yoke_mm=round(number(base['Dshaft'])/2+number(base['sta_yoke_thickin']),8),
                 inner_slot_depth_tip_mm=round(number(base['slot_d_axin'])+number(base['slot_tipin']),8),
                 outer_slot_depth_tip_mm=round(number(base['slot_d_axout'])+number(base['slot_tipout']),8))
    return dict(model_revision=MODEL_REVISION,
                fixed_variables={n:base[n] for n in sorted(base) if n not in RESET},
                coupling_anchors=anchors)


def configuration_signature(source):
    base=source if isinstance(source,dict) else source_variables(source)
    return hashlib.sha256(json.dumps(_configuration(base),sort_keys=True).encode()).hexdigest()


def model_identity(source):
    """Configuration identity, stable across saved optimization points and clones."""
    base=source if isinstance(source,dict) else source_variables(source)
    return dict(_configuration(base),configuration_signature=configuration_signature(base))


def design_values(base,point):
    values={n:v for n,v in base.items() if n in RESET}
    for n,v in point.items():
        if n not in BOUNDS:raise ValueError(f'Unknown optimization variable: {n}')
        values[n]=v if isinstance(v,str) else f'{float(v):.12g}{BOUNDS[n][2]}'
    y=number(base['sta_yoke_thickin'])-(number(values['Dshaft'])-number(base['Dshaft']))/2
    values['sta_yoke_thickin']=f'{y:.12g}mm'
    for side in ['in','out']:
        total=number(base['slot_d_ax'+side])+number(base['slot_tip'+side])
        values['slot_tip'+side]=f"{total-number(values['slot_d_ax'+side]):.12g}mm"
    values['kfill']=str(K_FILL)
    return values


def margins(point,base):
    v={n:number(s) for n,s in design_values(base,point).items()}
    for n in ['g','pm_bridin','pm_bridout','Ns','p','Dsout_out']:v[n]=number(base[n])
    return dict(inner_yoke_mm=v['sta_yoke_thickin'],inner_depth_mm=v['slot_d_axin'],
      outer_depth_mm=v['slot_d_axout'],inner_tip_mm=v['slot_tipin'],outer_tip_mm=v['slot_tipout'],
      inner_winding_mm=v['Dsin']/2-v['slot_d_axin']-v['slot_tipin']-v['Dshaft']/2-v['sta_yoke_thickin']-1.0,
      outer_winding_mm=v['Dsout_out']/2-v['sta_yoke_thickout']-v['Dsout']/2-v['slot_d_axout']-v['slot_tipout']-1.0,
      magnet_radial_mm=(v['Dsout']-4*v['g']-v['Dsin'])/2-v['pm_bridin']-v['pm_bridout'],
      inner_angle_deg=180/v['Ns']-v['slot_ang_axin'],outer_angle_deg=360/v['Ns']-v['slot_ang_axout'],
      inner_split_tooth_clearance_mm=v['Dsin']/2-(v['Dsin']/2-v['slot_d_axin']-v['slot_tipin'])/math.cos(math.radians(v['slot_ang_axin']))-v['slot_d_axin'],
      magnet_width_reserve_mm=(v['Dsin']+2*v['g'])*math.tan(math.radians(180/v['p']))-v['d_pm']-0.1)


def make_plan(n,seed,bounds,base):
    from scipy.stats import qmc
    import numpy as np
    if n<1:raise ValueError('N_SAMPLES must be positive')
    for lo,hi,_ in bounds.values():
        if not math.isfinite(lo+hi) or lo>=hi:raise ValueError('Invalid bounds')
    sampler=qmc.LatinHypercube(len(bounds),seed=seed)
    lo=np.array([v[0] for v in bounds.values()]);span=np.array([v[1]-v[0] for v in bounds.values()])
    accepted={}
    # Rejection filtering changes the strict LHS marginal stratification.
    for _ in range(1000):
        for x in lo+sampler.random(max(64,n*4))*span:
            p=dict(zip(bounds,map(float,np.round(x,8))))
            if min(margins(p,base).values())>1e-8:accepted.setdefault(tuple(p.values()),p)
            if len(accepted)==n:return list(accepted.values())
    raise ValueError('Cannot sample enough feasible points; inspect bounds/constraints')


def atomic_json(path,data):
    path=Path(path);tmp=path.with_suffix('.tmp')
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp.write_text(json.dumps(data,indent=2,allow_nan=False),encoding='utf-8');tmp.replace(path)


def worker_pool(run_dir,source,source_hash=None,legacy_manifest=None,prefix="worker"):
    """Create a fresh owned pool; never adopt historical campaign worker models."""
    run_dir=Path(run_dir).resolve();source=Path(source).resolve()
    source_hash=source_hash or digest(source)
    identity=model_identity(source)
    path=Path(run_dir)/'workers.json'
    if path.exists():pool=json.loads(path.read_text(encoding='utf-8'))
    else:
        pool=dict(source_sha256=source_hash,model_identity=identity,
                  source=str(source),base_variables=source_variables(source),workers=[])
        for i in range(1,6):
            model=Path(run_dir)/'work'/f'{prefix}_{i:02d}'/f'{prefix}_{i:02d}.aedt'
            if model.resolve()==source:raise ValueError('Worker must not overwrite the source model')
            if model.exists():raise ValueError(f'Unregistered model exists: {model}')
            model.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,model)
            pool['workers'].append(dict(worker=i,model=str(model),initialized=False))
        atomic_json(path,pool)
    if pool.get('model_identity')!=identity:raise ValueError('Source configuration changed; select a new worker pool')
    if len(pool['workers'])!=5 or not all(Path(w['model']).is_file() for w in pool['workers']):
        raise ValueError('Incomplete worker pool; check workers.json')
    models=[Path(w['model']).resolve() for w in pool['workers']]
    if len(set(models))!=5 or any(m==source or not m.is_relative_to(run_dir/'work') for m in models):
        raise ValueError('Worker pool does not own five independent project paths')
    return pool


def change(design,values):
    design.ChangeProperty(['NAME:AllTabs',['NAME:LocalVariableTab',
      ['NAME:PropServers','LocalVariables'],['NAME:ChangedProps']+
      [['NAME:'+n,'Value:=',v] for n,v in values.items()]]])


def clear_auto_mesh(design):
    operations=list(design.GetChildObject('Mesh').GetChildNames())
    if 'CylindricalGap1' not in operations:return False
    design.GetModule('MeshSetup').DeleteOp(['CylindricalGap1'])
    if 'CylindricalGap1' in list(design.GetChildObject('Mesh').GetChildNames()):
        raise RuntimeError('CylindricalGap1 could not be removed')
    return True


def open_project(desktop,model):
    model=Path(model).resolve();name=model.stem
    # Bind to the named project, independent of UI focus and other active solves.
    if name in list(desktop.GetProjectList()):
        project=desktop.GetChildObject(name)
    else:
        project=desktop.OpenProject(str(model))
        if project is None:project=desktop.GetChildObject(name)
    actual=(Path(str(project.GetPath()))/(name+'.aedt')).resolve()
    if actual!=model:
        raise ValueError(f'Project path mismatch for {name}: expected {model}; actual {actual}')
    return project


def prepare(desktop,worker,pool,run_dir,point,design_name):
    model=Path(worker['model']);name=model.stem
    project=open_project(desktop,model)
    design=project.SetActiveDesign(design_name)
    if design is None:design=project.GetActiveDesign()
    base=pool['base_variables']
    expected=set(RESET)
    if not expected.issubset(base):raise ValueError('Base variable snapshot is incomplete')
    fixed={str(n):str(design.GetVariableValue(n)) for n in design.GetVariables() if n not in RESET}
    if any(v!=base.get(n) for n,v in fixed.items()):raise ValueError('Fixed worker parameters differ from source model')
    m=margins(point,base)
    if min(m.values())<=0:raise ValueError(f'Analytic geometry constraint failed: {m}')
    change(design,design_values(base,point))
    if design.ValidateDesign(str(model.parent/'validation.txt'))!=1:raise ValueError('Ansys Validation Check failed')
    editor=design.SetActiveEditor('3D Modeler')
    if editor.GetModelUnits()!='mm':raise ValueError('Modeler area units must be mm2')
    areas={}
    for obj in ['coil_in_1','Circle12','coil_out_1','Circle10_Separate1']:
        faces=list(editor.GetFaceIDs(obj))
        a=sum(float(editor.GetFaceArea(int(f))) for f in faces)
        if not faces or not math.isfinite(a) or a<=0:raise ValueError(f'Invalid coil area: {obj}')
        areas[obj]=a
    ain=2*areas['coil_in_1']+areas['Circle12'];aout=2*areas['coil_out_1']+areas['Circle10_Separate1']
    ni=number(design.GetVariableValue('Ntc'));no=number(design.GetVariableValue('Ntc_out'))
    if number(design.GetVariableValue('kfill'))!=K_FILL:raise ValueError(f'kfill must be {K_FILL}')
    current=min(5.5*K_FILL*ain/(2*ni),5.5*K_FILL*aout/(2*no))
    change(design,{'I_rms':f'{current:.14g}A'})
    removed=clear_auto_mesh(design)
    project.Save()
    if clear_auto_mesh(design):
        removed=True;project.Save()
    if 'CylindricalGap1' in list(design.GetChildObject('Mesh').GetChildNames()):
        raise RuntimeError('CylindricalGap1 reappeared after saving; do not launch solver')
    if not worker['initialized']:
        worker['initialized']=True;atomic_json(Path(run_dir)/'workers.json',pool)
    record=dict(areas_mm2=areas,area_in_mm2=ain,area_out_mm2=aout,i_rms_a=current,
       j_in_a_mm2=2*ni*current/(K_FILL*ain),j_out_a_mm2=2*no*current/(K_FILL*aout),
       kfill=K_FILL,work_model=str(model),geometry_margins=m,removed_auto_mesh=removed,
       applied_variables={str(n):str(design.GetVariableValue(n)) for n in design.GetVariables()})
    return project,design,record


class InvalidOperatingPoint(ValueError):
    """FEA exists, but the present motoring objective definition is not applicable."""


def check_operating_metrics(torque,eta,pf):
    if not all(math.isfinite(v) for v in (torque,eta,pf)):raise InvalidOperatingPoint('Non-finite operating metrics')
    if torque<=0:raise InvalidOperatingPoint(f'Nonpositive mean torque: {torque:.9g} Nm; motoring objectives require torque > 0')
    if not 0<eta<1:raise InvalidOperatingPoint(f'Mean efficiency outside (0,1): {eta:.9g}')
    if not 0<pf<1:raise InvalidOperatingPoint(f'Power factor outside (0,1): {pf:.9g}')


def read_solution(design, record):
    irms = record["i_rms_a"]
    j_in, j_out, jmax = record["j_in_a_mm2"], record["j_out_a_mm2"], 5.5
    expressions = ["Moving1.Torque", "Moving1.Speed", "eff", "PF", "Pin", "Pout",
                   "p_cu", "CoreLoss", "SolidLoss", "U_ter1", "U_ter2", "U_ter3",
                   "InputCurrent(Phase_A)", "InputCurrent(Phase_B)",
                   "InputCurrent(Phase_C)", "Js_in", "Js_out"]
    result = design.GetModule("ReportSetup").GetSolutionDataPerVariation(
        "Transient", "Setup1 : Transient", [], ["Time:=", ["All"]], expressions)
    assert result and len(result) == 1, "Missing or ambiguous solution variation"
    data = result[0]
    times = np.array(data.GetSweepValues("Time", True), dtype=float)
    traces = {n: np.array(data.GetRealDataValues(n, True), dtype=float) for n in expressions}
    if len(times)<3 or not np.all(np.diff(times)>0):raise ValueError('Missing or non-increasing time samples')
    if not all(len(v)==len(times) and np.isfinite(v).all() for v in traces.values()):raise ValueError('Waveform length mismatch or non-finite data')
    freq_text = str(design.GetVariableValue("fs"))
    if not freq_text.endswith('Hz'):raise ValueError(f'Unsupported frequency expression: {freq_text}')
    fs = float(freq_text[:-2])
    stop, start_window = float(times[-1]), float(times[-1] - 1/fs)
    if not (abs(stop-2/fs)<1e-9 and times[0]<=start_window):raise ValueError(f'Incomplete time window: start={times[0]}, stop={stop}, expected stop={2/fs}')
    inner = (times > start_window + 1e-12) & (times < stop - 1e-12)
    window = np.r_[start_window, times[inner], stop]

    def mean(v):
        return float(np.trapezoid(np.interp(window, times, v), window) / (stop-start_window))

    def rms(v):
        return math.sqrt(mean(v*v))

    vrms = [rms(traces[f"U_ter{i}"]) for i in [1, 2, 3]]
    irms_measured = [rms(traces[f"InputCurrent(Phase_{phase})"]) for phase in "ABC"]
    pin = mean(traces["Pin"])
    pf = pin / (3 * vrms[0] * irms_measured[0])
    eta, torque = mean(traces["eff"]), mean(traces["Moving1.Torque"])
    pout, pcu = mean(traces["Pout"]), mean(traces["p_cu"])
    core, solid = mean(traces["CoreLoss"]), mean(traces["SolidLoss"])
    denominator=1.02*pout+pcu+core+solid
    eta_ratio=pout/denominator if abs(denominator)>1e-12 else None
    record['raw_metrics']=dict(average_torque_nm=torque,efficiency_pct=100*eta,power_factor=pf,
        i_rms_measured_a=irms_measured[0],j_in_a_mm2=mean(traces['Js_in']),j_out_a_mm2=mean(traces['Js_out']),pout_w=pout)
    if abs(irms_measured[0]-irms)>=1e-5:raise ValueError(f'RMS current mismatch: measured={irms_measured[0]}, expected={irms}')
    if max(float(traces['Js_in'].max()),float(traces['Js_out'].max()))>jmax+1e-6:raise ValueError('FEA current density exceeds 5.5 A/mm2')
    if abs(mean(traces['Js_in'])-j_in)>=1e-5:raise ValueError(f'Inner J mismatch: FEA={mean(traces["Js_in"])}, expected={j_in}')
    if abs(mean(traces['Js_out'])-j_out)>=1e-5:raise ValueError(f'Outer J mismatch: FEA={mean(traces["Js_out"])}, expected={j_out}')
    try:check_operating_metrics(torque,eta,pf)
    except InvalidOperatingPoint as exc:
        exc.times=times;exc.traces=traces
        raise
    speed = mean(traces["Moving1.Speed"])
    # Moving1.Speed is returned in SI rad/s when the API flag is True.
    if abs(pout-mean(traces['Moving1.Torque']*traces['Moving1.Speed']))>=1e-6:raise ValueError('Pout does not match torque times angular speed in SI')
    record.update(status="ok", average_torque_nm=torque, power_factor=pf,
                  efficiency_pct=100*eta, efficiency_ratio_of_means_pct=100*eta_ratio,
                  pf_report_full_window=mean(traces["PF"]),
                  pf_all_phases=pin/sum(v*i for v, i in zip(vrms, irms_measured)),
                  voltage_phase_rms_v=vrms, current_phase_rms_a=irms_measured,
                  pin_w=pin, pout_w=pout, copper_loss_w=pcu, core_loss_w=core,
                  solid_loss_w=solid, speed_rad_s=speed, speed_rpm=speed*60/(2*math.pi),
                  time_start_s=start_window, time_end_s=stop, frequency_hz=fs,
                  raw_sample_count=len(times), window_sample_count=len(window),
                  native_display_units={n: str(data.GetDataUnits(n)) for n in expressions},
                  waveform_storage="all values converted to SI; custom Pin/Pout/p_cu interpreted as W by their definitions")
    return times, traces
