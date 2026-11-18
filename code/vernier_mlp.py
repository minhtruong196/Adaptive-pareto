"""Solver-free shared-output Vernier MLP and leakage-free offline evaluation.

All artifacts belong to the explicitly supplied folder. Completed fits may be
reopened only with an identical data/settings fingerprint. Short epoch counts
are intended solely for explicitly labelled synthetic tests and dry runs.
"""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import numpy as np
import torch


OBJECTIVES = ('average_torque_nm', 'power_factor', 'efficiency_pct')
_VERSION = 2


def _json(path, payload):
    path = Path(path)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(payload, indent=2, allow_nan=False), encoding='utf-8')
    temporary.replace(path)


def _save(path, payload):
    temporary = path.with_name(path.name + '.tmp')
    torch.save(payload, temporary)
    temporary.replace(path)


def _bounds(bounds):
    names = list(bounds)
    if not names:
        raise ValueError('bounds must contain input names')
    lo = np.array([bounds[name][0] for name in names], dtype=float)
    span = np.array([bounds[name][1] for name in names], dtype=float) - lo
    if not np.isfinite(lo).all() or not np.isfinite(span).all() or np.any(span <= 0):
        raise ValueError('bounds must be finite and increasing')
    return names, lo, span


def _rows(rows, names):
    normalized = []
    for original in rows:
        row = {**original.get('data', {}), **original}
        point_id = row.get('point_id')
        if isinstance(point_id, bool) or not isinstance(point_id, (int, np.integer)) or point_id < 1:
            raise ValueError('point_id must be a one-based integer')
        if row.get('status', 'ok') != 'ok':
            raise ValueError('MLP rows must have status ok')
        point = row['point']
        normalized.append(dict(point_id=int(point_id),
                               x=[float(point[name]) for name in names],
                               y=[float(row[name]) for name in OBJECTIVES]))
    ids = [r['point_id'] for r in normalized]
    if len(set(ids)) != len(ids):
        raise ValueError('duplicate point_id in model data')
    if normalized and not np.isfinite([r['x'] + r['y'] for r in normalized]).all():
        raise ValueError('model inputs and outputs must be finite')
    return normalized


def _network(n_inputs):
    return torch.nn.Sequential(torch.nn.Linear(n_inputs, 32), torch.nn.Tanh(),
                               torch.nn.Linear(32, 32), torch.nn.Tanh(),
                               torch.nn.Linear(32, 3))


def _fingerprint(payload):
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':'),
                                      allow_nan=False).encode('utf-8')).hexdigest()


def _manifest(folder, payload):
    """Write identity before work so interrupted fits cannot change their data."""
    folder.mkdir(parents=True, exist_ok=True)
    fingerprint = _fingerprint(payload)
    path = folder/'fingerprint.json'
    if path.exists():
        saved = json.loads(path.read_text(encoding='utf-8'))
        if saved['fingerprint'] != fingerprint:
            raise ValueError('model fingerprint differs from saved data/settings')
    elif any(folder.glob('*.pt')) or (folder/'training.json').exists():
        raise ValueError('saved model has no verifiable fingerprint')
    else:
        _json(path, dict(fingerprint=fingerprint, identity=payload))
    return fingerprint


def _model(net, lo, span, mean, scale, names, record):
    net.eval()
    return dict(net=net, lo=lo, span=span, mean=mean, scale=scale,
                names=names, record=record)


def predict(model, x):
    """Predict physical output units from inputs in fixed-bound name order."""
    x = np.asarray(x, dtype=float)
    if x.size == 0:
        return np.empty((0, 3), dtype=float)
    if x.ndim == 1:
        x = x.reshape(1, -1)
    if x.ndim != 2 or x.shape[1] != len(model['names']) or not np.isfinite(x).all():
        raise ValueError('prediction inputs must be finite with one column per input')
    with torch.no_grad():
        scaled = torch.tensor((x - model['lo']) / model['span'], dtype=torch.float32)
        return model['net'](scaled).numpy().astype(float)*model['scale'] + model['mean']


def metrics(actual, predicted):
    """Physical-unit errors; bias is predicted minus actual, MAPE excludes zeros."""
    actual, predicted = np.asarray(actual, dtype=float), np.asarray(predicted, dtype=float)
    if actual.size == 0 and predicted.size == 0:
        actual = predicted = np.empty((0, 3))
    if actual.ndim != 2 or actual.shape != predicted.shape or actual.shape[1] != 3:
        raise ValueError('metrics require matching N x 3 arrays')
    if not np.isfinite(actual).all() or not np.isfinite(predicted).all():
        raise ValueError('metrics require finite outputs')
    result = dict(n=len(actual), objectives={})
    for j, name in enumerate(OBJECTIVES):
        target, error = actual[:, j], predicted[:, j] - actual[:, j]
        nonzero = np.abs(target) > 0
        relative = np.abs(error[nonzero] / target[nonzero])*100
        sse = float(np.sum(error**2))
        total = float(np.sum((target-target.mean())**2)) if len(target) else 0.
        r2 = (1.-sse/total if total > 0 else (1. if sse == 0 else None)) if len(target) else None
        mae = float(np.mean(np.abs(error))) if len(error) else None
        mape = float(np.mean(relative)) if len(relative) else None
        bias = float(error.mean()) if len(error) else None
        result['objectives'][name] = dict(
            n=len(target), mae=mae, rmse=float(np.sqrt(np.mean(error**2))) if len(error) else None,
            mape=mape, r2=r2, bias=bias, mean_relative_error_pct=mape,
            mean_signed_error=bias, overpredicted_n=int(np.sum(error > 0)),
            underpredicted_n=int(np.sum(error < 0)), zero_actual_n=int(np.sum(~nonzero)),
            max_relative_error_pct=float(relative.max()) if len(relative) else None,
            max_absolute_error=float(np.max(np.abs(error))) if len(error) else None)
    return result


def _prediction_records(model, normalized, role):
    predicted = predict(model, [r['x'] for r in normalized])
    return [dict(point_id=row['point_id'], role=role,
                 actual=dict(zip(OBJECTIVES, row['y'])),
                 predicted=dict(zip(OBJECTIVES, prediction.tolist())))
            for row, prediction in zip(normalized, predicted)]


def fit_model(train_rows, val_rows, bounds, folder, seed=17, epochs=500,
              min_checkpoint_epoch=300, merged=False):
    """Fit every epoch; stage checkpoints compete only at/after the epoch floor.

    ``merged=True`` requires an empty Val set and returns the final epoch. The
    fold trainer uses this same final-epoch mode with only its four fit folds.
    """
    if not isinstance(epochs, int) or epochs < 1:
        raise ValueError('epochs must be a positive integer')
    if not isinstance(min_checkpoint_epoch, int) or not 1 <= min_checkpoint_epoch <= epochs:
        raise ValueError('checkpoint epoch floor must lie between 1 and epochs; shorten it explicitly in tests')
    names, lo, span = _bounds(bounds)
    train, val = _rows(train_rows, names), _rows(val_rows, names)
    if not train:
        raise ValueError('training data must not be empty')
    if set(r['point_id'] for r in train) & set(r['point_id'] for r in val):
        raise ValueError('Train and Val point IDs overlap')
    if set(tuple(r['x']) for r in train) & set(tuple(r['x']) for r in val):
        raise ValueError('Train and Val geometries overlap')
    if merged and val:
        raise ValueError('merged fit must not use a validation set')
    if not merged and not val:
        raise ValueError('stage fit requires the explicit validation set')
    settings = dict(version=_VERSION, architecture=[len(names), 32, 32, 3], activation='Tanh',
                    optimizer='Adam', learning_rate=.003, weight_decay=0.,
                    scheduler=None, seed=int(seed),
                    epochs=epochs, min_checkpoint_epoch=min_checkpoint_epoch, merged=bool(merged),
                    names=names, lo=lo.tolist(), span=span.tolist(), objectives=list(OBJECTIVES),
                    dtype='float32', device='cpu', torch_version=str(torch.__version__))
    folder = Path(folder)
    fingerprint = _manifest(folder, dict(settings=settings, train=train, validation=val))
    if (folder/'ann.pt').exists() and (folder/'training.json').exists():
        saved = torch.load(folder/'ann.pt', map_location='cpu', weights_only=True)
        record = json.loads((folder/'training.json').read_text(encoding='utf-8'))
        if saved['fingerprint'] != fingerprint or record['fingerprint'] != fingerprint:
            raise ValueError('saved checkpoint fingerprint does not match training record')
        net = _network(len(names))
        net.load_state_dict(saved['state'])
        return _model(net, lo, span, np.asarray(saved['mean']), np.asarray(saved['scale']), names, record)
    # CPU, one thread and fixed seed give deterministic restarts independent of a
    # previously interrupted fit. Validation does not participate in any update.
    torch.set_num_threads(1)
    torch.manual_seed(seed)
    y = np.asarray([row['y'] for row in train], dtype=float)
    mean, scale = y.mean(axis=0), y.std(axis=0)
    scale[scale == 0] = 1.
    x = torch.tensor((np.asarray([row['x'] for row in train])-lo)/span, dtype=torch.float32)
    target = torch.tensor((y-mean)/scale, dtype=torch.float32)
    vx = torch.tensor((np.asarray([row['x'] for row in val]).reshape(-1, len(names))-lo)/span,
                      dtype=torch.float32)
    vy = torch.tensor((np.asarray([row['y'] for row in val]).reshape(-1, 3)-mean)/scale,
                      dtype=torch.float32)
    net = _network(len(names))
    optimizer = torch.optim.Adam(net.parameters(), lr=.003)
    curve, best_loss, selected, selected_state = [], float('inf'), None, None
    for epoch in range(1, epochs+1):
        net.train()
        optimizer.zero_grad()
        loss = ((net(x)-target)**2).mean()
        loss.backward()
        optimizer.step()
        net.eval()
        with torch.no_grad():
            train_target = ((net(x)-target)**2).mean(dim=0).tolist()
            val_target = ((net(vx)-vy)**2).mean(dim=0).tolist() if val else None
        validation_loss = float(np.mean(val_target)) if val else None
        curve.append(dict(epoch=epoch, learning_rate=optimizer.param_groups[0]['lr'],
                          train_loss=float(np.mean(train_target)), train_target_loss=train_target,
                          validation_loss=validation_loss, validation_target_loss=val_target))
        if not merged and epoch >= min_checkpoint_epoch and validation_loss < best_loss:
            best_loss, selected = validation_loss, epoch
            selected_state = {key: value.detach().clone() for key, value in net.state_dict().items()}
    final_state = {key: value.detach().clone() for key, value in net.state_dict().items()}
    if merged:
        selected, selected_state = epochs, final_state
    checkpoint = dict(fingerprint=fingerprint, state=final_state, mean=mean.tolist(),
                      scale=scale.tolist(), names=names, lo=lo.tolist(), span=span.tolist(),
                      epoch=epochs, settings=settings)
    _save(folder/'final_epoch.pt', checkpoint)
    net.load_state_dict(selected_state)
    record = dict(fingerprint=fingerprint, settings=settings, fit_n=len(train), validation_n=len(val),
                  fit_ids=[r['point_id'] for r in train], validation_ids=[r['point_id'] for r in val],
                  epochs_completed=epochs, selected_epoch=selected,
                  checkpoint_selection='final_epoch' if merged else 'minimum_validation_loss_after_floor',
                  selected_validation_loss=best_loss if val else None, merged=bool(merged), curve=curve,
                  scaler_mean=mean.tolist(), scaler_scale=scale.tolist())
    model = _model(net, lo, span, mean, scale, names, record)
    validation_report = metrics([r['y'] for r in val], predict(model, [r['x'] for r in val]))
    record['validation_metrics'] = validation_report
    record['val_metrics'] = validation_report
    record['files'] = {name: str(folder/name) for name in (
        'ann.pt', 'final_epoch.pt', 'scalers.json', 'training.json', 'loss_curve.csv', 'predictions.json')}
    if val:
        _json(folder/'premerge_validation.json', dict(
            report_type='historical_premerge_validation', selected_epoch=selected,
            fit_ids=record['fit_ids'], validation_ids=record['validation_ids'], metrics=validation_report))
    _json(folder/'scalers.json', dict(input_names=names, input_lo=lo.tolist(), input_span=span.tolist(),
                                    output_names=list(OBJECTIVES), mean=mean.tolist(), scale=scale.tolist(),
                                    fit_ids=record['fit_ids']))
    _json(folder/'predictions.json', _prediction_records(model, train, 'Train') +
          _prediction_records(model, val, 'Val'))
    with (folder/'loss_curve.csv').open('w', newline='', encoding='utf-8') as stream:
        fields = ['epoch', 'learning_rate', 'train_loss', 'validation_loss'] + [
            role+'_'+name for role in ('train', 'validation') for name in OBJECTIVES]
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in curve:
            flat = {key: row[key] for key in fields[:4]}
            for role in ('train', 'validation'):
                losses = row[role+'_target_loss']
                flat.update({role+'_'+name: losses[j] if losses else None
                             for j, name in enumerate(OBJECTIVES)})
            writer.writerow(flat)
    checkpoint.update(state=selected_state, epoch=selected)
    _save(folder/'ann.pt', checkpoint)
    _json(folder/'training.json', record)
    return model


def cross_validate(rows, bounds, folder, seed=17, folds=5, epochs=500):
    """Shuffled K-fold OOF evaluation with final-epoch fit and fold-only scalers."""
    names, lo, span = _bounds(bounds)
    rows = list(rows)
    normalized = _rows(rows, names)
    if not isinstance(folds, int) or folds < 2 or folds > len(rows):
        raise ValueError('cross-validation folds must be between 2 and row count')
    folder = Path(folder)
    fingerprint = _manifest(folder, dict(version=_VERSION, purpose='cross_validation',
        rows=normalized, names=names, lo=lo.tolist(), span=span.tolist(), seed=int(seed),
        folds=folds, epochs=epochs))
    indices = np.random.default_rng(seed).permutation(len(rows))
    partitions = np.array_split(indices, folds)
    fold_reports, oof = [], []
    for number, held in enumerate(partitions, 1):
        held_set = set(held.tolist())
        fit_indices = [i for i in range(len(rows)) if i not in held_set]
        model = fit_model([rows[i] for i in fit_indices], [], bounds, folder/f'fold_{number}',
                          seed=seed, epochs=epochs, min_checkpoint_epoch=min(300, epochs), merged=True)
        predicted = predict(model, [normalized[i]['x'] for i in held])
        report = metrics([normalized[i]['y'] for i in held], predicted)
        fold_reports.append(dict(fold=number, fit_ids=model['record']['fit_ids'],
            validation_ids=[], test_ids=[normalized[i]['point_id'] for i in held],
            selected_epoch=model['record']['selected_epoch'], scaler_mean=model['mean'].tolist(),
            scaler_scale=model['scale'].tolist(), metrics=report,
            checkpoint=str(folder/f'fold_{number}'/'ann.pt')))
        for i, prediction in zip(held, predicted):
            oof.append(dict(point_id=normalized[i]['point_id'], fold=number,
                            actual=dict(zip(OBJECTIVES, normalized[i]['y'])),
                            predicted=dict(zip(OBJECTIVES, prediction.tolist()))))
    oof.sort(key=lambda row: row['point_id'])
    summary = {}
    for name in OBJECTIVES:
        summary[name] = {}
        for metric in ('mae', 'rmse', 'mape', 'r2', 'bias', 'mean_relative_error_pct', 'mean_signed_error'):
            values = [fold['metrics']['objectives'][name][metric] for fold in fold_reports
                      if fold['metrics']['objectives'][name][metric] is not None]
            summary[name][metric] = dict(n=len(values), mean=float(np.mean(values)) if values else None,
                sample_sd=float(np.std(values, ddof=1)) if len(values) > 1 else None)
    with (folder/'oof_predictions.csv').open('w', newline='', encoding='utf-8') as stream:
        fields = ['point_id', 'fold'] + [role+'_'+name for role in ('actual', 'predicted') for name in OBJECTIVES]
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in oof:
            writer.writerow(dict(point_id=row['point_id'], fold=row['fold'], **{
                role+'_'+name: row[role][name] for role in ('actual', 'predicted') for name in OBJECTIVES}))
    result = dict(fingerprint=fingerprint, n=len(rows), seed=int(seed), fold_count=folds,
                  epochs=epochs, checkpoint_selection='final_epoch', folds=fold_reports,
                  summary=summary, oof_predictions=oof,
                  oof_metrics=metrics([[row['actual'][name] for name in OBJECTIVES] for row in oof],
                                      [[row['predicted'][name] for name in OBJECTIVES] for row in oof]),
                  files=dict(report=str(folder/'cross_validation.json'),
                             oof_predictions=str(folder/'oof_predictions.csv')))
    _json(folder/'cross_validation.json', result)
    return result
