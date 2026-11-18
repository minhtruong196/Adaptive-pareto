"""Fixed-budget Vernier campaigns following the research TXT stage ordering."""
from pathlib import Path
from collections import Counter
from contextlib import closing
import csv
import hashlib
import json
import sqlite3

import numpy as np
from pymoo.indicators.hv import HV

from vernier_model import BOUNDS,source_variables,digest,atomic_json,model_identity,margins,K_FILL,CONSTRAINTS_VERSION,MESH_POLICY_VERSION
from vernier_optimize import Ledger,run_lock,run as run_fea,export_results
from vernier_mlp import fit_model,predict,metrics,cross_validate
from vernier_protocol import (OBJECTIVES,allocation,point_key,sample_points,search_pareto,
                               choose_checks,corrected_guide,local_boxes)

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'inspection'/'vernier_pilot_20261113'/'work'/'test_point'/'base_half.aedt'


def save_state(path,state):
    state['integrity']=hashlib.sha256(json.dumps({k:v for k,v in state.items() if k!='integrity'},sort_keys=True).encode()).hexdigest()
    atomic_json(path,state)


def verify_state(state):
    actual=hashlib.sha256(json.dumps({k:v for k,v in state.items() if k!='integrity'},sort_keys=True).encode()).hexdigest()
    if state.get('integrity')!=actual:raise ValueError('Frozen points/roles/predictions/state changed; do not resume a modified campaign')


def settings(method='adaptive'):
    if method not in ['adaptive','static']:raise ValueError('Unknown campaign method')
    return dict(method=method,source=SOURCE,run_dir=ROOT/'runs'/f'vernier_{method}_narrow_300_txt_v3',
                evaluations=300,seed=17,bounds=dict(BOUNDS),design='VM_6_28',workers=5,
                worker_pool_dir=ROOT/'runs'/'vernier_narrow_workers_v1',worker_prefix='vernier_narrow',
                timeout_minutes=30,epochs=500,min_checkpoint_epoch=300,cv_folds=5,
                pareto_population=100,pareto_generations=100,local_groups=4,local_padding=.01,
                hv_scale=[10.,1.,100.],dry_run=False,protocol='txt_legacy_sampling_val_70_20_10_v3')


def read_rows(folder,state):
    path=Path(folder)/'evaluations.sqlite'
    if not path.exists():return []
    with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)) as db:
        rows=[]
        for i,raw,status,data in db.execute('SELECT id,point,status,data FROM points ORDER BY id'):
            meta=state['records'][i-1]
            rows.append(dict(json.loads(data or '{}'),point_id=i,point=json.loads(raw),status=status,
                             role=meta['role'],phase=meta['phase']))
        return rows


def solver_calls(folder):
    path=Path(folder)/'evaluations.sqlite'
    if not path.exists():return 0
    with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)) as db:
        return int(db.execute('SELECT COALESCE(SUM(fea_started),0) FROM attempts').fetchone()[0])


def synthetic_values(points,bounds):
    """Explicit synthetic dry-run objectives, never claimed as motor results."""
    names=list(bounds);x=np.array([[(p[k]-bounds[k][0])/(bounds[k][1]-bounds[k][0]) for k in names] for p in points])
    return np.column_stack([2+6*x[:,0],.94-.5*x[:,0],82+10*x[:,1]])


def freeze_step(state,path,name,points,roles,selection=None):
    if name in state['steps']:return state['steps'][name]
    if len(points)!=len(roles):raise ValueError('Point/role mismatch')
    old={point_key(r['point']) for r in state['records']};keys=[point_key(p) for p in points]
    if len(set(keys))!=len(keys) or any(k in old for k in keys):raise ValueError('Duplicate evaluation in frozen plan')
    start=len(state['records'])
    state['records'].extend(dict(point=p,role=role,phase=name) for p,role in zip(points,roles))
    step=dict(start_id=start+1,end_id=len(state['records']))
    if selection is not None:step['selection']=selection
    state['steps'][name]=step;save_state(path,state)
    return step


def evaluate_step(state,path,name,c,fp,spec,evaluate_batch):
    step=state['steps'][name];points=[r['point'] for r in state['records'][:step['end_id']]]
    previous=read_rows(c['run_dir'],state)
    if len(previous)>=len(points) and not any(r['status'] in ['pending','preparing','solving'] for r in previous[:len(points)]):
        return dict(stopped=False)
    if c['dry_run']:
        ledger=Ledger(c['run_dir'],fp,points)
        try:
            pending=ledger.pending()
            if pending:
                ids=[ledger.start(i,0,dict(synthetic=True)) for i in pending]
                batch=[points[i-1] for i in pending]
                values=(evaluate_batch(batch) if evaluate_batch else
                        [dict(status='ok',synthetic=True,**dict(zip(OBJECTIVES,y.tolist()))) for y in synthetic_values(batch,c['bounds'])])
                if len(values)!=len(pending):raise ValueError('Dry-run evaluator size mismatch')
                for i,aid,row in zip(pending,ids,values):ledger.finish(i,row['status'],dict(row,synthetic=True),aid)
            export_results(ledger)
        finally:ledger.close()
        result=dict(stopped=False)
    else:
        cfg=dict(c,samples=len(points),mode='fea',retry_failed=False,max_fea_calls=c['evaluations'],
                 legacy_workers=Path(c['worker_pool_dir'])/'workers.json')
        result=run_fea(cfg,plan_override=dict(fingerprint=fp,settings=spec,points=points))
    if result.get('stopped'):return result
    rows=read_rows(c['run_dir'],state)[step['start_id']-1:step['end_id']]
    step['outcomes']=dict(Counter(r['status'] for r in rows))
    if 'selection' in step:
        actual=[];pred=[]
        for row,selected in zip(rows,step['selection']):
            values=[row.get(k,row.get('raw_metrics',{}).get(k)) for k in OBJECTIVES]
            if all(v is not None and np.isfinite(v) for v in values):
                actual.append(values);pred.append(selected['prediction'])
        step['prediction_metrics']=metrics(np.array(actual).reshape(-1,3),np.array(pred).reshape(-1,3))
        atomic_json(Path(c['run_dir'])/'verification_reports.json',
                    {key:{k:v for k,v in value.items() if k in ['outcomes','prediction_metrics']}
                     for key,value in state['steps'].items() if 'prediction_metrics' in value})
    save_state(path,state)
    print(f"{name}: {len(rows)} fixed slots, outcomes={step['outcomes']}",flush=True)
    return result


def validate_front(model,c,base,candidates):
    if not candidates:raise ValueError('Empty cached predicted Pareto')
    keys=[point_key(r['point']) for r in candidates]
    if len(set(keys))!=len(keys):raise ValueError('Cached predicted Pareto contains duplicate points')
    for r in candidates:
        p=r['point'];y=np.array(r['prediction'],dtype=float)
        if (set(p)!=set(c['bounds']) or not all(np.isfinite(v) for v in p.values()) or
            not all(lo<=p[k]<=hi for k,(lo,hi,_) in c['bounds'].items()) or
            min(margins(p,base).values())<=1e-8 or y.shape!=(3,) or not np.isfinite(y).all() or
            not (y[0]>0 and 0<y[1]<1 and 0<y[2]<100)):
            raise ValueError('Cached predicted Pareto violates constraints')
    predicted=predict(model,[[r['point'][k] for k in c['bounds']] for r in candidates])
    if not np.allclose(predicted,[r['prediction'] for r in candidates],rtol=1e-5,atol=1e-5):
        raise ValueError('Cached Pareto predictions do not match the saved model')
    from vernier_protocol import nondominated
    if len(nondominated(candidates))!=len(candidates):raise ValueError('Cached Pareto includes dominated candidates')


def stage_model(state,path,name,c,base,all_rows):
    train=[r for r in all_rows if r['role']=='train' and r['status']=='ok']
    val=[r for r in all_rows if r['role']=='val' and r['status']=='ok']
    if len(train)<8 or len(val)<2:raise ValueError('Too few valid Train/Val points; stopped without replacement FEA')
    folder=Path(c['run_dir'])/'models'/name
    front_path=folder/'predicted_pareto.json';prior=state['models'].get(name,{})
    for key,file in [('front_sha256',front_path),('checkpoint_sha256',folder/'ann.pt')]:
        if prior.get(key) and (not file.exists() or digest(file)!=prior[key]):
            raise ValueError(f'Frozen {name} {key} changed; stop before more FEA')
    model=fit_model(train,val,c['bounds'],folder,seed=c['seed'],epochs=c['epochs'],
                    min_checkpoint_epoch=c['min_checkpoint_epoch'],merged=False)
    if front_path.exists():candidates=json.loads(front_path.read_text())['candidates']
    else:
        candidates=search_pareto(model,c['bounds'],base,seed=c['seed'],population=c['pareto_population'],
                                 generations=c['pareto_generations'],seen=[r['point'] for r in all_rows])
        atomic_json(front_path,dict(prediction_only=True,candidates=candidates))
    validate_front(model,c,base,candidates)
    values=predict(model,[[r['point'][k] for k in c['bounds']] for r in val])
    report=metrics(np.array([[r[k] for k in OBJECTIVES] for r in val]),values)
    atomic_json(folder/'validation_report.json',dict(stage=name,fit_ids=[r['point_id'] for r in train],
                validation_ids=[r['point_id'] for r in val],metrics=report,
                note='Internal validation selects checkpoint; not an independent random test.'))
    state['models'][name]=dict(fit_n=len(train),val_n=len(val),fit_ids=[r['point_id'] for r in train],
                               validation_ids=[r['point_id'] for r in val],folder=str(folder),
                               front_sha256=digest(front_path),
                               checkpoint_sha256=digest(folder/'ann.pt') if (folder/'ann.pt').exists() else None)
    save_state(path,state)
    print(f'MODEL {name}: Train={len(train)}, Val={len(val)}; full {c["epochs"]} epochs',flush=True)
    return model,candidates


def assigned_roles(train_n,val_n,seed):
    roles=['train']*train_n+['val']*val_n
    return [roles[i] for i in np.random.default_rng(seed).permutation(len(roles))]


def report_campaign(c,state,budget):
    folder=Path(c['run_dir']);rows=read_rows(folder,state)
    pool=[r for r in rows if r['role']!='test'];test=[r for r in rows if r['role']=='test']
    selected=state['steps']['final']['selection'];actual=[];pred=[]
    for r,s in zip(test,selected):
        values=[r.get(k,r.get('raw_metrics',{}).get(k)) for k in OBJECTIVES]
        if all(v is not None and np.isfinite(v) for v in values):actual.append(values);pred.append(s['prediction'])
    scale=np.array(c['hv_scale']);hv=HV(ref_point=np.zeros(3))
    def volume(part):
        values=np.array([[r[k] for k in OBJECTIVES] for r in part if r['status']=='ok'])
        return float(hv(-values/scale)) if len(values) else 0.
    fitted={i for m in state['models'].values() for i in m['fit_ids']}
    fitted.update(state.get('merged_fit_ids',[]));test_ids={r['point_id'] for r in test}
    if fitted&test_ids:raise RuntimeError('Final test leaked into model fitting')
    result=dict(method=c['method'],synthetic=c['dry_run'],evaluation_slots=len(rows),
                actual_solver_calls=solver_calls(folder),budget=budget,
                roles_planned=dict(Counter(r['role'] for r in state['records'])),
                roles_valid=dict(Counter(r['role'] for r in rows if r['status']=='ok')),
                statuses=dict(Counter(r['status'] for r in rows)),pool_valid=sum(r['status']=='ok' for r in pool),
                final_outcomes=dict(planned=budget['test'],statuses=dict(Counter(r['status'] for r in test))),
                final_metrics=metrics(np.array(actual).reshape(-1,3),np.array(pred).reshape(-1,3)),
                hv=dict(scale=dict(zip(OBJECTIVES,c['hv_scale'])),reference=[0,0,0],pool=volume(pool),
                        final_only=volume(test),archive=volume(rows),final_gain=volume(rows)-volume(pool)),
                final_never_trained=True,
                note='SYNTHETIC dry-run; no physical FEA evidence.' if c['dry_run'] else
                     'Final points are optimization-selected verification, not a random global test. No failure refill.')
    if len(rows)>c['evaluations'] or solver_calls(folder)>c['evaluations']:raise RuntimeError('Budget exceeded')
    atomic_json(folder/'campaign_summary.json',result)
    fields=['point_id','phase','role','status',*c['bounds'],*OBJECTIVES,'error']
    with (folder/'campaign_results.csv').open('w',newline='',encoding='utf-8-sig') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
        for r in rows:w.writerow({k:(r['point'].get(k) if k in c['bounds'] else r.get(k)) for k in fields})
    valid=[r for r in rows if r['status']=='ok']
    from vernier_protocol import nondominated
    front=nondominated([dict(point=r['point'],prediction=[r[k] for k in OBJECTIVES],point_id=r['point_id']) for r in valid])
    atomic_json(folder/'fea_pareto.json',dict(synthetic=c['dry_run'],source='actual status-ok evaluations only',pareto=front))
    return result


def main(c=None,evaluate_batch=None):
    c=settings() if c is None else dict(c);folder=Path(c['run_dir']);budget=allocation(c['evaluations'],c['method'])
    if evaluate_batch is not None and not c['dry_run']:raise ValueError('Synthetic callback only allowed in explicit dry-run')
    if c['bounds']!=BOUNDS:raise ValueError('This protocol locks the agreed narrow Vernier13 bounds')
    if not c['source'].is_file():raise FileNotFoundError(c['source'])
    if not c['dry_run'] and (c['epochs']!=500 or c['min_checkpoint_epoch']!=300 or c['cv_folds']!=5):
        raise ValueError('Real campaign locks500 epochs, checkpoint floor300 and5fold CV')
    spec={k:(str(v) if isinstance(v,Path) else v) for k,v in c.items() if k not in ['run_dir']}
    spec.update(source_sha256=digest(c['source']),source_identity=model_identity(c['source']),kfill=K_FILL,
                constraints_version=CONSTRAINTS_VERSION,mesh_policy_version=MESH_POLICY_VERSION,budget=budget,
                code_sha256={p.name:digest(p) for p in Path(__file__).parent.glob('vernier_*.py')})
    # Saved optimized values can change without changing the declared model.
    # Raw hash is provenance; fixed parameters/coupling anchors determine identity.
    identity={k:v for k,v in spec.items() if k!='source_sha256'}
    fp=hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()
    with run_lock(folder,'.campaign.lock'):
        manifest=folder/'campaign.json'
        if manifest.exists() and json.loads(manifest.read_text())['fingerprint']!=fp:
            raise ValueError('Campaign settings/source/code changed; restore or use a new run folder')
        atomic_json(manifest,dict(fingerprint=fp,settings=spec))
        path=folder/'state.json';state=json.loads(path.read_text()) if path.exists() else dict(records=[],steps={},models={})
        if path.exists():verify_state(state)
        if state.get('completed'):
            return json.loads((folder/'campaign_summary.json').read_text())
        base=source_variables(c['source']);candidates=None;model=None
        for index,stage in enumerate(budget['stages']):
            name=stage['name']
            doe=name+'_doe'
            if doe not in state['steps']:
                boxes=None if stage['kind']=='initial' else local_boxes(guide,c['bounds'],stage['kind'],c['local_groups'],c['local_padding'])
                points=sample_points(stage['doe_train']+stage['val'],c['bounds'],base,c['seed']+index*100,
                                     [r['point'] for r in state['records']],boxes)
                roles=assigned_roles(stage['doe_train'],stage['val'],c['seed']+index*100+1)
                freeze_step(state,path,doe,points,roles)
                if boxes is not None:
                    state['steps'][doe]['boxes']=[(lo.tolist(),hi.tolist()) for lo,hi in boxes];save_state(path,state)
            result=evaluate_step(state,path,doe,c,fp,spec,evaluate_batch)
            if result.get('stopped'):return result
            # On resume, historical models use only their original prefix, not later Val/Train.
            end=state['steps'][doe]['end_id'];rows=read_rows(folder,state)[:end]
            model,candidates=stage_model(state,path,name,c,base,rows)
            # TXT sections3/6: DOE -> FEA -> fit -> predicted Pareto -> verify5.
            # Verification corrects guidance, but enters fitting only next stage.
            if stage['verify']:
                check=name+'_verify'
                if check not in state['steps']:
                    chosen=choose_checks(candidates,[r['point'] for r in state['records']],stage['verify'])
                    freeze_step(state,path,check,[r['point'] for r in chosen],['train']*len(chosen),chosen)
                result=evaluate_step(state,path,check,c,fp,spec,evaluate_batch)
                if result.get('stopped'):return result
                rows=read_rows(folder,state)[:state['steps'][check]['end_id']]
            guide=corrected_guide(candidates,rows)
        pool=read_rows(folder,state)[:budget['pool']]
        valid=[r for r in pool if r['status']=='ok']
        last=budget['stages'][-1]['name']
        # Preserve stage validation before any merge; later writes never overwrite it.
        val=[r for r in pool if r['role']=='val' and r['status']=='ok']
        premerge=metrics(np.array([[r[k] for k in OBJECTIVES] for r in val]),
                         predict(model,[[r['point'][k] for k in c['bounds']] for r in val]))
        atomic_json(folder/'validation_before_merge.json',dict(stage=last,validation_ids=[r['point_id'] for r in val],metrics=premerge))
        cv=cross_validate(valid,c['bounds'],folder/'cv5',seed=c['seed'],folds=c['cv_folds'],epochs=c['epochs'])
        atomic_json(folder/'cv_report.json',cv)
        merged=fit_model(valid,[],c['bounds'],folder/'models'/'merged',seed=c['seed'],epochs=c['epochs'],
                         min_checkpoint_epoch=c['min_checkpoint_epoch'],merged=True)
        state['merged_fit_ids']=[r['point_id'] for r in valid];save_state(path,state)
        print(f'FINAL MERGE: {len(valid)} valid Train+Val; epoch{c["epochs"]}',flush=True)
        if 'final' not in state['steps']:
            front=search_pareto(merged,c['bounds'],base,seed=c['seed'],population=c['pareto_population'],
                                 generations=c['pareto_generations'],seen=[r['point'] for r in state['records']])
            chosen=choose_checks(front,[r['point'] for r in state['records']],budget['test'])
            freeze_step(state,path,'final',[r['point'] for r in chosen],['test']*len(chosen),chosen)
        result=evaluate_step(state,path,'final',c,fp,spec,evaluate_batch)
        if result.get('stopped'):return result
        result=report_campaign(c,state,budget);state['completed']=True;save_state(path,state)
        print(f'COMPLETE: {len(state["records"])} evaluation slots; actual solver calls={result["actual_solver_calls"]}',flush=True)
        return result


def cli(method,defaults):
    import argparse
    parser=argparse.ArgumentParser(description='Vernier fixed-budget70/20/10; no failure refill')
    parser.add_argument('--evaluations',type=int,default=defaults['evaluations'])
    parser.add_argument('--dry-run',action='store_true',help='Synthetic only; never calls Ansys')
    args=parser.parse_args();c=dict(defaults,evaluations=args.evaluations,dry_run=args.dry_run)
    if args.dry_run or args.evaluations!=300:
        c['run_dir']=Path(str(defaults['run_dir'])+f'_n{args.evaluations}'+('_dry_run' if args.dry_run else ''))
    result=main(c)
    print(json.dumps({k:result.get(k) for k in ['method','synthetic','evaluation_slots','actual_solver_calls','final_outcomes']},indent=2))
    return result
