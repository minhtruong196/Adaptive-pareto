"""Append-only real-FEA adapter; contains no optimization algorithm.

COM is imported only inside run(). Importing this module never opens Ansys.
"""
import csv
import hashlib
import json
import sqlite3
import time
import traceback
from contextlib import contextmanager
from datetime import datetime,timezone
from pathlib import Path

from vernier_model import (digest,source_variables,worker_pool,make_plan,atomic_json,
                           prepare,read_solution,K_FILL,CONSTRAINTS_VERSION,MESH_POLICY_VERSION,
                           InvalidOperatingPoint,model_identity)


def utc():return datetime.now(timezone.utc).isoformat()


def new_messages(messages,previous):
    from collections import Counter
    old=Counter(previous);fresh=[]
    for message in messages:
        if old[message]:old[message]-=1
        else:fresh.append(message)
    return fresh


class Ledger:
    def __init__(self,folder,fingerprint,points):
        folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
        self.folder=folder;self.db=sqlite3.connect(folder/'evaluations.sqlite')
        self.db.executescript('''
          CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY,value TEXT);
          CREATE TABLE IF NOT EXISTS points (id INTEGER PRIMARY KEY,point TEXT,status TEXT,data TEXT);
          CREATE TABLE IF NOT EXISTS attempts (id INTEGER PRIMARY KEY,point_id INTEGER,worker INTEGER,
            status TEXT,fea_started INTEGER DEFAULT 0,started TEXT,finished TEXT,data TEXT);
          CREATE TABLE IF NOT EXISTS waveforms (attempt_id INTEGER,sample INTEGER,time_s REAL,data TEXT,
            PRIMARY KEY(attempt_id,sample));''')
        try:
            old=self.db.execute("SELECT value FROM meta WHERE key='fingerprint'").fetchone()
            if old and old[0]!=fingerprint:
                raise ValueError('Run fingerprint changed: restore settings or select another RUN_DIR')
            encoded_points=[json.dumps(p,sort_keys=True,allow_nan=False) for p in points]
            if len(set(encoded_points))!=len(encoded_points):raise ValueError('Saved DOE plan contains duplicate points')
            existing=self.db.execute('SELECT id,point FROM points ORDER BY id').fetchall()
            if len(existing)>len(points) or any(i!=idx or raw!=encoded_points[idx-1] for idx,(i,raw) in enumerate(existing,1)):
                raise ValueError('Saved DOE plan changed; only appending new points is allowed')
            self.db.execute("INSERT OR IGNORE INTO meta VALUES ('fingerprint',?)",(fingerprint,))
            for i,encoded in enumerate(encoded_points,1):
                self.db.execute('INSERT OR IGNORE INTO points VALUES (?,?,?,?)',(i,encoded,'pending','{}'))
            self._interrupt_open_attempts()
            self.db.commit()
        except BaseException:
            self.db.rollback();self.db.close();raise

    def _interrupt_open_attempts(self):
        self.db.execute("UPDATE points SET status='interrupted',data=(SELECT data FROM attempts WHERE point_id=points.id ORDER BY id DESC LIMIT 1) WHERE status IN ('preparing','solving')")
        self.db.execute("UPDATE attempts SET status='interrupted',finished=? WHERE status IN ('preparing','solving')",(utc(),))

    def pending(self,retry_failed=False,fea=True):
        # Compatibility arguments never authorize terminal-slot retries/refill.
        return [row[0] for row in self.db.execute("SELECT id FROM points WHERE status='pending' ORDER BY id")]

    def start(self,point,worker,data):
        with self.db:
            changed=self.db.execute("UPDATE points SET status='preparing' WHERE id=? AND status='pending'",(point,))
            if changed.rowcount!=1:raise ValueError('Point is absent or already attempted; terminal slots cannot be retried')
            cur=self.db.execute('INSERT INTO attempts (point_id,worker,status,started,data) VALUES (?,?,?,?,?)',
                                (point,worker,'preparing',utc(),json.dumps(data,allow_nan=False)))
            return cur.lastrowid

    def mark_solving(self,attempt,max_calls=None):
        with self.db:
            # Acquire the write lock before reading the cumulative solver budget.
            self.db.execute('UPDATE meta SET value=value WHERE key=\'fingerprint\'')
            state=self.db.execute('SELECT status,fea_started FROM attempts WHERE id=?',(attempt,)).fetchone()
            if state!=('preparing',0):raise ValueError('Attempt is absent or has already started')
            if max_calls is not None and self.solver_calls()>=max_calls:raise RuntimeError('Solver-call budget exhausted')
            self.db.execute("UPDATE attempts SET status='solving',fea_started=1 WHERE id=?",(attempt,))
            self.db.execute("UPDATE points SET status='solving' WHERE id=(SELECT point_id FROM attempts WHERE id=?)",(attempt,))

    def finish(self,point,status,data,attempt=None):
        encoded=json.dumps(data,allow_nan=False)
        self.db.execute('UPDATE points SET status=?,data=? WHERE id=?',(status,encoded,point))
        if attempt is not None:self.db.execute('UPDATE attempts SET status=?,finished=?,data=? WHERE id=?',(status,utc(),encoded,attempt))
        self.db.commit()

    def solver_calls(self):return self.db.execute('SELECT COALESCE(SUM(fea_started),0) FROM attempts').fetchone()[0]
    def close(self):
        self._interrupt_open_attempts();self.db.commit();self.db.close()


@contextmanager
def run_lock(folder,name='.runner.lock'):
    import os
    path=Path(folder)/name;path.parent.mkdir(parents=True,exist_ok=True)
    f=path.open('a+b')
    try:
        if path.stat().st_size==0:f.write(b'0');f.flush()
        f.seek(0)
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(f.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:raise RuntimeError('This DOE is already running; do not start a second VS Code run')
        yield
    finally:f.close()


def export_results(ledger):
    """One common Excel workbook plus a small common CSV; never per-point Excel."""
    from openpyxl import Workbook
    from openpyxl.styles import Font,PatternFill,Alignment
    rows=[]
    for i,raw,status,data in ledger.db.execute('SELECT * FROM points ORDER BY id'):
        r=json.loads(data);point=json.loads(raw)
        rows.append(dict(point_id=i,status=status,**point,**{k:r.get(k) for k in [
          'average_torque_nm','power_factor','efficiency_pct','i_rms_a','j_in_a_mm2',
          'j_out_a_mm2','solve_elapsed_s','area_in_mm2','area_out_mm2','error']}))
    keys=list(rows[0]) if rows else ['point_id','status']
    temp=ledger.folder/'results.csv.tmp'
    with temp.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,keys);w.writeheader();w.writerows(rows)
    temp.replace(ledger.folder/'results.csv')
    wb=Workbook();ws=wb.active;ws.title='Results';ws.append(keys)
    for row in rows:ws.append([row[k] for k in keys])
    wave=wb.create_sheet('Waveforms')
    columns=['Moving1.Torque','eff','PF','Pin','Pout','p_cu','CoreLoss','SolidLoss',
             'U_ter1','U_ter2','U_ter3','InputCurrent(Phase_A)','InputCurrent(Phase_B)',
             'InputCurrent(Phase_C)','Js_in','Js_out','Moving1.Speed']
    wave.append(['point_id','attempt_id','time_s','torque_Nm','eff_fraction','PF_full_window',
       'Pin_W','Pout_W','copper_W','core_W','solid_W','Ua_V','Ub_V','Uc_V','Ia_A','Ib_A','Ic_A',
       'Jin_A_mm2','Jout_A_mm2','speed_rad_s'])
    for point,attempt,t,data in ledger.db.execute('SELECT a.point_id,w.attempt_id,w.time_s,w.data FROM waveforms w JOIN attempts a ON a.id=w.attempt_id ORDER BY a.point_id,w.attempt_id,w.sample'):
        r=json.loads(data);wave.append([point,attempt,t]+[r[n] for n in columns])
    for sheet in wb:
        sheet.freeze_panes='C2';sheet.auto_filter.ref=sheet.dimensions
        for c in sheet[1]:c.font=Font(bold=True,color='FFFFFF');c.fill=PatternFill('solid',fgColor='26384A');c.alignment=Alignment(wrap_text=True)
        sheet.row_dimensions[1].height=34
        for col in sheet.columns:sheet.column_dimensions[col[0].column_letter].width=min(34,max(14,len(str(col[0].value))+2))
        for row in sheet.iter_rows(min_row=2):
            for c in row:
                if isinstance(c.value,float):c.number_format='0.000000'
    tmp=ledger.folder/'results.tmp.xlsx';wb.save(tmp);tmp.replace(ledger.folder/'results.xlsx')
    counts=dict(ledger.db.execute('SELECT status,count(*) FROM points GROUP BY status'))
    atomic_json(ledger.folder/'summary.json',dict(points=len(rows),solver_calls=ledger.solver_calls(),statuses=counts,
      efficiency='time mean of eff(t), including 2% excess loss; final electrical cycle',voltage_constraint=False))


def run(settings,plan_override=None):
    import openpyxl  # Fail before touching Ansys if the export dependency is missing.
    source=Path(settings['source']).resolve();folder=Path(settings['run_dir']).resolve()
    workers=int(settings['workers']);fea=settings['mode']=='fea'
    if settings['mode'] not in ('fea','geometry') or not 1<=workers<=5:raise ValueError('Use mode fea/geometry and 1..5 workers')
    sha=digest(source);base=source_variables(source)
    identity=model_identity(source)
    spec=dict(model_identity=identity,n=settings['samples'],seed=settings['seed'],bounds=settings['bounds'],metrics_version=1,kfill=K_FILL,constraints_version=CONSTRAINTS_VERSION,mesh_policy_version=MESH_POLICY_VERSION)
    fp=plan_override['fingerprint'] if plan_override else hashlib.sha256(json.dumps(spec,sort_keys=True).encode()).hexdigest()
    pool_folder=Path(settings.get('worker_pool_dir',folder)).resolve()
    with run_lock(folder),run_lock(pool_folder,'.worker_pool.lock'):
        plan_path=folder/'plan.json'
        if plan_override is not None:
            plan=plan_override
            if plan_path.exists():
                old=json.loads(plan_path.read_text(encoding='utf-8'))
                # Raw bytes are provenance; configuration identity governs compatibility.
                compatible_old={k:v for k,v in old['settings'].items() if k!='source_sha256'}
                # Compare JSON representations: tuple bounds reload as lists.
                compatible_new=json.loads(json.dumps({k:v for k,v in plan['settings'].items() if k!='source_sha256'},allow_nan=False))
                if old['fingerprint']!=fp or compatible_old!=compatible_new or old['points']!=plan['points'][:len(old['points'])]:
                    raise ValueError('Evaluation archive changed; only appending points is allowed')
            atomic_json(plan_path,plan)
        elif plan_path.exists():
            plan=json.loads(plan_path.read_text(encoding='utf-8'))
            if plan['fingerprint']!=fp:raise ValueError('Plan fingerprint changed; restore settings or change RUN_DIR')
        else:
            plan=dict(fingerprint=fp,settings=spec,points=make_plan(settings['samples'],settings['seed'],settings['bounds'],base),
                      sampling='feasibility-filtered LHS; filtering changes strict marginal stratification')
            atomic_json(plan_path,plan)
        ledger=Ledger(folder,fp,plan['points']);opened={};active={};stop=False;stop_reason=None
        todo=ledger.pending(settings.get('retry_failed',False),fea)
        # Repeated completed calls and exhausted budgets must not touch COM.
        if not todo or (fea and ledger.solver_calls()>=settings.get('max_fea_calls',float('inf'))):
            budget=bool(todo)
            try:export_results(ledger)
            finally:ledger.close()
            return dict(stopped=budget,reason='budget' if budget else None)
        try:
            import win32com.client
            app=win32com.client.Dispatch('Ansoft.ElectronicsDesktop.2024.1');desk=app.GetAppDesktop()
            if desk.AreThereSimulationsRunning():raise RuntimeError('Ansys is already solving. Wait for it to finish before resuming this DOE.')
            pool=worker_pool(pool_folder,source,sha,settings.get('legacy_workers'),
                             prefix=settings.get('worker_prefix','worker'))
            if pool['model_identity']!=identity:raise ValueError('Worker configuration differs from saved source')
        except BaseException:
            ledger.close();raise
        print(f'DOE: {len(todo)} pending / {len(plan["points"])} planned; {workers} workers; mode={settings["mode"]}',flush=True)
        print(f'Output: {folder}\nCtrl+C: stop submitting new points and finish current solves.',flush=True)
        def export():
            try:export_results(ledger)
            except PermissionError:print('Close results.xlsx in Excel to allow the next export; data remains safe in SQLite.',flush=True)
        try:
            while todo or active:
                try:
                    for worker in pool['workers'][:workers]:
                        wid=worker['worker']
                        if stop or not todo or wid in active:continue
                        if fea and ledger.solver_calls()>=settings.get('max_fea_calls',float('inf')):
                            stop=True;stop_reason='budget';break
                        point=todo.pop(0);requested=plan['points'][point-1]
                        r=dict(point_id=point,worker=wid,requested_variables=requested,source_sha256=sha)
                        aid=ledger.start(point,wid,r)
                        try:
                            project,design,extra=prepare(desk,worker,pool,pool_folder,requested,settings['design'])
                            opened[project.GetName()]=project;r.update(extra)
                            if not fea:
                                ledger.finish(point,'geometry_ok',r,aid);export();print(f'GEOMETRY {point}: ok',flush=True);continue
                            offset=list(desk.GetMessages(project.GetName(),settings['design'],0))
                            started=time.monotonic();ledger.mark_solving(aid,max_calls=settings.get('max_fea_calls'))
                            # Register before the external call, so interruption cannot lose ownership.
                            active[wid]=(point,aid,project,design,r,offset,started)
                            design.Analyze('Setup1',False)
                            print(f'START point {point}/{len(plan["points"])} worker {wid}; Irms={r["i_rms_a"]:.5f} A',flush=True)
                        except KeyboardInterrupt:raise
                        except Exception as exc:
                            if wid in active:
                                # A failed RPC does not prove the remote solve stopped.
                                # Keep ownership until Ansys reports completion/error.
                                r['launch_error']=f'{type(exc).__name__}: {exc}'
                                print(f'Launch RPC warning for {point}; checking remote solver status.',flush=True)
                                continue
                            status='preparation_failed'
                            r['error']=f'{type(exc).__name__}: {exc}'
                            r['error_traceback']=traceback.format_exc()
                            print(r['error_traceback'],flush=True)
                            ledger.finish(point,status,r,aid);export();print(f'FAILED {point}: {r["error"]}',flush=True)
                    for wid,(point,aid,project,design,r,offset,started) in list(active.items()):
                        messages=new_messages(list(desk.GetMessages(project.GetName(),settings['design'],0)),offset)
                        errors=[m for m in messages if '[error]' in m.lower()]
                        complete=any('Normal completion of simulation' in m for m in messages)
                        if not errors and not complete:
                            if time.monotonic()-started>settings['timeout_minutes']*60:
                                raise TimeoutError('Solver timeout. Worker projects are left open; inspect Ansys before rerunning.')
                            continue
                        r.update(solve_elapsed_s=time.monotonic()-started,ansys_messages=messages)
                        status='ok'
                        if errors:status='solve_failed';r['error']='; '.join(errors)
                        else:
                            try:
                                # Persist the successful solver state even if subsequent parsing rejects it.
                                project.Save()
                                try:times,traces=read_solution(design,r)
                                except InvalidOperatingPoint as exc:
                                    status='operating_point_infeasible';r['error']=str(exc)
                                    times,traces=exc.times,exc.traces
                                for i,t in enumerate(times):
                                    ledger.db.execute('INSERT INTO waveforms VALUES (?,?,?,?)',(aid,i,float(t),json.dumps({n:float(v[i]) for n,v in traces.items()})))
                            except Exception as exc:
                                status='postprocess_failed';r['error']=f'{type(exc).__name__}: {exc}'
                                r['error_traceback']=traceback.format_exc();print(r['error_traceback'],flush=True)
                        ledger.finish(point,status,r,aid);active.pop(wid);export()
                        print(f'DONE {point}: {status}; T={r.get("average_torque_nm")} PF={r.get("power_factor")} eff={r.get("efficiency_pct")}',flush=True)
                    if stop and not active:break
                    if active:time.sleep(2)
                except KeyboardInterrupt:
                    if stop:raise
                    stop=True;stop_reason='user';print('Stopping new submissions; waiting for active solvers. Press Ctrl+C again only to detach.',flush=True)
            export()
            print('STOPPED' if stop else 'FINISHED',dict(ledger.db.execute('SELECT status,count(*) FROM points GROUP BY status')),flush=True)
        finally:
            try:
                # Terminalize every consumed slot even if Ctrl+C occurs during CAD/RPC.
                # Active remote solves remain owned/open; never automatically retry them.
                for wid,(point,aid,project,design,r,offset,started) in active.items():
                    r['error']='Controller detached from active solve; inspect Ansys before any new run'
                    ledger.finish(point,'interrupted',r,aid)
                ledger._interrupt_open_attempts();ledger.db.commit()
                export()
                # Never close or alter a project with an active simulation.
                if not active:
                    for name in opened:desk.CloseProject(name)
            finally:
                ledger.close()
                if digest(source)!=sha:raise RuntimeError('Source model changed during this run')
        return dict(stopped=stop,reason=stop_reason)


OBJECTIVES=('average_torque_nm','power_factor','efficiency_pct')


def pareto_rows(rows):
    valid=[r for r in rows if r.get('status')=='ok' and all(k in r and r[k] is not None for k in OBJECTIVES)]
    return [r for r in valid if not any(all(o[k]>=r[k] for k in OBJECTIVES) and
                any(o[k]>r[k] for k in OBJECTIVES) for o in valid)]


def export_pareto(folder):
    db=sqlite3.connect(Path(folder)/'evaluations.sqlite')
    rows=[]
    for i,point,status,data in db.execute('SELECT * FROM points ORDER BY id'):
        rows.append(dict(json.loads(data),point_id=i,status=status,**json.loads(point)))
    calls=db.execute('SELECT COALESCE(SUM(fea_started),0) FROM attempts').fetchone()[0];db.close()
    front=pareto_rows(rows)
    from vernier_model import BOUNDS
    fields=['point_id',*OBJECTIVES,*BOUNDS]
    tmp=Path(folder)/'pareto.csv.tmp'
    with tmp.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fields,extrasaction='ignore');w.writeheader();w.writerows(front)
    tmp.replace(Path(folder)/'pareto.csv')
    atomic_json(Path(folder)/'pareto.json',dict(source='actual valid FEA only',
      solver_calls=calls,valid_designs=sum(r.get('status')=='ok' for r in rows),pareto=front))
