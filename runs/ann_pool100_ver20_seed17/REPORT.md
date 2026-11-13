# ANN pool100 + final 20 verification results

All three methods completed. IMPORTANT: each final modeling pool is 100 = fit 92 + fixed validation 8. This completed run does NOT mean100 directly fitted samples. Final 20 designs are excluded from both fit and validation; no final retraining.

Each method charged120 FEA:40 reused shared initial +80 newly executed. Total new calls240. Initial reuse source: old ANN100 initial40, verified matching fingerprint/LHS keys. Direct800 never used in training/sampling.

| Method | Pool | Fit | Validation | Final verification | Archive Pareto n | Archive HV | Verified20 HV | HV/archive Direct800 % |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| conventional |100|92|8|20|27|1.086135|1.067533|94.68|
| sequential |100|92|8|20|41|1.125000|1.097108|98.07|
| alternating |100|92|8|20|38|1.122135|1.099679|97.82|

## Verification errors: mean relative / maximum relative (%)

| Method | Torque mean | Torque max | PF mean | PF max | Efficiency mean | Efficiency max |
|---|---:|---:|---:|---:|---:|---:|
| conventional | 9.7819 | 24.4201 | 0.3483 | 1.0337 | 0.6745 | 1.3244 |
| sequential | 2.8286 | 10.5001 | 0.1429 | 0.4159 | 0.1755 | 0.5226 |
| alternating | 2.9524 | 9.6607 | 0.1649 | 0.9771 | 0.2018 | 1.1471 |

## Cost and interpretation

- conventional: new execution wall 7.83min, ANN training 0.522s, train calls 1.
- sequential: new execution wall 10.10min, ANN training 2.424s, train calls 5.
- alternating: new execution wall 10.46min, ANN training 2.438s, train calls 5.

HV uses the original 100-report normalization unchanged; Direct800 HV=1.147174. Direct800 is an unequal-budget reference, not ground truth. Prior total100 runs had pool95+final5; do not treat this total120 run as equal budget to them.

Final 20 are novel predicted-Pareto candidates selected by extremes/maximin. They differ between methods; verification R2/errors are not a common global test. Archive HV includes all120 real FEA records including known designs. Verified20 HV is a subset metric, not confirmation of the entire predicted Pareto.

Adaptive pools40/52/68/84/100 include previous-stage verification exactly once. The15 intermediate verification samples enter subsequent training; the final 20 never do.

Artifacts: comparison.json/csv, correctness_audit.json, execution.log, comparison_pareto.png, comparison_hv.png; per-stage ANN checkpoint, training.json, prediction_vs_fea.csv, verification_metrics.json, verified_results.csv and plots.


## Experimental problem and data generation

This is a pilot Motor-CAD2025.2 study of an SPM motor (18slots/4poles), not a completed ANN study of the dual-stator Vernier motor mentioned in the broader research context. All three objectives are maximized: average electromagnetic torque `AvTorqueMsVw` (Nm), signed phasor power factor `PhasorPowerFactor`, and motor efficiency `MotorEfficiency` (%). Shaft torque and system efficiency are distinct supplementary outputs, not substituted objectives.

| Independent variable | Lower | Upper | Step |
|---|---:|---:|---:|
| Ratio_Bore |0.5|0.8|0.0001|
| Ratio_SlotDepth_ParallelTooth |0.5|0.8|0.0001|
| Ratio_ToothWidth |0.3|0.65|0.0001|
| Ratio_ShaftD |0.5|0.8|0.0001|
| Ratio_MagnetArc |0.7|0.9|0.05|
| Magnet_Thickness (mm) |3|5|0.5|
| Slot_Corner_Radius (mm) |0|2|0.5|

The geometry is represented on an integer grid, with rounding repair and duplicate exclusion. Stator outside diameter129.772mm; stator/rotor/magnet lengths100mm. Operating point1500rpm, phase advance0degrees, DC bus400V; no additional voltage constraint imposed. Current-density mode targets7A/mm2, independently checked after FEA using calculated RMS current and round copper area. Other winding/material/operating/loss/thermal settings are inherited from the baseline. No additional physical assumptions were introduced during ANN optimization.

Motor-CAD calls use separate worker directories with five sessions in parallel. Geometry/readback, calculation and output-validity failures would be recorded and excluded; this campaign had no invalid FEA. The original model is not overwritten. The shared initial40 are real evaluations reused from an earlier ANN campaign only after exact model/environment fingerprint and seeded-LHS key matching. They are NOT taken from the Direct800 optimization dataset.

## Exact training and verification flow

Terminology: a modeling pool contains both fitting and validation samples. Fitting samples enter gradient optimization. Validation samples select the ANN checkpoint. Final verification samples enter neither fitting nor validation. These roles must not be conflated.

Conventional: initial40 LHS +60 additional unique full-domain LHS samples -> pool100 -> fit 92/validation 8 -> one ANN fit -> NSGA-II on ANN -> select20 unseen candidates -> real FEA. The combined DoE is the union of two LHS batches, not a single freshly stratified100-point LHS.

Adaptive stage order is GGLL for Sequential and GLGL for Alternating. Both use the following allocation:

| Step | Newly sampled DoE | Verification inherited from previous step | Pool at training | Fit | Validation | Verification after training |
|---|---:|---:|---:|---:|---:|---:|
| Initial |40|0|40|32|8|0|
| Stage1 |12|0|52|44|8|5|
| Stage2 |11|5|68|60|8|5|
| Stage3 |11|5|84|76|8|5|
| Stage4 |11|5|100|92|8|20|

Thus Adaptive pool100 =85 initial/DoE +15 previous-stage verification samples. Each sample is counted once, even though cumulative data are used in multiple training calls. The20 final samples never enter ANN fitting. ANN fitting occurs five times for Adaptive, once for Conventional. The same eight initial samples are held out for validation in every method and every stage. No intermediate verification is followed by immediate retraining: it enters the next stage together with that stage's new DoE.

The sampler excludes existing designs. If an intermediate verification reuses an already evaluated point, extra DoE at the next stage fills the exact pool target, rather than counting the same design twice. This completed campaign achieved all specified pool targets and20 distinct unseen final designs for each method.

## ANN and Pareto-search settings

Seed17, one campaign seed only. PyTorch feed-forward network7->32tanh->32tanh->3linear, CPU fitting, full-batch Adam with learning rate0.003. Each training call runs500 epochs and restores the checkpoint with lowest standardized validation MSE; it does not stop early based on final verification. Input grid indices are scaled to[0,1] using the original design bounds. Output means/standard deviations are fitted only on fitting data, never on validation or verification labels.

The eight validation samples are selected by a seed 17 permutation of the40 initial samples and remain fixed. Validation is used for checkpoint selection and is NOT an independent test set. Model architecture/hyperparameters are held fixed across methods. At each Adaptive stage the network is fitted afresh on the accumulated fitting data.

Surrogate optimization uses pymoo NSGA-II, population 100,100 generations, integer random sampling, SBX crossover(probability0.9,eta15), polynomial mutation(eta20, pymoo default individual probability0.9 and per-variable probability1/7), rounding repair and duplicate elimination. Objective predictions are converted to minimization by changing sign. Raw predictions are saved without clipping them to physical output bounds; only actual valid FEA results enter the confirmed archive metrics.

Global infill: LHS within per-variable min/max of the entire current guidance Pareto; zero Global padding and zero exploration. Local infill: up to four groups in normalized predicted-objective space. Centers are selected from objective extremes followed by maximin, points assigned to the nearest center, and LHS sampled within each group's design-variable box with1% original-domain padding and clipping to original bounds. This is a specified implementation of the project's V1 workflow, not a replication of the published Barri APA.

After intermediate verification, FEA values replace predictions for those candidates in the guidance set, then nondominance is recomputed. Unverified guidance candidates remain predictions. All FEA observations are retained for subsequent training, including points removed from the guidance Pareto.

## Selection and interpretation of final verification

For each frozen final ANN, select up to20 distinct candidates from its predicted Pareto that are absent from its entire modeling pool. Selection starts with the maximum Torque/PF/Efficiency candidates in that eligible set, followed by greedy maximin in min/max-normalized objective space. Repeated extremes are deduplicated and filled by maximin. Each method obtained20 eligible candidates in this run.

This is a targeted check of each model's own proposed Pareto, NOT a common uniform test of global surrogate accuracy. Methods' final 20 coordinates differ. Any known Pareto designs already in the modeling pool remain in the full FEA archive but are excluded from the novel20-point subset. Hence verified20 HV is not the HV of all known good designs, and lower subset HV alone does not demonstrate inferior full-archive quality.

Twenty verification points provide broader coverage than five but do not prove that the entire predicted Pareto is correct. No final verification labels are used for model tuning/retraining in this campaign.

Errors are computed separately per objective: absolute errors areabs(ANN-FEA); MAE is their mean; RMSE is sqrt(mean((ANN-FEA)^2)); relative errors are100*abs(ANN-FEA)/abs(FEA). Reported mean and maximum relative errors are different summaries, not interchangeable. Efficiency absolute error is in percentage points; relative error is in percent of the FEA efficiency. R2=1-SSE/SST on the specified evaluation set.

## R2: validation 8 versus final verification20

| Method | Validation torque | Validation PF | Validation efficiency | Verification torque | Verification PF | Verification efficiency |
|---|---:|---:|---:|---:|---:|---:|
| conventional | 0.967431 | 0.980082 | 0.968377 | 0.900259 | 0.969056 | 0.657467 |
| sequential | 0.902098 | 0.942076 | 0.907855 | 0.994157 | 0.995373 | 0.973775 |
| alternating | 0.908422 | 0.933906 | 0.919669 | 0.991619 | 0.991641 | 0.962475 |

These R2 columns measure different sets and must not be treated as directly interchangeable. The validation set is shared across methods; the final verification sets differ.

## Hypervolume definition and reference

All reported HV values in this document use the SAME fixed calibration, inherited from the original100-total-FEA report. Objective order isTorque, PF, Efficiency. Setz=(y-min)/span for maximized physical outputs andF=1-z for minimization; compute dominated HV with reference[1.1,1.1,1.1]. No normalization is refitted for an individual method.

- Calibration min: [4.54883620411918, 0.884752904222439, 79.5612967771118]
- Calibration span: [18.52456735421862, 0.11341821372885497, 11.529350551225392]

Archive HV is based on nondominance over all120 available real FEA designs per method, including reused initial data. Verified20 HV uses only the20 final newly verified designs. Predicted ANN-only candidates never contribute to these FEA HV values.

The fixed calibration was derived posthoc from earlier completed data, not from a priori physical bounds. Its numerical choice affects HV values and percentage gains; conclusions should not depend on mixing calibrations. An HV ratio such as98.07% of Direct800 does NOT mean98.07% prediction accuracy, convergence or pointwise agreement. Direct800 is a best-known unequal-budget reference, not the true Pareto front.

## Scope of conclusions and supporting files

This is a one-seed pilot. It supports comparison of the observed FEA archives and final candidate prediction errors in this run, not a general claim that one method wins at every seed or problem. Global generalization remains weakly assessed because validation has only eight samples and is used for model selection. Independent common-set testing and multi-seed stability have not been established here. No200/300 follow-up results are included in this report.

The report is self-contained for understanding the protocol, but raw numerical auditing requires the supporting data. Recommended attachments are the campaign config, comparison.json, correctness_audit.json, each method's evaluations.csv, and each final stage's training.json, prediction_vs_fea.csv, verified_results.csv. Per-stage files additionally permit checking the Adaptive data-flow schedule.


## Preserved source assets after cleanup

The obsolete total-budget campaigns were removed at user request. The exact initial FEA CSV is preserved, byte-for-byte SHA256 checked, under `data/spm_initial40/shared_initial/evaluations.csv` at project root; its `campaign.json` retains the environment fingerprint, source run IDs and CSV hash. Frozen HV values are preserved in `data/spm_hv_calibration.json`. Active config and campaign-manifest paths were migrated consistently; see `cleanup_migration.json`. Training data, ANN checkpoints and reported scores in this completed run were not changed. Historical source IDs/paths inside raw records describe provenance, not active runtime dependencies.
