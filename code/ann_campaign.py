"""V1 ANN experiments. Real FEA only; Direct800 is comparison-only."""
import argparse
import copy
import csv
import json
import sys
import time
from contextlib import ExitStack
from pathlib import Path

import numpy as np
from scipy.stats import qmc
import motorcad_optimize as opt

ORDERS = {'sequential': ['G','G','L','L'], 'alternating': ['G','L','G','L']}


def read_settings(path='ann_pool100_ver20_config.json'):
    return json.loads((opt.CONFIG_DIR/path).read_text())


def validate_settings(c):
    n=c['initial_n'];budget=c['budget']
    if c.get('budget_semantics')=='ann_pool_plus_final_verification':
        allocations={100:(40,[12,11,11,11],[52,68,84,100]),
                     60:(20,[7,6,6,6],[27,38,49,60])}
        if c['pool_n'] not in allocations:raise ValueError('Only pool60/100 + final20 approved')
        initial,counts,targets=allocations[c['pool_n']]
        if (n,c['final_verify_n'],budget)!=(initial,20,c['pool_n']+20):
            raise ValueError('Modeling pool and final verification allocation mismatch')
        if (c['conventional_doe_n']!=c['pool_n'] or c['verify_n']!=5 or
            c['stage_doe_counts']!=counts or c['stage_pool_targets']!=targets):
            raise ValueError('Adaptive final pool must equal Conventional, including previous verification')
        if not 0<c['validation_n']<=n-8:raise ValueError('Insufficient fitting data')
        return n,budget-n
    raise ValueError('Use modeling-pool + separate final verification configuration')


def key(x): return ','.join(map(str, map(int,x)))
def indices(row): return tuple(map(int,row['design_key'].split(',')))
def outputs(rows):
    y=np.array([[float(r[k]) for k in opt.OBJECTIVES] for r in rows])
    if not np.isfinite(y).all():raise RuntimeError('Nonfinite objective data')
    return y


def sample_box(n, lo, hi, excluded, seed):
    lo=np.ceil(lo).astype(int);hi=np.floor(hi).astype(int)
    if np.any(lo>hi): raise ValueError('Empty sampling box')
    rng=qmc.LatinHypercube(7,seed=seed)
    found={}
    for _ in range(500):
        batch=lo+np.floor(rng.random(max(32,n*2))*(hi-lo+1)).astype(int)
        for x in batch:
            t=tuple(map(int,x))
            if t not in excluded: found.setdefault(t,None)
            if len(found)==n:return list(found)
    raise RuntimeError('Collapsed sampling domain cannot provide requested unique DoE')


def select_verify(y,n):
    selected=list(dict.fromkeys(int(i) for i in np.argmax(y,axis=0)))[:n]
    z=(y-y.min(0))/np.maximum(np.ptp(y,axis=0),1e-12)
    while len(selected)<min(n,len(y)):
        d=((z[:,None,:]-z[selected][None,:,:])**2).sum(2).min(1)
        d[selected]=-1
        selected.append(int(np.argmax(d)))
    return selected


def make_net(hidden):
    import torch
    layers=[];n=7
    for width in hidden:
        layers.extend([torch.nn.Linear(n,width),torch.nn.Tanh()]);n=width
    return torch.nn.Sequential(*layers,torch.nn.Linear(n,3))


def errors(actual,predicted):
    actual=np.asarray(actual);predicted=np.asarray(predicted)
    if not len(actual):return {}
    result={}
    for j,name in enumerate(opt.OBJECTIVES):
        diff=predicted[:,j]-actual[:,j];den=((actual[:,j]-actual[:,j].mean())**2).sum()
        result[name]=dict(mae=float(abs(diff).mean()),rmse=float(np.sqrt((diff**2).mean())),
                          r2=float(1-(diff**2).sum()/den) if den>1e-15 else None,
                          n=len(actual),max_absolute_error=float(abs(diff).max()),
                          max_relative_error_pct=float((abs(diff)/np.maximum(abs(actual[:,j]),1e-9)).max()*100),
                          mean_relative_error_pct=float((abs(diff)/np.maximum(abs(actual[:,j]),1e-9)).mean()*100))
    return result


def predict(model,x):
    import torch
    with torch.no_grad():
        z=torch.tensor(np.asarray(x)/np.array(opt.LIMITS),dtype=torch.float32)
        y=model['net'](z).numpy()*model['scale']+model['mean']
    if not np.isfinite(y).all():raise RuntimeError('Nonfinite ANN predictions')
    return y


def fit_ann(rows,held,c):
    import torch
    torch.set_num_threads(1);torch.manual_seed(c['seed'])
    fit=[r for r in rows if r['design_key'] not in held]
    val=[r for r in rows if r['design_key'] in held]
    if len(fit)<8 or not val: raise RuntimeError('Insufficient valid fitting/validation data')
    y=outputs(fit);mean=y.mean(0);scale=np.maximum(y.std(0),1e-8)
    x=torch.tensor(np.array([indices(r) for r in fit])/np.array(opt.LIMITS),dtype=torch.float32)
    yt=torch.tensor((y-mean)/scale,dtype=torch.float32)
    vx=torch.tensor(np.array([indices(r) for r in val])/np.array(opt.LIMITS),dtype=torch.float32)
    vy=torch.tensor((outputs(val)-mean)/scale,dtype=torch.float32)
    net=make_net(c['hidden']);optim=torch.optim.Adam(net.parameters(),lr=c['learning_rate'])
    best=None;best_loss=float('inf');curve=[];started=time.monotonic()
    for epoch in range(c['epochs']):
        optim.zero_grad();loss=((net(x)-yt)**2).mean();loss.backward();optim.step()
        with torch.no_grad():vl=float(((net(vx)-vy)**2).mean())
        if not np.isfinite(vl):raise RuntimeError('Nonfinite training loss')
        curve.append(dict(epoch=epoch+1,fit_loss=float(loss.detach()),validation_loss=vl))
        if vl<best_loss:best_loss=vl;best=copy.deepcopy(net.state_dict());best_epoch=epoch+1
    net.load_state_dict(best);net.eval()
    model=dict(net=net,mean=mean,scale=scale)
    record=dict(fit_n=len(fit),validation_n=len(val),fit_keys=[r['design_key'] for r in fit],
                validation_keys=[r['design_key'] for r in val],best_epoch=best_epoch,
                train_calls=1,training_seconds=time.monotonic()-started,curve=curve,
                validation_metrics=errors(outputs(val),predict(model,[indices(r) for r in val])),
                note='Validation used for epoch selection; not independent test. Scaling fitted only on fitting rows.')
    return model,record


def predicted_pareto(model,c):
    from pymoo.core.problem import Problem
    from pymoo.algorithms.moo.nsga2 import NSGA2
    from pymoo.operators.sampling.rnd import IntegerRandomSampling
    from pymoo.operators.crossover.sbx import SBX
    from pymoo.operators.mutation.pm import PM
    from pymoo.operators.repair.rounding import RoundingRepair
    from pymoo.optimize import minimize
    class Surrogate(Problem):
        def __init__(self):super().__init__(n_var=7,n_obj=3,xl=np.zeros(7),xu=np.array(opt.LIMITS),vtype=int)
        def _evaluate(self,x,out,*args,**kwargs):out['F']=-predict(model,np.rint(x).astype(int))
    algorithm=NSGA2(pop_size=c['pareto_population'],sampling=IntegerRandomSampling(),
        crossover=SBX(prob=.9,eta=15,vtype=float,repair=RoundingRepair()),
        mutation=PM(eta=20,vtype=float,repair=RoundingRepair()),eliminate_duplicates=True)
    result=minimize(Surrogate(),algorithm,('n_gen',c['pareto_generations']),seed=c['seed'],verbose=False)
    x=np.atleast_2d(result.X).astype(int);y=predict(model,x)
    return [dict(design_key=key(xx),**dict(zip(opt.NAMES,opt.decode(xx))),
                 **dict(zip(opt.OBJECTIVES,map(float,yy))),prediction_only=True) for xx,yy in zip(x,y)]


def infill(n,guide,seen,kind,c,seed):
    x=np.array([indices(r) for r in guide]);limits=np.array(opt.LIMITS)
    if not len(x):raise RuntimeError('Empty guidance Pareto')
    if kind=='G':return sample_box(n,x.min(0),x.max(0),seen,seed)
    y=outputs(guide);z=(y-y.min(0))/np.maximum(np.ptp(y,axis=0),1e-12)
    centers=select_verify(y,min(c['group_count'],len(y)))
    assignment=((z[:,None,:]-z[centers][None,:,:])**2).sum(2).argmin(1)
    groups=[x[assignment==j] for j in range(len(centers)) if (assignment==j).any()]
    picked=[]
    for j in range(n):
        group=groups[j%len(groups)];padding=c['local_padding']*limits
        point=sample_box(1,np.maximum(0,group.min(0)-padding),np.minimum(limits,group.max(0)+padding),
                         seen|set(picked),seed+j)[0]
        picked.append(point)
    return picked


def strict_results(rows):
    if any(not opt.feasible(r) for r in rows):
        raise RuntimeError('Invalid real FEA output; inspect evaluations.csv before continuation')


def evaluate_plan(store,evaluator,path,designs,source):
    if path.exists():designs=json.loads(path.read_text())['designs']
    else:opt.atomic_json(path,dict(designs=designs,source=source))
    result=evaluator.evaluate_many(designs,source)
    strict_results(result)
    return result


def stage(store,evaluator,folder,name,c,held,doe_n=0,kind=None,guide=None,target_pool_n=None):
    import torch
    folder=folder/name;folder.mkdir(exist_ok=True)
    marker=folder/'complete.json'
    if marker.exists():return json.loads(marker.read_text())['guide']
    started=time.monotonic()
    if doe_n:
        plan=folder/'doe_plan.json'
        if plan.exists():designs=json.loads(plan.read_text())['designs']
        else:
            if target_pool_n is not None:
                doe_n=target_pool_n-len([r for r in store.rows() if r['source']!=name+'_verify'])
                if doe_n<0:raise RuntimeError('Training pool already exceeds approved target')
            seen={indices(r) for r in store.rows()}
            designs=[] if doe_n==0 else (infill(doe_n,guide,seen,kind,c,c['seed']+sum(map(ord,name))) if kind else
                     sample_box(doe_n,np.zeros(7),np.array(opt.LIMITS),seen,c['seed']+101))
        evaluate_plan(store,evaluator,plan,designs,name+'_doe')
    # Current-stage verification must never be included in its ANN fit, even on replay.
    training=[r for r in store.rows() if r['source']!=name+'_verify']
    strict_results(training)
    if target_pool_n is not None and len(training)!=target_pool_n:
        raise RuntimeError('Training pool target not met')
    annfile=folder/'ann.pt';metricsfile=folder/'training.json'
    if annfile.exists() and metricsfile.exists():
        saved=torch.load(annfile,weights_only=False);net=make_net(c['hidden']);net.load_state_dict(saved['state']);net.eval()
        model=dict(net=net,mean=saved['mean'],scale=saved['scale'])
        record=json.loads(metricsfile.read_text())
        if set(record['fit_keys']) & held:raise RuntimeError('Validation leakage')
    else:
        model,record=fit_ann(training,held,c)
        temp=annfile.with_suffix('.tmp');torch.save(dict(state=model['net'].state_dict(),mean=model['mean'],scale=model['scale']),temp);temp.replace(annfile)
        opt.atomic_json(metricsfile,record)
    paretopath=folder/'predicted_pareto.json'
    if paretopath.exists():pred=json.loads(paretopath.read_text())
    else:
        t=time.monotonic();pred=predicted_pareto(model,c)
        opt.atomic_json(paretopath,pred)
        opt.atomic_json(folder/'optimization.json',dict(seconds=time.monotonic()-t))
    opt.write_csv(folder/'predicted_pareto.csv',pred)
    if name=='initial':
        opt.atomic_json(marker,dict(guide=pred,stage=name,training_pool_n=len(training),verification_n=0,seconds=time.monotonic()-started))
        return pred
    final_stage=name=='final' or name.startswith('04_')
    eligible=list(range(len(pred)))
    if final_stage and c.get('final_verify_unseen_only'):
        seen_training={r['design_key'] for r in training}
        eligible=[i for i,r in enumerate(pred) if r['design_key'] not in seen_training]
    if not eligible:raise RuntimeError('No unseen predicted Pareto designs available for verification')
    verify_n=c.get('final_verify_n',c['verify_n']) if final_stage else c['verify_n']
    chosen=[eligible[i] for i in select_verify(outputs([pred[j] for j in eligible]),verify_n)]
    chosenrows=[pred[i] for i in chosen]
    verified=evaluate_plan(store,evaluator,folder/'verification_plan.json',[indices(r) for r in chosenrows],name+'_verify')
    pairs=[]
    corrected=copy.deepcopy(pred)
    for i,p,r in zip(chosen,chosenrows,verified):
        pairs.append(dict(design_key=r['design_key'],evaluation_id=r['evaluation_id'],
                          used_for_fit=r['design_key'] in record['fit_keys'],
                          used_for_validation=r['design_key'] in record['validation_keys'],
                          **{'pred_'+k:p[k] for k in opt.OBJECTIVES},**{'fea_'+k:r[k] for k in opt.OBJECTIVES}))
        corrected[i].update({k:r[k] for k in opt.OBJECTIVES});corrected[i]['prediction_only']=False
    for r in corrected:r['status']='ok'
    from pymoo.util.nds.non_dominated_sorting import NonDominatedSorting
    guide=[corrected[int(i)] for i in NonDominatedSorting().do(-outputs(corrected),only_non_dominated_front=True)]
    opt.write_csv(folder/'verified_results.csv',verified);opt.write_csv(folder/'prediction_vs_fea.csv',pairs)
    unseen=[i for i,r in enumerate(verified) if r['design_key'] not in {p['design_key'] for p in training}]
    opt.atomic_json(folder/'verification_metrics.json',dict(
        all_selected=errors(outputs(verified),outputs(chosenrows)),unseen_n=len(unseen),
        unseen_only=errors(outputs(verified)[unseen],outputs(chosenrows)[unseen])))
    opt.write_csv(folder/'guidance_pareto.csv',guide)
    plot_predictions(folder,outputs(verified),outputs(chosenrows))
    consumed=c['initial_n']+store.attempts()
    if consumed>c['budget']:raise RuntimeError('Budget overshoot')
    opt.atomic_json(marker,dict(stage=name,guide=guide,training_pool_n=len(training),verification_n=len(verified),
                               method_charged_fea=consumed,seconds=time.monotonic()-started))
    print(f'{name}: training pool {len(training)}, verification {len(verified)}, charged FEA {consumed}/{c["budget"]}',flush=True)
    return guide


def plot_predictions(folder,actual,predicted):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,axes=plt.subplots(1,3,figsize=(12,4),layout='constrained')
    for j,ax in enumerate(axes):
        ax.scatter(actual[:,j],predicted[:,j]);lo=min(actual[:,j].min(),predicted[:,j].min());hi=max(actual[:,j].max(),predicted[:,j].max())
        ax.plot([lo,hi],[lo,hi],'k--');ax.set(xlabel='Motor-CAD',ylabel='ANN prediction',title=opt.OBJECTIVES[j])
    fig.savefig(folder/'verification_predictions.png',dpi=160);plt.close(fig)


def import_initial(store,shared):
    for r in shared:
        ix=indices(r)
        if store.lookup(ix):continue
        eid=store.start(ix,'shared_initial',None,fea_started=0)
        data={k:r[k] for k in opt.OBJECTIVES}
        data.update(reused_from_run_id=r['run_id'],reused_from_evaluation_id=r['evaluation_id'],actual_j_a_per_mm2=r['actual_j_a_per_mm2'])
        store.finish(eid,'ok','Reused shared initial FEA; charged to method, not executed again',data,0.)


def compare(root,c):
    from pymoo.indicators.hv import HV
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    allrows={};verified={};reports=[]
    # Independent800 is read ONLY here, after every training/sampling method finishes.
    reference=opt.PROJECT_ROOT/c['direct_reference']
    with reference.open(encoding='utf-8-sig') as h:direct=[r for r in csv.DictReader(h) if opt.feasible(r)]
    for method in ['conventional','sequential','alternating']:
        folder=root/method
        with (folder/'evaluations.csv').open(encoding='utf-8-sig') as h:allrows[method]=list(csv.DictReader(h))
        end='final' if method=='conventional' else '04_'+ORDERS[method][-1]
        with (folder/end/'verified_results.csv').open(encoding='utf-8-sig') as h:verified[method]=list(csv.DictReader(h))
    pooled=outputs(direct+sum(allrows.values(),[]));lo=pooled.min(0);span=np.maximum(np.ptp(pooled,axis=0),1e-12)
    if c.get('hv_calibration'):
        calibration=json.loads((opt.PROJECT_ROOT/c['hv_calibration']).read_text())
        lo=np.array(calibration['hv_normalization_min']);span=np.array(calibration['hv_normalization_span'])
    hv=HV(ref_point=np.ones(3)*1.1)
    def volume(rows):return float(hv(1-(outputs(rows)-lo)/span)) if rows else 0.
    for method,rows in allrows.items():
        folder=root/method;cost=json.loads((folder/'cost.json').read_text());end='final' if method=='conventional' else '04_'+ORDERS[method][-1]
        report=dict(method=method,**cost,archive_pareto_n=len(opt.nondominated(rows)),archive_hv=volume(rows),
                    final_verified_pareto_n=len(opt.nondominated(verified[method])),final_verified_hv=volume(verified[method]),
                    final_verification_errors=json.loads((folder/end/'verification_metrics.json').read_text()),
                    validation_metrics=json.loads((folder/end/'training.json').read_text())['validation_metrics'])
        reports.append(report)
    opt.atomic_json(root/'comparison.json',dict(methods=reports,direct800_reference_hv=volume(direct),
        hv_normalization_min=lo.tolist(),hv_normalization_span=span.tolist(),hv_reference=[1.1]*3,
        note='Direct800 independent unequal-budget reference; never used in training/sampling. HV computed on actual FEA only. One seed; validation is not a test set.'))
    flat=[]
    for r in reports:
        flat.append({k:v for k,v in r.items() if not isinstance(v,dict)})
    opt.write_csv(root/'comparison.csv',flat)
    fig,axes=plt.subplots(1,3,figsize=(14,4),layout='constrained')
    for method,rows in allrows.items():
        front=outputs(opt.nondominated(rows))
        for ax,(i,j) in zip(axes,[(0,1),(0,2),(1,2)]):
            ax.scatter(front[:,i],front[:,j],s=15,label=method);ax.set(xlabel=opt.OBJECTIVES[i],ylabel=opt.OBJECTIVES[j])
    axes[0].legend();fig.savefig(root/'comparison_pareto.png',dpi=180);plt.close(fig)
    fig,ax=plt.subplots(layout='constrained');ax.bar([r['method'] for r in reports],[r['archive_hv'] for r in reports]);ax.set(ylabel='FEA archive hypervolume');fig.savefig(root/'comparison_hv.png',dpi=160);plt.close(fig)


def run(root,c):
    root=Path(root).resolve();root.mkdir(parents=True,exist_ok=True)
    initial_n,new_budget=validate_settings(c)
    config=opt.load_config(opt.CONFIG_DIR/c['motorcad_config']);signature=opt.environment_signature(config)
    fingerprint=opt.digest(signature)
    manifest=root/'campaign.json';expected=dict(settings=c,fingerprint=fingerprint)
    if manifest.exists() and json.loads(manifest.read_text())!=expected:raise ValueError('Campaign settings/environment changed')
    opt.atomic_json(manifest,expected)
    with opt.Store(root/'shared_initial',fingerprint) as shared_store,ExitStack() as sessions:
        if (root/'comparison.json').exists():return
        if c.get('initial_reuse_from'):
            origin=opt.PROJECT_ROOT/c['initial_reuse_from']
            source_manifest=json.loads((origin.parent/'campaign.json').read_text())
            if source_manifest['fingerprint']!=fingerprint:
                raise RuntimeError('Initial reuse environment fingerprint mismatch')
            with (origin/'evaluations.csv').open(encoding='utf-8-sig') as h:
                reused=list(csv.DictReader(h))
            strict_results(reused)
            expected_keys={key(x) for x in opt.lhs_designs(initial_n,c['seed'])}
            if len(reused)!=initial_n or {r['design_key'] for r in reused}!=expected_keys:
                raise RuntimeError('Initial reuse does not match exact LHS plan')
            import_initial(shared_store,reused)
            opt.atomic_json(root/'initial_reuse.json',dict(source=str(origin),count=len(reused),fingerprint=fingerprint,
                charged_per_method=initial_n,new_physical_calls=0))
        solvers=[]
        for i in range(c['workers']):
            solver=opt.MotorCADSolver(config,root/'work'/f'worker_{i+1:02d}',single_session=False)
            sessions.callback(solver.close);solvers.append(solver)
            print(f'Worker {i+1}/{c["workers"]} ready (no smoke FEA).',flush=True)
        initial=opt.lhs_designs(initial_n,c['seed'])
        evaluate_plan(shared_store,opt.ParallelEvaluator(shared_store,solvers,initial_n),root/'initial_plan.json',initial,'shared_initial')
        shared=shared_store.rows();strict_results(shared)
        expected_initial_calls=0 if c.get('initial_reuse_from') else initial_n
        if len(shared)!=initial_n or shared_store.attempts()!=expected_initial_calls:raise RuntimeError('Shared initial accounting mismatch')
        held={key(initial[i]) for i in np.random.default_rng(c['seed']).permutation(initial_n)[:c['validation_n']]}
        opt.atomic_json(root/'validation_keys.json',sorted(held))
        for method in ['conventional','sequential','alternating']:
            folder=root/method
            if (folder/'complete.json').exists():continue
            started=time.monotonic()
            with opt.Store(folder,fingerprint) as store:
                import_initial(store,shared)
                evaluator=opt.ParallelEvaluator(store,solvers,new_budget)
                if method=='conventional':
                    stage(store,evaluator,folder,'final',c,held,doe_n=c['conventional_doe_n']-initial_n,
                          target_pool_n=c['pool_n'])
                else:
                    guide=stage(store,evaluator,folder,'initial',c,held)
                    for i,kind in enumerate(ORDERS[method],1):
                        guide=stage(store,evaluator,folder,f'{i:02d}_{kind}',c,held,
                            doe_n=c['stage_doe_counts'][i-1],kind=kind,guide=guide,
                            target_pool_n=c['stage_pool_targets'][i-1])
                store.export();strict_results(store.rows())
                opt.analyze_csv(folder/'evaluations.csv',folder/'analysis')
                stagefiles=list(folder.glob('*/training.json'))
                cost=dict(charged_fea=initial_n+store.attempts(),new_fea=store.attempts(),shared_initial_reused=initial_n,
                          wall_seconds_excluding_initial=time.monotonic()-started,
                          shared_initial_solver_seconds=sum(r['elapsed_s'] for r in shared),
                          method_solver_seconds=sum(r['elapsed_s'] or 0 for r in store.rows()),
                          ann_train_calls=len(stagefiles),ann_training_seconds=sum(json.loads(p.read_text())['training_seconds'] for p in stagefiles))
                end=folder/('final' if method=='conventional' else '04_L')
                end_state=json.loads((end/'complete.json').read_text())
                cost.update(ann_pool_n=end_state['training_pool_n'],final_verification_n=end_state['verification_n'],
                    final_fit_n=json.loads((end/'training.json').read_text())['fit_n'],
                    shared_initial_new_calls=expected_initial_calls)
                opt.atomic_json(folder/'cost.json',cost);opt.atomic_json(folder/'complete.json',dict(method=method,status='complete'))
                print(f'{method} COMPLETE: {cost}',flush=True)
        compare(root,c)
        print(f'ALL THREE {c["budget"]}-FEA METHODS COMPLETE',flush=True)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',default='ann_pool100_ver20_config.json')
    parser.add_argument('--run-dir')
    args=parser.parse_args(argv)
    settings=read_settings(args.config)
    if args.run_dir is None:
        args.run_dir=str(opt.PROJECT_ROOT/'runs'/f'ann_pool{settings["pool_n"]}_ver{settings["final_verify_n"]}_seed{settings["seed"]}')
    class Tee:
        def __init__(self,stream,log):self.stream,self.log=stream,log
        def write(self,s):self.stream.write(s);self.log.write(s);self.log.flush();return len(s)
        def flush(self):self.stream.flush();self.log.flush()
    from contextlib import redirect_stdout,redirect_stderr
    Path(args.run_dir).mkdir(parents=True,exist_ok=True)
    with (Path(args.run_dir)/'execution.log').open('a',encoding='utf-8') as log, \
            redirect_stdout(Tee(sys.stdout,log)),redirect_stderr(Tee(sys.stderr,log)):
        try:run(args.run_dir,settings)
        except BaseException as exc:
            opt.atomic_json(Path(args.run_dir)/'fatal_error.json',dict(error=repr(exc),time=opt.utcnow()))
            raise


if __name__=='__main__':
    main()
