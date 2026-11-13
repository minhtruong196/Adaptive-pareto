# Pool60 vs pool100, final20 each, fixed HV calibration

| Pool | Method | Charged FEA | Archive HV | Verified20 HV | Torque mean error % | Torque max error % |
|---|---|---:|---:|---:|---:|---:|
|60|conventional|80|1.050064|0.994969|16.5929|32.4898|
|60|sequential|80|1.102307|1.095134|12.4408|44.2177|
|60|alternating|80|1.098929|1.094071|6.1224|20.7821|
|100|conventional|120|1.086135|1.067533|9.7819|24.4201|
|100|sequential|120|1.125000|1.097108|2.8286|10.5001|
|100|alternating|120|1.122135|1.099679|2.9524|9.6607|

Higher HV is better. Both calibrations identical; no scoring scale changed. Different budgets use different initial/validation coordinates and different adaptive allocations. Verification sets differ by method. One seed only. See each campaign REPORT.md for complete protocol, errors and limitations.

## Closeout and handoff — 13 November 2026

The user accepts these pilot results as sufficient to move to the new Vernier model. No further SPM tests, seeds or FEA campaigns are requested. This is a research-stage decision, not proof of universal superiority. Both Adaptive methods have higher confirmed archive/verification20 HV than Conventional in these runs. At pool60, Sequential improves mean torque error (12.4408% vs16.5929%) while its worst torque error is higher (44.2177% vs32.4898%); both facts must be reported. Global surrogate accuracy is not established by eight validation points or method-specific verification sets.

The consolidated handoff is [README.md](../../README.md). Preserve old data and configuration. A Vernier campaign must use its own model-specific variables, constraints, fingerprint and dataset; no automatic carryover of SPM training labels, bounds, lengths or J-validation assumptions.
