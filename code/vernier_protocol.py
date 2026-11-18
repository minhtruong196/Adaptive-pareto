"""Fixed-budget Vernier allocations and TXT Pareto/DOE operations."""
import math
import numpy as np
from scipy.stats import qmc
from pymoo.util.nds.non_dominated_sorting import NonDominatedSorting

OBJECTIVES=('average_torque_nm','power_factor','efficiency_pct')


def apportion(n,weights):
    total=sum(weights);counts=[n*w//total for w in weights]
    order=sorted(range(len(weights)),key=lambda i:(-(n*weights[i]%total),i))
    for i in order[:n-sum(counts)]:counts[i]+=1
    return counts


def allocation(n=300,method='adaptive'):
    if isinstance(n,bool) or int(n)!=n or n<1:raise ValueError('Evaluations must be a positive integer')
    n=int(n);train,val,test=apportion(n,[7,2,1]);pool=train+val
    if method=='static':
        stages=[dict(name='Initial',kind='initial',verify=0,doe_train=train,val=val,cumulative_train=train,cumulative_val=val)]
    elif method=='adaptive':
        blocks=apportion(pool,[2,1,1,1,1]);vals=apportion(val,blocks)
        stages=[];ct=cv=0
        for i,(name,kind,block,v) in enumerate(zip(['Initial','G1','G2','L1','L2'],['initial','G','G','L','L'],blocks,vals)):
            verify=0 if i==0 else 5;t=block-v
            if t<=verify or v<1:raise ValueError('Budget too small for four verify5 rounds and Train/Val DOE')
            ct+=t;cv+=v
            stages.append(dict(name=name,kind=kind,verify=verify,doe_train=t-verify,val=v,cumulative_train=ct,cumulative_val=cv))
    else:raise ValueError('Method must be static or adaptive')
    if train<8 or val<2 or test<1:raise ValueError('Budget too small to fit and validate ANN')
    return dict(total=n,train=train,val=val,test=test,pool=pool,stages=stages)


def point_key(point):return tuple((k,round(float(v),8)) for k,v in sorted(point.items()))


def nondominated(rows):
    if not rows:return []
    indices=NonDominatedSorting().do(-np.array([r['prediction'] for r in rows]),only_non_dominated_front=True)
    return [rows[int(i)] for i in indices]


def choose_checks(candidates,seen,n):
    excluded={point_key(p) for p in seen};unique={}
    for r in candidates:
        key=point_key(r['point'])
        if key not in excluded:unique.setdefault(key,r)
    rows=list(unique.values())
    if len(rows)<n:raise ValueError(f'Only {len(rows)} unseen Pareto candidates for {n} checks; no FEA added')
    y=np.array([r['prediction'] for r in rows]);z=(y-y.min(0))/np.maximum(np.ptp(y,axis=0),1e-12)
    selected=list(dict.fromkeys(map(int,np.argmax(y,axis=0))))[:n]
    while len(selected)<n:
        distance=((z[:,None,:]-z[selected][None,:,:])**2).sum(2).min(1)
        distance[selected]=-1;selected.append(int(np.argmax(distance)))
    return [rows[i] for i in selected]


def corrected_guide(candidates,actual):
    """Correct checked predictions as before; additionally admit explicit Val rows.

    Historical Train DOE remains available for fitting/FEA reporting, but is not
    automatically injected into the next guidance front. Val participates in
    guidance under the agreed validation rule and never enters stage fitting.
    """
    observed={point_key(r['point']):r for r in actual};mixed={}
    for r in candidates:
        key=point_key(r['point']);a=observed.get(key)
        if a is None:mixed[key]=r
        elif a['status']=='ok':mixed[key]=dict(point=r['point'],prediction=[a[k] for k in OBJECTIVES],verified=True)
    for key,r in observed.items():
        if r.get('role')=='val' and r['status']=='ok':
            mixed[key]=dict(point=r['point'],prediction=[r[k] for k in OBJECTIVES],verified=True)
    if not mixed:raise ValueError('No valid predicted/FEA guidance remains; stop without fallback FEA')
    return nondominated(list(mixed.values()))


def local_boxes(guide,bounds,kind,groups=4,padding=.01):
    names=list(bounds);lo=np.array([v[0] for v in bounds.values()]);hi=np.array([v[1] for v in bounds.values()]);span=hi-lo
    x=np.array([[r['point'][k] for k in names] for r in guide])
    if not len(x):raise ValueError('Empty guidance')
    if kind=='G':return [(np.maximum(lo,x.min(0)),np.minimum(hi,x.max(0)))]
    if kind!='L':raise ValueError('Expected G or L')
    y=np.array([r['prediction'] for r in guide]);scale=np.maximum(np.ptp(y,axis=0),1e-12);z=(y-y.min(0))/scale
    centers=choose_checks(guide,[],min(groups,len(guide)))
    cz=(np.array([r['prediction'] for r in centers])-y.min(0))/scale
    assignment=((z[:,None,:]-cz[None,:,:])**2).sum(2).argmin(1);boxes=[]
    for j in range(len(centers)):
        part=x[assignment==j]
        if len(part):boxes.append((np.maximum(lo,part.min(0)-padding*span),np.minimum(hi,part.max(0)+padding*span)))
    return boxes


def sample_points(n,bounds,base,seed,seen=(),boxes=None):
    """Preserve recovered narrow runner sampling, including its eight decimals.

    Initial/search use make_plan's filtered LHS batches. G/L use a new seeded
    32-point batch per selected point, alternating the local boxes as before.
    All filtering precedes FEA; it never adds replacement solver calls.
    """
    from vernier_model import margins
    if n<1:raise ValueError('Need a positive DOE allocation')
    names=list(bounds);lo=np.array([v[0] for v in bounds.values()]);hi=np.array([v[1] for v in bounds.values()])
    excluded={point_key(p) for p in seen};chosen=[]
    if boxes is None:
        sampler=qmc.LatinHypercube(len(names),seed=seed)
        for _ in range(1000):
            for xx in lo+sampler.random(max(64,n*4))*(hi-lo):
                point=dict(zip(names,map(float,np.round(xx,8))));key=point_key(point)
                if key not in excluded and min(margins(point,base).values())>1e-8:
                    chosen.append(point);excluded.add(key)
                    if len(chosen)==n:return chosen
        raise ValueError('DOE region cannot provide enough unseen feasible points; no fallback/replacement FEA')
    if not boxes:raise ValueError('Empty DOE region')
    for left,right in boxes:
        left,right=map(np.asarray,(left,right))
        if np.any(left>right) or np.any(left<lo-1e-10) or np.any(right>hi+1e-10):raise ValueError('DOE region outside fixed bounds')
    for i in range(n):
        left,right=map(np.asarray,boxes[i%len(boxes)])
        sampler=qmc.LatinHypercube(len(names),seed=seed+i);found=None
        for _ in range(1000):
            for xx in left+sampler.random(32)*(right-left):
                point=dict(zip(names,map(float,np.round(xx,8))));key=point_key(point)
                if key not in excluded and min(margins(point,base).values())>1e-8:
                    found=point;break
            if found is not None:break
        if found is None:raise ValueError('DOE region cannot provide enough unseen feasible points; no fallback/replacement FEA')
        chosen.append(found);excluded.add(point_key(found))
    return chosen


def search_pareto(model,bounds,base,seed=17,population=100,generations=100,seen=()):
    from pymoo.core.problem import Problem
    from pymoo.algorithms.moo.nsga2 import NSGA2
    from pymoo.optimize import minimize
    from vernier_model import margins
    from vernier_mlp import predict
    names=list(bounds);lo=np.array([v[0] for v in bounds.values()]);hi=np.array([v[1] for v in bounds.values()]);archive={}
    class Surrogate(Problem):
        def __init__(self):super().__init__(n_var=len(names),n_obj=3,n_ieq_constr=len(margins({},base))+5,xl=lo,xu=hi)
        def _evaluate(self,x,out,*args,**kwargs):
            x=np.array([[float(f'{v:.12g}') for v in row] for row in x]);y=predict(model,x);constraints=[]
            for xx,yy in zip(x,y):
                point=dict(zip(names,map(float,xx)));t,pf,eff=yy
                limits=np.r_[1e-8-np.array(list(margins(point,base).values())),1e-8-t,1e-8-pf,pf-(1-1e-8),1e-8-eff,eff-(100-1e-8)]
                constraints.append(limits)
                if np.all(limits<=0):archive.setdefault(point_key(point),dict(point=point,prediction=yy.tolist()))
            out['F']=-y;out['G']=np.array(constraints)
    initial=sample_points(population,bounds,base,seed+101)
    minimize(Surrogate(),NSGA2(pop_size=population,sampling=np.array([[p[k] for k in names] for p in initial])),
             ('n_gen',generations),seed=seed,verbose=False)
    excluded={point_key(p) for p in seen}
    result=nondominated([r for k,r in archive.items() if k not in excluded])
    if not result:raise ValueError('ANN produced no unseen feasible Pareto; no FEA started')
    return result
