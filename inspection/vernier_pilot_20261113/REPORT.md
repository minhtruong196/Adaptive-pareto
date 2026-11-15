# Vernier pilot ? 13 November 2026

Baseline and five distinct parameter variations completed successfully after the one-time CylindricalGap1 cleanup. Five separate projects were launched nonblocking in the same AEDT session; native solver profiles confirm overlapping execution.

| Case | Torque (Nm) | PF | Efficiency (%) | I RMS (A) | J in | J out | Solve wall time (s) |
|---|---:|---:|---:|---:|---:|---:|---:|
| baseline | 9.612713 | 0.352323 | 86.409502 | 11.530735 | 5.500000 | 4.656102 | 145.915759 |
| inner_width_low | 7.780245 | 0.327189 | 83.141369 | 12.861144 | 5.500000 | 5.193321 | 357.559335 |
| outer_width_low | 7.085186 | 0.358518 | 85.211454 | 11.530735 | 5.500000 | 3.782593 | 343.341397 |
| inner_width_high | 8.760962 | 0.393922 | 87.723927 | 9.918799 | 5.500000 | 4.005204 | 327.128954 |
| outer_width_high | 9.233112 | 0.380047 | 86.814803 | 10.592543 | 5.052495 | 5.500000 | 343.793472 |
| coupled_geometry | 4.962262 | 0.349900 | 84.989741 | 7.693834 | 5.500000 | 3.194037 | 395.020013 |

Five varied cases: slot_thickin=3 and 12 mm; slot_thickout=5 and 28 mm; one combined geometry case. Other parameters and actual areas/currents are retained in the SQLite ledger and workbook.

- kfill=0.4; a common RMS current is recomputed from actual coil areas; both current densities are at most 5.5 A/mm2.
- All three objectives use the last electrical cycle, [1/fs, 2/fs], with fs=210 Hz. Efficiency is the time mean of the existing eff(t), including the 2% excess-loss allowance.
- Waveforms are read directly in SI. The raw PF report uses a full-window aggregate; the objective PF is recomputed on the last-cycle window.
- Voltage is recorded and does not constrain this performance pilot.
- 8 solver calls in the ledger: six successes and two earlier failed mesh attempts before the cleanup. Failures remain recorded, without fabricated objectives.
- Source base.aedt SHA256: 55000c80389f490c850ca2cad64fb2811f9aad542ba5a7df84fc365d54317163. Source file preserved.
- This validates the tested points and parallel execution, not mesh/time-step convergence, the entire proposed domain, or ANN accuracy.

Outputs: [single workbook](../../outputs/vernier_pilot_20261113/vernier_pilot.xlsx), evaluations.sqlite (authoritative ledger), solver files under ignored work/.
