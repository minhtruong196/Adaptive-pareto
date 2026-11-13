# Modeling pool60 + separate final20 verification

All three methods completed: pool60 = fit52 + fixed validation8; final20 distinct unseen designs are outside fitting/validation. This is NOT60 directly fitted samples. Each method charged80 FEA;180 newly executed calls across the campaign, plus reused20 initial FEA. No invalid FEA. Total campaign wall including startup: 24.68min.

| Method | Pool | Fit | Validation | Final verification | Archive Pareto n | Archive HV | Verified20 HV | HV / Direct800 % |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| conventional |60|52|8|20|26|1.050064|0.994969|91.53|
| sequential |60|52|8|20|21|1.102307|1.095134|96.09|
| alternating |60|52|8|20|25|1.098929|1.094071|95.79|

## Errors on20 unseen final designs: relative mean / maximum (%)

| Method | Torque mean | Torque max | PF mean | PF max | Efficiency mean | Efficiency max |
|---|---:|---:|---:|---:|---:|---:|
| conventional | 16.5929 | 32.4898 | 0.2073 | 0.3700 | 0.9783 | 1.7419 |
| sequential | 12.4408 | 44.2177 | 0.5252 | 2.3646 | 0.7873 | 2.0571 |
| alternating | 6.1224 | 20.7821 | 0.4917 | 1.2642 | 0.5978 | 1.5411 |

## Validation8 and verification20 R2

| Method | Validation torque | Validation PF | Validation efficiency | Verification torque | Verification PF | Verification efficiency |
|---|---:|---:|---:|---:|---:|---:|
| conventional | 0.913107 | 0.932652 | 0.887701 | 0.851383 | 0.994843 | 0.506579 |
| sequential | 0.936067 | 0.866389 | 0.979347 | 0.949256 | 0.975463 | 0.839377 |
| alternating | 0.957149 | 0.859746 | 0.956591 | 0.985621 | 0.955106 | 0.835818 |

## Exact data flow

Conventional:20 shared initial LHS +40 additional full-domain LHS =60 modeling samples. Fit52/validation8 once, then20 unseen final FEA without retraining.

Sequential stagesGGLL; Alternating stagesGLGL. Initial20 ->train12fit+8validation. Stage1:20+7DoE=27 ->fit19+val8 ->5verification. Stage2:27+5previous verification+6DoE=38 ->fit30+val8 ->5verification. Stage3:38+5previous verification+6DoE=49 ->fit41+val8 ->5verification. Stage4:49+5previous verification+6DoE=60 ->fit52+val8 ->20 finalverification, no retraining. Thus45 initial/DoE +15 priorverification =60 in each final Adaptive modeling pool.

The same eight initial validation samples are excluded from fitting/scaling at every stage and every method. They select the lowest-validation-loss checkpoint, so are not an independent test. Final20 are selected from unseen predicted-Pareto candidates by three objective extremes followed by maximin in normalized objective space. These coordinates differ among methods; this is not a common global test.

Shared initial20 were reused from the completed earlier ANN60 initial dataset only after exact fingerprint and seeded-LHS key checks. They are charged20 to each method but not re-executed. Direct800 is not a training/sampling source. Initial20 and validation8 coordinates differ from the pool100 experiment.

ANN/optimization:PyTorch7->32tanh->32tanh->3linear, Adam0.003,500 full-batch epochs, best validation checkpoint; fit-only output standardization and input original-bound scaling. Seed17, five Motor-CAD sessions, NSGA-II100population/100generations, SBX0.9 eta15, PMeta20 with rounding repair. Same settings as pool100.

Strict Global:bounds from all current guidance Pareto, zero padding/exploration. Local:up to4 objective-space farthest-center groups and1% original-domain padding. Intermediate FEA replaces predictions only for verified guidance candidates, then nondominance is recomputed. Prior verification enters the next stage together with new DoE; each stage trains once.

Physical problem:SPM18slots/4poles, seven design variables and unchanged baseline physics, stator diameter129.772mm, stator/rotor/magnet lengths100mm,1500rpm,J7A/mm2. Same bounds/steps and objective definitions as pool100:AvTorqueMsVw(Nm),PhasorPowerFactor,MotorEfficiency(%), all maximized. Actual J is checked after FEA. This is a testbed, not a completed Vernier-motor optimization study.

Archive HV uses all80 real FEA observations. Verified20 HV is only the final novel subset and may omit already known good designs in the modeling pool. The normalization min/span and reference[1.1,1.1,1.1] are fixed from the original100 report, identical to pool100+ver20. Direct800 HV=1.147174. This is an unequal-budget best-known reference, not ground truth. HV ratios are not ANN prediction accuracy.

## Costs and limitations

- conventional: new execution wall 6.28min; training calls1; ANN training0.511s; new FEA60, charged FEA80.
- sequential: new execution wall 8.83min; training calls5; ANN training2.532s; new FEA60, charged FEA80.
- alternating: new execution wall 8.50min; training calls5; ANN training2.547s; new FEA60, charged FEA80.

Wall costs exclude previously executed initial20 work; their data are nevertheless charged to each method. Single seed only. Do not infer universal superiority, generalization over the full design space or correctness of the entire predicted Pareto. Cases differ in initial sample coordinates, modeling-pool size and infill allocation. No200/300 experiment was started.

Supporting files:comparison.json/csv,correctness_audit.json,execution.log,comparison_pareto.png,comparison_hv.png; per-stage training.json/ann.pt,predicted_pareto.csv,verified_results.csv,prediction_vs_fea.csv,verification_metrics.json and plots.


## Preserved source assets after cleanup

The obsolete total-budget campaigns were removed at user request. The exact initial FEA CSV is preserved, byte-for-byte SHA256 checked, under `data/spm_initial20/shared_initial/evaluations.csv` at project root; its `campaign.json` retains the environment fingerprint, source run IDs and CSV hash. Frozen HV values are preserved in `data/spm_hv_calibration.json`. Active config and campaign-manifest paths were migrated consistently; see `cleanup_migration.json`. Training data, ANN checkpoints and reported scores in this completed run were not changed. Historical source IDs/paths inside raw records describe provenance, not active runtime dependencies.
