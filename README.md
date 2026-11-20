# PMSM / Vennet và ghi chú khởi động lại Vernier

## Kết quả Vernier — NSGA-II trực tiếp, ANN tĩnh và Adaptive GGLL

Cập nhật 20/11/2026. NSGA-II trực tiếp (seed 17, population 40) hoàn tất 20 thế hệ với **800 lần gọi Ansys**, gồm **783 kết quả hợp lệ**, 17 lỗi solver và **102 thiết kế Pareto** trong tập kết quả tích lũy. Các cực trị FEA ở mốc 800 là mô-men **11,234 Nm** (điểm 638), PF **0,9265** (điểm 790) và hiệu suất **91,360%** (điểm 784). [Tổng kết NSGA-II](runs/vernier_nsga2_narrow_800_v1/performance.json) · [Pareto FEA 800](runs/vernier_nsga2_narrow_800_v1/pareto.csv)

### Dự đoán trên Pareto cuối và kiểm chứng Ansys

Với ANN tĩnh và Adaptive GGLL, mỗi ô lấy ứng viên có **dự đoán cao nhất cho mục tiêu đó trong 30 thiết kế được chọn từ Pareto dự đoán cuối**, rồi ghi kết quả Ansys của chính thiết kế đó sau mũi tên. Với NSGA-II trực tiếp, mỗi ô là cực trị FEA trong toàn bộ kết quả hợp lệ đến mốc tương ứng. Các hàng có thể thuộc những thiết kế khác nhau.

| Mục tiêu | ANN tĩnh: dự đoán → FEA cùng điểm | Adaptive GGLL: dự đoán → FEA cùng điểm | NSGA-II 300, FEA | NSGA-II 800, FEA |
|---|---:|---:|---:|---:|
| Mô-men (Nm) | 11,235 → 9,006 | 10,372 → 8,798 | 10,431 | 11,234 |
| PF | 0,9688 → 0,9431 | 0,9458 → 0,9460 | 0,8359 | 0,9265 |
| Hiệu suất (%) | 96,914 → 90,196 | 91,633 → 90,960 | 91,148 | 91,360 |

Ví dụ, Adaptive dự đoán điểm 271 đạt mô-men 10,372 Nm và Ansys kiểm chứng được 8,798 Nm. Trong 30 thiết kế cuối của Adaptive, mô-men FEA cao nhất là 9,677 Nm ở điểm 283. Giá trị 9,927 Nm thuộc điểm 249 trong pool trước bước kiểm chứng cuối. [Dữ liệu ANN tĩnh](runs/vernier_static_narrow_300_txt_v3/state.json) · [Dữ liệu Adaptive](runs/vernier_adaptive_narrow_300_txt_v3/state.json) · [Pareto FEA NSGA-II 300](runs/vernier_nsga2_narrow_800_v1/checkpoints/300/pareto.csv)

### Hypervolume theo ngân sách FEA

HV tính trên toàn bộ kết quả FEA hợp lệ tích lũy đến từng mốc, với cùng chuẩn hóa mô-men/10, PF/1, hiệu suất/100 và điểm tham chiếu (0, 0, 0). Mốc 270 lấy pool trước bước kiểm chứng của hai phương pháp surrogate. Mốc 300 tính thêm 30 lượt xác nhận thiết kế cuối. Với NSGA-II, cả hai mốc lấy đúng số lần gọi Ansys đầu tiên.

| Số lần gọi Ansys | ANN tĩnh | Adaptive GGLL | NSGA-II trực tiếp |
|---:|---:|---:|---:|
| 270 | 0,638658 | 0,729911 | **0,738903** |
| 300 | 0,693966 | **0,760458** | 0,744321 |
| 800 | — | — | **0,856902** |

NSGA-II dẫn về HV ở mốc 270. Adaptive dẫn ở cùng ngân sách 300, cao hơn NSGA-II khoảng 2,17%. Trong lượt này, NSGA-II lần đầu đạt mức HV của Adaptive 300 ở lần gọi solver **338**. Đến 800 FEA, HV của NSGA-II cao hơn Adaptive 300 khoảng **12,7%**, với ngân sách 800 so với 300. HV NSGA-II tăng từ 0,852742 ở mốc 700 lên 0,856902 ở mốc 800. Kết quả dựa trên một seed cho mỗi quy trình. [Đối chiếu cùng ngân sách 300](runs/vernier_nsga2_narrow_800_v1/checkpoints/300/comparison.json)

## Vernier NSGA-II trực tiếp — ngân sách 800, báo cáo tại 300

[nsga2_vernier.py](code/nsga2_vernier.py) dùng cùng 13 biến liên tục, bounds,
model nguồn, kfill0,3, ràng buộc hình học và bộ giải FEA với ANN/adaptive.
Bấm Run trong VS Code hoặc chạy:

```powershell
.\.venv\Scripts\python.exe code\nsga2_vernier.py
# Tiếp tục cùng thư mục/cấu hình sau khi dừng:
.\.venv\Scripts\python.exe code\nsga2_vernier.py --resume
# Chỉ kiểm tra bằng dữ liệu giả, không mở Ansys:
.\.venv\Scripts\python.exe code\nsga2_vernier.py --dry-run
```

Mặc định population40, seed17, SBX(prob0,9/eta15), PM(eta20), 5 worker,
800 điểm khác nhau; `--workers`, `--population`, `--budget`, `--seed`,
`--run-dir` cho phép đổi cấu hình. `--generations` là giới hạn dừng sớm tùy chọn;
mặc định chạy đến đủ ngân sách điểm. Điểm khởi tạo dùng LHS lọc khả thi;
offspring vi phạm hình học được lấy lại trong bounds trước FEA. Điểm FEA lỗi
vẫn tiêu một suất và không được chạy bù, giống giao thức ANN/adaptive.
Đếm số suất và số lần thực sự khởi động solver riêng; số lần solver luôn ≤800.

Kết quả thật: `runs/vernier_nsga2_narrow_800_v1/`; dry-run có hậu tố
`_dry_run`. Khi đủ đúng300 suất, chương trình lưu `checkpoints/300/` rồi tiếp
tục800; không chọn lọc GA ở giữa thế hệ nên mốc báo cáo không đổi thuật toán.
Thư mục mốc chứa `results.csv`, `pareto.csv`, `pareto.json`, `performance.json`
và `comparison.json` đối chiếu với các chiến dịch ANN/adaptive300 tương thích.
Ở thư mục gốc có `results.xlsx` (kèm waveform), `results.csv`, Pareto,
`performance.json`, `comparison.json`, `nsga2_summary.json` và checkpoint resume.

So sánh **HV archive FEA hợp lệ** với cùng scale10 Nm/1 PF/100% và
reference(0,0,0); số Pareto và cực trị từng mục tiêu được báo riêng. So sánh
300 với300 cần kiểm tra `actual_solver_calls` bằng nhau; nếu có lỗi trước solve,
300 suất có thể chưa phải300 lần solver. NSGA-II800 so với ANN/adaptive300 là
đối chiếu chất lượng theo ngân sách khác nhau. Các cực trị từng mục tiêu có thể
thuộc các thiết kế khác nhau. Không dùng sai số dự đoán ANN để chấm NSGA-II.

Cập nhật: 18/11/2026.

## So sánh FEA thật — ANN tĩnh300 và adaptive GGLL300

Đã hoàn tất cả hai chiến dịch seed17, mỗi bên **300 FEA cho300 điểm khác nhau**, không bù lỗi, không lặp điểm. Trong cặp thử này, **adaptive đạt HV archive cao hơn9,58%** và dự đoán Torque tại các ứng viên cuối chính xác hơn rõ rệt; ANN tĩnh có ít lỗi FEA hơn. Đây là kết quả một seed, chưa chứng minh ưu thế trên mọi lần chạy.

### Điều kiện so sánh và dữ liệu thực tế

Hai bên cùng model nguồn, miền13 biến hẹp, điều kiện FEA, ANN Tanh32×32, Adam lr0,003 cố định, weight decay0, không scheduler,500 epochs, checkpoint vòng300–500, CV5, Final Merge lấy epoch500 và NSGA-II population100/generations100. Đã đối chiếu cấu hình lưu và checksum các module: không có khác biệt ngoài phương pháp và phân bổ các bước.

- ANN tĩnh:270 DOE toàn miền →207 Train/59 Val hợp lệ → CV5 trên266 điểm → Final Merge266 → NSGA-II →30 FEA cuối.
- Adaptive: Initial90 →G1→G2→L1→L2, có verification giữa vòng →204 Train/57 Val hợp lệ → CV5 trên261 điểm → Final Merge261 → NSGA-II →30 FEA cuối.
- Hai bên cùng seed17 nhưng không dùng chung Initial:270 DOE tĩnh được tạo riêng, không phải90 Initial adaptive cộng thêm180 điểm. Final30 của mỗi bên cũng khác nhau.

| Chỉ tiêu | ANN tĩnh | Adaptive GGLL |
|---|---:|---:|
| FEA thực sự đã gọi | 300 | 300 |
| Điểm hợp lệ | 296 (98,67%) | 291 (97%) |
| Điểm lỗi | 4 (1,33%) | 9 (3%) |
| Train hợp lệ trước gộp | 207 | 204 |
| Val hợp lệ | 59 | 57 |
| Điểm dùng CV và train gộp | 266 | 261 |
| Final30 hợp lệ | 30/30 | 30/30 |

ANN tĩnh có3 lỗi `TAU: Surface Mesh Generation Failed` tại điểm47,180,203 và1 lỗi `Edge is not preserved in the mesh!` tại điểm150. Không có lỗi final30. Mạng trước gộp chọn epoch499; mạng gộp học266 điểm đủ500 epochs và lấy epoch500. Không dùng final30 trong fit/scaler/CV; mỗi điểm pool được giữ ngoài train đúng một fold CV.

### Sai số final30

| Đại lượng | ANN tĩnh MAE | Adaptive MAE | ANN tĩnh MAPE (%) | Adaptive MAPE (%) | ANN tĩnh R² | Adaptive R² |
|---|---:|---:|---:|---:|---:|---:|
| Torque (Nm) | 3,5136 | 0,3488 | 81,468 | 4,998 | −2,1313 | 0,9401 |
| PF | 0,03409 | 0,02906 | 4,593 | 4,120 | 0,8137 | 0,9126 |
| Efficiency (điểm phần trăm) | 5,9720 | 0,4361 | 6,660 | 0,484 | −332,5567 | 0,5807 |

| ANN tĩnh, final30 | RMSE | Bias (ANN − FEA) | Sai số tuyệt đối lớn nhất |
|---|---:|---:|---:|
| Torque (Nm) | 3,6039 | +3,5136 | 4,7420 |
| PF | 0,04586 | +0,03067 | 0,09439 |
| Efficiency (điểm phần trăm) | 6,0103 | +5,9720 | 6,9901 |

ANN tĩnh dự đoán Torque và Efficiency cao hơn FEA ở **30/30 điểm**; PF cao hơn ở23/30 điểm. Efficiency dự đoán94,0707–96,9136% nhưng FEA chỉ89,0652–90,2655%. Torque dự đoán4,6926–11,2348 Nm, FEA2,6405–9,0062 Nm. Mức giảm Torque MAE90,07% của adaptive trên hai bộ final riêng là số mô tả, không phải so hai mạng trên cùng điểm.

### Val/CV khá ổn nhưng không dự báo được sai số ở vùng tối ưu của ANN tĩnh

| Đại lượng | Val MAE, tĩnh / adaptive | CV5 MAE tĩnh: trung bình ± SD | CV5 MAE adaptive: trung bình ± SD |
|---|---:|---:|---:|
| Torque (Nm) | 0,4403 /0,4028 | 0,4910 ±0,0657 | 0,5091 ±0,0358 |
| PF | 0,02973 /0,02586 | 0,02702 ±0,00466 | 0,03110 ±0,00394 |
| Efficiency (điểm phần trăm) | 1,1393 /0,6759 | 1,1330 ±0,1049 | 0,9507 ±0,1233 |

CV của mỗi bên đánh giá trên kho riêng, nên không kết luận mạng tĩnh tốt hơn mạng adaptive chỉ từ Torque CV MAE0,491 so với0,509. Val/CV trên DOE không bảo đảm dự đoán chính xác ở các ứng viên cực trị do tối ưu chọn. Sự chênh lệch giữa CV và final của ANN tĩnh phù hợp với khả năng NSGA-II chọn vào vùng mạng đánh giá quá cao; chưa xác định đây là nguyên nhân duy nhất.

### Kiểm tra bổ sung hậu nghiệm trên cùng điểm FEA

Không train lại hoặc gọi thêm FEA. Nạp checkpoint và scaler đã lưu, cho cả hai mạng cuối dự đoán lại từng bộ final. Kiểm tra cả60 điểm không thuộc pool train của bất kỳ mạng nào, tại độ làm tròn8 chữ số đang dùng để nhận dạng điểm.

| Mạng cuối | Torque MAE trên30 điểm final tĩnh (Nm) | Torque MAE trên30 điểm final adaptive (Nm) |
|---|---:|---:|
| ANN tĩnh | 3,5136 | 0,9554 |
| Adaptive | 0,3954 | 0,3488 |

Trên cùng30 điểm final tĩnh, Efficiency MAE của hai mạng lần lượt5,9720 và0,5402 điểm phần trăm; PF MAE0,03409 và0,06348, tức adaptive không tốt hơn ở mọi đầu ra của tập kiểm tra này. Kết quả hỗ trợ lợi thế dự đoán Torque/Efficiency của mạng adaptive ngoài sự khác nhau giữa hai bộ final, nhưng đây là đánh giá hậu nghiệm trên các ứng viên tối ưu, không phải test ngẫu nhiên toàn miền.

Mạng tĩnh trước Final Merge đã có Torque MAE3,6789 Nm, Efficiency MAE5,0409 điểm phần trăm trên chính30 điểm final tĩnh. Lỗi lớn vì vậy đã tồn tại trước gộp; không thể quy toàn bộ cho Final Merge.

Đối chiếu độc lập: dự đoán từ checkpoint/scaler khớp chính xác dự đoán đã đóng băng; giá trị13 biến thực sự áp dụng trong FEA khớp từng điểm yêu cầu; không phát hiện ghép sai điểm hoặc lọt final vào train/CV. Khoảng cách Euclid chuẩn hóa13 biến đến điểm pool gần nhất có trung vị1,2370 cho final tĩnh,0,8211 cho final adaptive. Đây là dấu hiệu phụ về độ gần dữ liệu, không phải phép chứng minh nội suy/ngoại suy theo bao lồi.

### So sánh HV trên cùng thang

Chuẩn hóa Torque/10, PF/1, Efficiency/100; reference(0,0,0); chỉ dùng FEA hợp lệ. Đã tính lại HV từ dữ liệu từng điểm và khớp báo cáo.

| HV | ANN tĩnh | Adaptive | Adaptive cao hơn tĩnh |
|---|---:|---:|---:|
| Pool trước final,270 lượt | 0,638658 | 0,729911 | 14,29% |
| Final30 riêng | 0,681142 | 0,747391 | 9,73% |
| Archive toàn bộ300 lượt | 0,693966 | 0,760458 | 9,58% |

ANN tĩnh vẫn tìm được nghiệm có ích: final30 nâng HV archive từ0,638658 lên0,693966. Kho tĩnh có22 nghiệm Pareto FEA (17 từ final), adaptive có19 (15 từ final); nhiều điểm Pareto hơn không đồng nghĩa HV lớn hơn. Hai archive gồm số điểm hợp lệ khác nhau nhưng có cùng ngân sách300 FEA.

**Nhận định:** trong cặp thực nghiệm hiện có, adaptive tạo archive FEA có HV cao hơn và khắc phục phần lớn sai số Torque/Efficiency tại các ứng viên tối ưu mà baseline tĩnh gặp phải. Kết quả ủng hộ việc bổ sung FEA theo vùng tìm kiếm. Chưa đủ nhiều seed để kết luận ưu thế ổn định; chưa tách riêng tác dụng của chiến lược DOE, verification giữa vòng và dữ liệu thích nghi.

**Kiểm tra optimizer trên dữ liệu đã lưu:** huấn luyện lại trên 266 điểm hợp lệ của ANN tĩnh và 261 điểm hợp lệ của adaptive, chấm trên 30 thiết kế cuối đã kiểm chứng của từng lượt, qua 5 seed. Weight decay `1e-4` chỉ làm MAE thay đổi nhẹ. Cosine Annealing giảm MAE mô-men của ANN tĩnh từ 3,171 xuống 3,002 Nm nhưng tăng sai số PF và hiệu suất. Trong adaptive, cosine tăng MAE cả ba mục tiêu. Giữ cấu hình Adam với learning rate cố định 0,003 cho hai quy trình. Phép thử dùng lại dữ liệu FEA và chỉ đánh giá sai số trên các thiết kế đã chọn. [Kết quả theo seed và thiết kế](inspection/vernier_optimizer_offline_final30.json)

**Nguồn ANN tĩnh:** [tổng kết](runs/vernier_static_narrow_300_txt_v3/campaign_summary.json), [Val trước gộp](runs/vernier_static_narrow_300_txt_v3/validation_before_merge.json), [CV5](runs/vernier_static_narrow_300_txt_v3/cv_report.json), [kết quả từng điểm](runs/vernier_static_narrow_300_txt_v3/campaign_results.csv), [Pareto FEA](runs/vernier_static_narrow_300_txt_v3/fea_pareto.json), [trạng thái](runs/vernier_static_narrow_300_txt_v3/state.json), [mạng cuối và scaler](runs/vernier_static_narrow_300_txt_v3/models/merged/), [mạng trước gộp](runs/vernier_static_narrow_300_txt_v3/models/Initial/). Nguồn adaptive được liên kết trong phần chi tiết ngay dưới.

## Kết quả FEA thật — Vernier GGLL300, hoàn tất 18/11/2026

Một chiến dịch seed17 đã hoàn tất **300 FEA cho300 điểm khác nhau**, không bù lỗi và không chạy lặp Initial sau sửa lỗi resume. Bắt đầu21:46:04 ngày17/11, kết thúc02:08:08 ngày18/11/2026 (UTC+7; thời gian này gồm khoảng dừng để sửa resume). Đây là kết quả động cơ thật, không phải dry-run.

**Cấu hình thực sự sử dụng:** ANN chung Tanh32×32, Adam learning rate cố định0,003, weight decay0, không scheduler; mỗi lần train đủ500 epochs, chọn checkpoint vòng trong epoch300–500. NSGA-II population100/generations100. Miền13 biến hẹp, kfill0,3, J≤5,5 A/mm², torque>0. Initial không verify P0 trước G1; mỗi vòng DOE → FEA → train → Pareto → verify5. Val hợp lệ tham gia dẫn hướng nhưng không cập nhật trọng số trong các vòng.

### Ngân sách, dữ liệu và lỗi

| Tập | Định mức | Hợp lệ | Lỗi |
|---|---:|---:|---:|
| Train, gồm verification giữa vòng | 210 | 204 | 6 |
| Val | 60 | 57 | 3 |
| Final30 | 30 | 30 | 0 |
| **Tổng** | **300** | **291 (97%)** | **9 (3%)** |

- 6 lỗi tạo lưới `TAU: Surface Mesh Generation Failed`: điểm54,88,94,98,238,242.
- 3 lỗi chồng hình giữa `coil_out_1` và `Stator_out`: điểm78,124,266.
- Theo bước: Initial3 lỗi; DOE G1 có3; DOE L2 có2; verify L2 có1; các bước khác không lỗi. Final30 thành công30/30.
- L2 fit trên200 Train/57 Val. Sau4 verification L2 hợp lệ, kho có204 Train +57 Val; CV và Final Merge dùng261 điểm. Vai trò được gán trước FEA nên tỷ lệ hợp lệ không được chia lại thành đúng7/9–2/9.

### Sai số trên final30

| Đại lượng | MAE | RMSE | MAPE (%) | R² | Bias (ANN − FEA) |
|---|---:|---:|---:|---:|---:|
| Torque (Nm) | 0,3488 | 0,4556 | 4,998 | 0,9401 | +0,1667 |
| PF | 0,02906 | 0,03333 | 4,120 | 0,9126 | −0,02277 |
| Efficiency (điểm phần trăm) | 0,4361 | 0,5505 | 0,484 | 0,5807 | +0,0042 |

- Điểm271 sai Torque lớn nhất: ANN10,3719 Nm, FEA8,7977 Nm, lệch1,5742 Nm (17,89%). ANN dự đoán Torque cao hơn FEA ở18/30 điểm.
- PF bị dự đoán thấp ở26/30 điểm. Efficiency sai lớn nhất1,3305 điểm phần trăm; R²0,5807 cần đọc cùng khoảng FEA hẹp86,9909–91,2246%.
- Final30 là ứng viên được tối ưu chọn, không phải test ngẫu nhiên toàn miền. Chúng không tham gia train, scaler hoặc CV; đối chiếu ID không phát hiện giao nhau.

### Val trước Final Merge và 5-Fold CV

Val dưới đây dùng mạng L2 trước gộp. CV dùng261 điểm hợp lệ, mỗi điểm được giữ ngoài train đúng một fold, scaler riêng từng fold, lấy trọng số epoch500. SD là độ lệch chuẩn mẫu giữa5 folds, không phải giữa5 chiến dịch adaptive độc lập.

| Đại lượng | Val57: MAE | Val57: R² | CV5: MAE trung bình ± SD | CV5: MAPE trung bình ± SD (%) | CV5: R² trung bình ± SD |
|---|---:|---:|---:|---:|---:|
| Torque (Nm) | 0,4028 | 0,9038 | 0,5091 ±0,0358 | 9,9530 ±0,5197 | 0,8516 ±0,0317 |
| PF | 0,02586 | 0,9537 | 0,03110 ±0,00394 | 5,9122 ±0,9719 | 0,9308 ±0,0282 |
| Efficiency (điểm phần trăm) | 0,6759 | 0,8906 | 0,9507 ±0,1233 | 1,1226 ±0,1613 | 0,7525 ±0,0792 |

Val tham gia chọn checkpoint và dẫn hướng nên là validation nội bộ. CV cũng đánh giá trên kho được lấy mẫu thích nghi; không chứng minh độ chính xác trên toàn miền13 biến.

### Diễn biến qua các vòng

| Mạng | Train / Val thực tế | Epoch chọn | Verification hợp lệ | Torque MAE verification (Nm) |
|---|---:|---:|---:|---:|
| Initial | 67 /20 | 390 | — | — |
| G1 | 96 /28 | 491 | 5 | 3,8276 |
| G2 | 131 /38 | 406 | 5 | 2,5097 |
| L1 | 166 /48 | 376 | 5 | 1,9973 |
| L2 | 200 /57 | 499 | 4 | 1,0544 |
| Final Merge → final30 | 261 /0 | 500 | 30 | 0,3488 |

Ở G1 và G2, cả5 điểm verification đều bị dự đoán cao hơn FEA về Torque, PF và Efficiency. Sai số cuối thấp hơn rõ rệt nhưng các nhóm verification khác nhau về điểm và kích thước; chưa thể quy mức giảm cho riêng Val, checkpoint, Final Merge hoặc một vòng adaptive.

### HV và Pareto từ FEA thật

HV chỉ tính FEA hợp lệ, chuẩn hóa Torque/10, PF/1, Efficiency/100, reference(0,0,0). Tất cả mốc trong bảng dùng cùng thang.

| Mốc | HV archive tích lũy |
|---|---:|
| Sau Initial | 0,545178 |
| Sau G1 và verify | 0,618801 |
| Sau G2 và verify | 0,668870 |
| Sau L1 và verify | 0,703343 |
| Sau L2 và verify (pool270) | 0,729911 |
| Sau final30 (tổng300) | 0,760458 |

- HV final30 riêng: **0,747391**. Thêm final30 làm HV archive tăng **4,19%** so với pool trước final.
- Kho cuối có19 nghiệm Pareto FEA: 15 từ final30, 2 từ DOE L2, 1 từ verify L2, 1 từ DOE L1. Không phải cả30 điểm Pareto ANN vẫn là Pareto khi thay bằng FEA.
- HV tăng39,49% so với Initial, nhưng số FEA cũng tăng; riêng mức tăng này không chứng minh ưu thế so với baseline. Baseline tĩnh300 đã hoàn tất và được so sánh riêng ở đầu README. Không so trực tiếp HV này với HV Vernier cũ dùng calibration khác hoặc với PMSM.

| Điểm final đại diện | ID | Torque (Nm) | PF | Efficiency (%) |
|---|---:|---:|---:|---:|
| Torque lớn nhất trong final30 | 283 | 9,6767 | 0,56771 | 89,0185 |
| PF lớn nhất trong final30 | 272 | 3,1208 | 0,94605 | 90,2601 |
| Efficiency lớn nhất trong final30 | 285 | 6,3470 | 0,82576 | 91,2246 |

### Nhận định và điểm cần chuyên gia xem

- Final30 đạt Torque MAE0,3488 Nm, thấp hơn con số lịch sử1,0473 Nm trong bài học bên dưới. Tuy nhiên, tập kiểm tra30 điểm mới khác40 điểm cũ, dữ liệu train và ngân sách cũng khác: đây không phải đối chứng để định lượng tác dụng từng sửa đổi.
- Cần đánh giá việc khoanh G1 từ Pareto P0 chưa được verify, khi verification G1/G2 đang quá lạc quan; cơ chế dùng Val thật chung với dự đoán để dẫn hướng; và việc dùng CV trên kho thích nghi.
- Kết quả ANN tĩnh 300, NSGA-II trực tiếp và phép thử optimizer trên dữ liệu đã lưu được trình bày ở đầu README. Các chiến dịch FEA dùng một seed cho mỗi quy trình.
- Lỗi resume từng phát sinh khi JSON đổi tuple bounds thành list. Đã sửa phép so sánh, sao lưu và cập nhật fingerprint tương thích;90 kết quả Initial/model/kế hoạch G1 được giữ. Kiểm tra cuối có300 attempts cho300 điểm, không lặp điểm.

**Dữ liệu đối chiếu:** [tổng kết chiến dịch](runs/vernier_adaptive_narrow_300_txt_v3/campaign_summary.json), [Val trước gộp](runs/vernier_adaptive_narrow_300_txt_v3/validation_before_merge.json), [CV5](runs/vernier_adaptive_narrow_300_txt_v3/cv_report.json), [verification từng vòng](runs/vernier_adaptive_narrow_300_txt_v3/verification_reports.json), [kết quả từng điểm](runs/vernier_adaptive_narrow_300_txt_v3/campaign_results.csv), [Pareto FEA](runs/vernier_adaptive_narrow_300_txt_v3/fea_pareto.json), [trạng thái các vòng](runs/vernier_adaptive_narrow_300_txt_v3/state.json), [prediction ngoài fold](runs/vernier_adaptive_narrow_300_txt_v3/cv5/oof_predictions.csv). Checkpoint và đường học nằm trong `runs/vernier_adaptive_narrow_300_txt_v3/models/`.

## Quy chuẩn chạy Vernier mới — 70/20/10, không bù lỗi

Entry FEA: [run_vernier_adaptive_ggll.py](code/run_vernier_adaptive_ggll.py) và [run_vernier_ann.py](code/run_vernier_ann.py). Người dùng tự bấm Run trong VSCode; import không mở Ansys. Mặc định300 lượt đánh giá thiết kế, **210 Train (gồm20 verification) +60 Val +30 Test**. Solver calls thực đếm riêng, không vượt300; lỗi trước solve không được ghi thành solver call. Mọi điểm lỗi tiêu thụ slot của mình, không bù hoặc tự retry. Vai trò Train/Val đóng băng trước FEA; điểm lỗi không chuyển vai để làm đẹp tỷ lệ.

Model clone lấy đúng tại `inspection/vernier_pilot_20261113/work/test_point/base_half.aedt`, năm worker riêng. Miền13 biến khóa theo [Vernier_Model_Constraints.txt](Vernier_Model_Constraints.txt); kfill0,3, J≤5,5 A/mm², torque trung bình>0. Không dùng lại các kết quả chiến dịch cũ.

**TXT gốc là chuẩn thuật toán.** Trong mỗi vòng G/L: Pareto dẫn hướng → rải DOE → FEA → gộp Train → train ANN → NSGA-II → verify5 (ba cực trị+maximin) → hiệu chỉnh Pareto dẫn hướng cho vòng tiếp theo. Không train ngay sau verify; các điểm verify được học ở lần train kế tiếp. Initial không có verify5 riêng. Sau verify5 của L2 mới báo cáo/CV/Final Merge. Giữ cách hiệu chỉnh cũ: thay dự đoán tại các điểm vừa verify bằng FEA thật, loại điểm verify lỗi, lọc lại Pareto; bổ sung các điểm Val hợp lệ vào dẫn hướng theo yêu cầu mới. Không tự đưa toàn bộ DOE Train lịch sử vào dẫn hướng. Archive báo cáo/HV vẫn dùng mọi FEA hợp lệ; điểm chưa kiểm chứng vẫn là dự đoán.

| Giai đoạn | Verify sau ANN/Pareto, thuộc Train | DOE: Train / Val | ANN fit trên Train lũy kế | Val lũy kế |
|---|---:|---:|---:|---:|
| Initial | 0 | 70 /20 | 70 | 20 |
| G1 | 5 | 30 /10 | 100 | 30 |
| G2 | 5 | 30 /10 | 135 | 40 |
| L1 | 5 | 30 /10 | 170 | 50 |
| L2 | 5 | 30 /10 | 205 | 60 |

Các mốc trên áp dụng khi không lỗi. Sau mỗi verify, kho Train lần lượt105/140/175/210, nhưng chỉ được fit ở vòng sau. Sau L2:205 đã fit +5 verify L2 +60 Val =270 để lưu báo cáo Val trước gộp →5-Fold offline → Final Merge → tìm30 ứng viên Pareto mới → FEA final30. Final30 không bao giờ vào train/CV/scaler. Baseline tĩnh dùng270 LHS (210 Train/60 Val), rồi cùng quy trình Val/CV/Merge/final30. Với222/111, định mức lần lượt156/44/22 và78/22/11, phân bổ vòng bằng quy tắc phần dư lớn nhất; verification vẫn5 mỗi vòng. Budget quá nhỏ dừng rõ, không tự thay thuật toán.

ANN chung Tanh32×32, input chuẩn hóa theo bounds, từng output chuẩn hóa chỉ trên Train. Adam với learning rate **cố định0,003**, **không weight decay, không scheduler**. Luôn chạy đủ500 epochs; mô hình vòng chỉ chọn checkpoint có Val loss thấp nhất trong **epoch300–500**. Final Merge lấy thẳng epoch500; không dùng logic8 validation. Val là validation nội bộ vì tham gia chọn checkpoint/dẫn hướng, không phải test độc lập toàn miền.

5-Fold dùng scaler riêng trong từng fold, train500 epochs và lấy epoch500; fold đánh giá không chọn checkpoint. Lưu MAE/RMSE/MAPE/R²/Bias từng fold, trung bình±sample SD và prediction ngoài fold. Báo cáo Val trước Merge được giữ riêng. Final30 là kiểm chứng ứng viên tối ưu, không phải mẫu test ngẫu nhiên toàn miền. Huấn luyện mới chưa được gán kết quả chính xác của phép thử lịch sử.

G lấy min–max của Pareto dẫn hướng, padding0; L chia tối đa4 nhóm mục tiêu và dùng các hộp padding1% bounds. Khôi phục cách lấy mẫu của runner GGLL miền hẹp220 đã xóa (blob `733602e`, ANN `4ff5076`, model `ad15562`): Initial dùng LHS lọc khả thi như `make_plan`; G/L tạo nhóm32 điểm với seed riêng cho từng điểm được chọn, luân phiên các hộp L, làm tròn8 chữ số. Khởi tạo quần thể NSGA-II dùng lại offset seed+101. Đây không phải một LHS duy nhất cho cả DOE; lọc giải tích/điểm trùng diễn ra trước FEA và không tạo lượt FEA bù. Không exploration hoặc fallback ngoài vùng. NSGA-II mặc định population100/generations100/seed17, tìm toàn bounds miền hẹp; không lấy điểm bị trội để lấp thiếu Pareto. Thiếu ứng viên mới/dữ liệu hợp lệ thì dừng, không phát sinh FEA thay thế.

HV dùng cùng scale cố định **10 Nm /1 PF /100% eff**, reference(0,0,0), chỉ từ kết quả hợp lệ; không dùng calibration Direct đã xóa. Báo riêng pool, final và archive. Đây là thang báo cáo chốt trước FEA, không phải cực trị vật lý. Dữ liệu, vai trò, prediction, checkpoint và cấu hình được khóa để resume; không chạy hai runner dùng chung worker pool cùng lúc.

Dry-run không gọi Ansys, kết quả ghi nhãn synthetic và nằm trong thư mục riêng:

```powershell
.\.venv\Scripts\python.exe code\run_vernier_adaptive_ggll.py --dry-run
.\.venv\Scripts\python.exe code\run_vernier_ann.py --dry-run
```

Kết quả thật mặc định: `runs/vernier_adaptive_narrow_300_txt_v3/` hoặc `runs/vernier_static_narrow_300_txt_v3/`. Bản khôi phục cách rải DOE cũ dùng thư mục riêng, không trộn các dry-run phiên bản trước. Các file chính: `campaign_results.csv` có phase/role/status, `results.xlsx` chứa kết quả+waveform, `state.json`, `models/`, `validation_before_merge.json`, `cv_report.json`, `cv5/oof_predictions.csv`, `campaign_summary.json`, `fea_pareto.json`. Lưu lỗi và actual solver calls đầy đủ; không coi HV dry-run là kết quả động cơ.

**Tài liệu thuật toán gốc:** [Vernier_ANN_Workflow_Intermag2027.txt](Vernier_ANN_Workflow_Intermag2027.txt), đã khôi phục nguyên bản từ Git. Đây là workflow nghiên cứu V1; các đề xuất mới về train/validation/ngân sách chưa tự động thay đổi cơ chế Global/Local và verification trong tài liệu này.

Theo yêu cầu người dùng, đã gỡ code và kết quả chạy Vernier phiên bản cũ. Phần trên là code được xây dựng lại theo giao thức mới; không dùng các lượt cũ làm baseline. Code, cấu hình, dữ liệu và kết quả PMSM/Vennet được giữ nguyên.

## Bài học chính từ Vernier

Các số dưới đây là tóm tắt lịch sử để rút kinh nghiệm; file kết quả và checkpoint tương ứng đã được xóa theo yêu cầu, không còn là bộ dữ liệu tái lập trong workspace.

- Không bê nguyên số điểm validation và cách chọn checkpoint từ PMSM sang một bài toán khác mà chưa kiểm tra tính đại diện của split, learning curve và độ ổn định giữa seed. Với miền hẹp, code chạy đủ500 epochs nhưng khôi phục checkpoint epoch25 theo loss trên8 validation; không phải dừng train ở epoch25.
- Trước khi tăng mẫu FEA hoặc kết luận ANN thiếu dữ liệu, phải kiểm tra offline trên dữ liệu sẵn có. Giữ nguyên189 điểm fit, mạng chung và seed17, chỉ đổi checkpoint đã giảm torque MAE trên40 điểm kiểm tra hậu nghiệm từ1,0473 xuống0,3993 Nm.

| Kết quả chẩn đoán cần nhớ | Torque MAE trên40 điểm |
|---|---:|
| Checkpoint cũ epoch25, seed17 | 1,0473 Nm |
| Cùng mạng/dữ liệu/seed, lấy epoch500 | 0,3993 Nm |
| Gói ba mạng riêng64×64, train197,1000 epochs, weight decay0,0001 | Trung bình0,2864 ± 0,0326 Nm qua3 seed |

- Tách mạng không tự động tốt hơn: trung bình ba seed, mạng chung lấy epoch500 đạt0,3136 Nm; ba mạng riêng32×32 đạt0,3749 Nm. Gói64×64 thay nhiều yếu tố cùng lúc, nên không quy toàn bộ cải thiện cho tách mạng.
- Bộ40 điểm đã được xem và dùng hình thành đề xuất; đây là hậu kiểm thăm dò, không phải test độc lập để chốt bài báo. Chọn seed/epoch theo bộ này rồi báo lại như test độc lập sẽ làm kết luận thiếu tin cậy.
- Tìm trong hộp local không bảo đảm nội suy: các tổ hợp biến vẫn có thể ngoài bao lồi hoặc ở vùng dữ liệu thưa. Giảm sai số trên một nhóm điểm cũng không tự bảo đảm tăng HV/Pareto. Thử offline không tạo HV FEA mới.
- Các lỗi mesh cần tách khỏi vi phạm vận hành và sai số mô hình học. Chưa xác định nguyên nhân thì không quy chung cho thiếu mẫu, phi tuyến hay bản thân ý tưởng nghiên cứu.
- Mặc định chỉ sửa và kiểm tra code; người dùng tự bấm Run trong VSCode. Chỉ khởi chạy mô phỏng khi người dùng yêu cầu rõ ràng.

## Model và dữ kiện vật lý giữ lại cho Vernier

Model half đã về đúng vị trí nguồn `inspection/vernier_pilot_20261113/work/test_point/base_half.aedt`, checksum nguyên bản; không giữ bản thay thế trong `Verinier Ansys`. Các model backup `base.aedt`, `base_half_main.aedt`, bản `.aedt.txt`, hai file ghi lệnh Ansys trong [Verinier Ansys](<Verinier Ansys>) và [ràng buộc hình học, miền biến mới](Vernier_Model_Constraints.txt) được giữ lại. Không sửa model nguồn khi campaign đang chạy.

## PMSM / Vennet — giữ nguyên

SPM 18 slots/4 poles, J7 A/mm², 1500 rpm, seed17. Đã kết thúc; không chạy thêm SPM, không dùng dữ liệu SPM train Vernier, không so raw HV hai động cơ.

| Pool | Phương pháp | HV archive | HV final20 | Torque MAPE (%) |
|---:|---|---:|---:|---:|
| 60 | Conventional | 1,050064 | 0,994969 | 16,5929 |
| 60 | Sequential GGLL | 1,102307 | 1,095134 | 12,4408 |
| 60 | Alternating GLGL | 1,098929 | 1,094071 | 6,1224 |
| 100 | Conventional | 1,086135 | 1,067533 | 9,7819 |
| 100 | Sequential GGLL | 1,125000 | 1,097108 | 2,8286 |
| 100 | Alternating GLGL | 1,122135 | 1,099679 | 2,9524 |

SPM Direct800 HV1,147174. Mọi final20 của bảng SPM đều hợp lệ. Pool60 fit52/validation8; pool100 fit92/validation8. Calibration riêng tại [spm_hv_calibration.json](data/spm_hv_calibration.json), initial riêng tại `data/spm_initial20/`, `data/spm_initial40/`. Kết quả hỗ trợ tính khả thi trên testbed đơn giản; không chứng minh hiệu quả trên Vernier hoặc nhiều seed.
