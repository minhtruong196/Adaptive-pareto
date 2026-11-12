# Motor-CAD: Exploratory DoE và Direct NSGA-II

**File chạy tối ưu chính hiện tại: `nsga2_motorcad.py`**, cấu hình `nsga2_config.json`. Thuật toán pymoo NSGA-II nằm trong file này. `motorcad_optimize.py` giữ phần kết nối, cache và công cụ hỗ trợ DoE/check/analyze; `test_motorcad_optimize.py` chỉ kiểm thử offline.

## NSGA-II riêng: chiều dài cố định 100 mm, một license

**Chạy bằng nút ▶ Run của VS Code:** lưu/đóng Motor-CAD đang mở, mở `nsga2_motorcad.py` rồi chọn Run Python File. Không cần nhập lệnh hoặc tham số. Mỗi lần bấm Run sẽ tạo thư mục mới `runs/nsga2_L100_<ngày_giờ_KST>_<mã>` và bắt đầu tối ưu thật. Đường dẫn hiện trong vùng Output/Terminal của VS Code. File tự dùng Python `.venv` nếu VS Code đang chọn nhầm interpreter; cũng đã thêm cấu hình Run and Debug tên `Run NSGA-II (one hour)`. Không mở đồng thời nhiều lượt Run; khóa một phiên vẫn được áp dụng. Import module không chạy mô phỏng, nhưng thực thi file không tham số hiện đã chủ động chạy NSGA-II theo yêu cầu mới.

**Thiết lập mặc định mới cho một lượt khoảng một giờ:** population 24, generations 7, budget tối đa 168 lượt EMag, seed 17, `--max-minutes 55`. Đã qua 25 kiểm thử offline, gồm dừng theo thời gian và resume. Theo duy nhất một điểm đo cũ 20.343 giây/lượt, 168 lượt tương đương khoảng 57 phút; đây là ước tính, chưa đo trên cấu hình 100 mm. Mốc 55 phút tính cả khởi động trong lần gọi hiện tại: ngừng bắt đầu FEA mới, hoàn tất FEA đang chạy rồi lưu Pareto/checkpoint. Không cưỡng bức cắt solver nên không phải cam kết thời hạn cứng; một FEA bất thường có thể kéo dài hơn.

Lệnh dùng toàn bộ thiết lập trên:

```powershell
.\.venv\Scripts\python.exe nsga2_motorcad.py --run-dir runs/nsga2_L100_1h
```

Đây là một lượt tối ưu trực tiếp theo ngân sách thời gian, không tự khởi chạy các đợt test/DoE hay nhiều seed. Số lượt/thế hệ không chứng minh hội tụ. Các tham số có thể ghi đè trên CLI; khi dùng những ví dụ ngân sách lớn bên dưới, nhớ tăng `--max-minutes` nếu muốn chạy lâu hơn 55 phút. Resume giữ đúng population/generations/seed, giới hạn thời gian áp dụng lại cho từng lần gọi.

Theo yêu cầu mới, chọn `Stator_Lam_Length = Rotor_Lam_Length = Magnet_Length = 100 mm`. Giữ đường kính stator 129.772 mm. Chỉ áp dụng trên bản sao; `Basic_Model.mot` giữ nguyên. Ba chiều dài được đặt và kiểm tra lại sau mỗi lần load, không phải biến tối ưu. Fingerprint mới tách kết quả này khỏi lần smoke 8.70 Nm trước đây.

```powershell
# Chỉ xem trợ giúp, không FEA:
.\.venv\Scripts\python.exe nsga2_motorcad.py --help

# Ví dụ khi chủ động bắt đầu tối ưu, tổng budget 100 lượt gọi EMag:
.\.venv\Scripts\python.exe nsga2_motorcad.py --population 20 --generations 10 --budget 100 --seed 17 --run-dir runs/nsga2_L100

# Tiếp tục và tăng tổng budget nếu muốn:
.\.venv\Scripts\python.exe nsga2_motorcad.py --population 20 --generations 10 --budget 200 --seed 17 --run-dir runs/nsga2_L100 --resume
```

**Không cần chạy DoE hay smoke FEA riêng trước NSGA-II.** Nó kiểm tra tên input/output ngay trong cùng phiên dùng để tối ưu, ghi `startup_check.json`, rồi đánh giá từng ứng viên. Lần FEA đầu tiên là ứng viên NSGA-II, có tính vào budget. Luôn tuần tự: đặt thiết kế → chạy EMag → đọc/lưu kết quả → thiết kế tiếp theo. Không tự chuyển sang song song sau một giờ.

**Một license:** lưu và đóng Motor-CAD đang mở trước khi chạy để nhường license cho Python. Nếu phát hiện Motor-CAD đã mở, chương trình báo lỗi trước khi mở thêm; không tự đóng hoặc ghi đè phiên bạn đang chỉnh sửa. Khóa phiên chung ngăn hai run của chương trình tranh license. Nếu máy khác giữ license mạng, vẫn có thể gặp lỗi checkout từ Motor-CAD.

Đã qua 21 kiểm thử offline sau thay đổi. **Chưa chạy thêm FEA và chưa có kết quả cho cấu hình 100 mm.**

Các phần dưới mô tả công cụ hỗ trợ và lần kiểm chứng trước: DoE/check mặc định dùng `motorcad_config.json`, giữ các chiều dài gốc; NSGA-II (cả file riêng và lệnh tương thích) mặc định dùng `nsga2_config.json`, chiều dài 100 mm. Yêu cầu smoke trước chiến dịch bên dưới chỉ còn áp dụng cho DoE hỗ trợ, không áp dụng cho NSGA-II.

## Cài đặt

Đã tạo `.venv` trong project, dùng Python 3.9.7 và các phiên bản trong `requirements.txt`. Không sửa Python đi kèm Motor-CAD. Trong PowerShell tại thư mục project:

```powershell
# Nếu tạo môi trường mới trên máy khác:
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# Kiểm thử offline, không cần license Motor-CAD:
.\.venv\Scripts\python.exe -m unittest -v

# Trợ giúp, không khởi động Motor-CAD:
.\.venv\Scripts\python.exe motorcad_optimize.py --help
```

Python 3.9 trở lên; đã kiểm thử bằng interpreter nói trên. Sửa `motorcad_exe` trong `motorcad_config.json` nếu vị trí cài đặt khác. Đường dẫn model tương đối được tính từ thư mục chứa config. License Motor-CAD có E-Magnetic phải khả dụng. Trong môi trường Codex này, lần khởi động trong sandbox đã thất bại; các lần kiểm tra thành công được chạy ngoài sandbox. Đây không phải yêu cầu chạy Windows bằng quyền quản trị.

## Chạy từng chế độ

### 1. Check, mặc định không FEA

```powershell
.\.venv\Scripts\python.exe motorcad_optimize.py check
```

Mở một instance riêng, copy model vào thư mục làm việc, xác nhận get/set/readback bảy biến, kiểm tra geometry không tự sửa, xác nhận thông số cố định, script autorun tắt, mapping output và điều khiển J. Không chạy script DoE nhúng trong model. Báo cáo: `inspection/check/check_report.json`.

Đọc output trước FEA chỉ xác nhận tên có thể truy cập; giá trị 0 trong check không phải dữ liệu mô phỏng. Trước khi chạy chiến dịch, thực hiện kiểm tra một thiết kế thật:

```powershell
.\.venv\Scripts\python.exe motorcad_optimize.py check --smoke-fea
```

Lệnh này chỉ cho tối đa **một lần gọi E-Magnetic trong thư mục check**, chọn thiết kế gần baseline sau làm tròn về lưới. Nó giữ nguyên file gốc, vật liệu, số vòng dây, tốc độ, phase advance, dòng theo current-density mode, losses và thermal assumptions. Kết quả lưu ledger/CSV như một run kiểm tra độc lập; không tự đưa vào cache của các thí nghiệm khác. Gọi lại cùng thư mục dùng cache. Nếu lần duy nhất lỗi, dùng thư mục check mới để chủ động thử lại, rồi trỏ `--verification` tới báo cáo mới.

### 2. Exploratory LHS DoE

```powershell
# Ví dụ chiến dịch 40 thiết kế; chỉ chạy khi bạn chủ động gọi lệnh:
.\.venv\Scripts\python.exe motorcad_optimize.py doe --samples 40 --budget 40 --seed 17 --run-dir runs/doe_40

# Tiếp tục run, tổng ngân sách vẫn tính từ lúc bắt đầu:
.\.venv\Scripts\python.exe motorcad_optimize.py doe --samples 40 --budget 40 --seed 17 --run-dir runs/doe_40 --resume
```

SciPy Latin Hypercube lấy mẫu trong không gian chỉ số lưới, mỗi mức có cùng độ rộng ô, sau đó loại trùng. Danh sách mẫu được lưu trước mô phỏng. Geometry bị loại trước solver không tiêu budget nên số lần gọi solver có thể ít hơn số mẫu. Khuyến nghị ban đầu 30–50 mẫu; mặc định 40 nhưng không chạy nếu chưa chỉ định mode.

### 3. Direct NSGA-II

```powershell
.\.venv\Scripts\python.exe motorcad_optimize.py nsga2 --population 40 --generations 30 --budget 200 --seed 17 --run-dir runs/nsga2_reference

# Tăng tổng budget và tiếp tục chính run đó:
.\.venv\Scripts\python.exe motorcad_optimize.py nsga2 --population 40 --generations 30 --budget 400 --seed 17 --run-dir runs/nsga2_reference --resume
```

Dùng NSGA-II của pymoo 0.6.1.5, SBX/PM với integer rounding repair và duplicate elimination. Ba mục tiêu maximize được đổi dấu nhất quán bên trong pymoo. Mỗi thiết kế mới trực tiếp gọi Motor-CAD; không có mô hình thay thế. Thiết kế lỗi có constraint violation, không có mục tiêu giả trong CSV hoặc Pareto.

`--population >= 4`, `--generations >= 1`. Resume giữ nguyên population/generations/seed; được tăng tổng budget. Checkpoint giữ thuật toán, population/offspring đang dở và trạng thái RNG Python/NumPy. Một thế hệ đang dở được đi lại qua cache để hoàn thành. Không load checkpoint từ nguồn khác: file `.dill` là dữ liệu tuần tự hóa Python có thể thực thi mã khi đọc.

### 4. Phân tích CSV, không Motor-CAD và không FEA

```powershell
.\.venv\Scripts\python.exe motorcad_optimize.py analyze --csv runs/nsga2_reference/evaluations.csv --out-dir runs/nsga2_reference/analysis
```

Xuất `pareto.csv`, `objective_pairs.png`, `pareto_3d.png`, `analysis.json`. Chỉ dùng hàng `status=ok` có đủ ba mục tiêu hữu hạn và nằm trong khoảng PF/efficiency hợp lệ. Không nối điểm bằng đường giả vì nondominated set được tính đồng thời trong ba chiều. Nếu chưa có điểm khả thi thì CSV Pareto rỗng và không tạo hình giả. Không so sánh/nối chung dữ liệu khác fingerprint.

Tên Pareto luôn là **Best-known Pareto Reference**, không khẳng định ground truth. Với một điểm thật chỉ vẽ được một điểm, chưa thể kết luận đánh đổi.

## Biến thiết kế và cấu hình được bảo toàn

| Tên | Min | Max | Step |
|---|---:|---:|---:|
| Ratio_Bore | 0.5 | 0.8 | 0.0001 |
| Ratio_SlotDepth_ParallelTooth | 0.5 | 0.8 | 0.0001 |
| Ratio_ToothWidth | 0.3 | 0.65 | 0.0001 |
| Ratio_ShaftD | 0.5 | 0.8 | 0.0001 |
| Ratio_MagnetArc | 0.7 | 0.9 | 0.05 |
| Magnet_Thickness | 3 | 5 | 0.5 |
| Slot_Corner_Radius | 0 | 2 | 0.5 |

Các bước được biểu diễn bằng chỉ số nguyên, cache dùng chỉ số nên không bị sai khác float. Với config hỗ trợ gốc `motorcad_config.json`, chiều dài stator là 117.839 mm, rotor/nam châm là 83.472 mm. Với config tối ưu hiện tại `nsga2_config.json`, cả ba chiều dài cố định 100 mm theo yêu cầu mới. Đường kính stator luôn giữ 129.772 mm.

Model có 18 slots / 4 poles, Surface Radial rotor, Parallel Tooth stator, 1500 rpm, `MagTurnsConductor=35`, ba pha. Mỗi thiết kế được load lại từ bản sao sạch ở đường dẫn riêng để không kế thừa input tự sửa hoặc kết quả sidecar của thiết kế trước. Nếu Motor-CAD tự sửa một biến ra khỏi giá trị yêu cầu, chương trình ghi `readback_mismatch` và loại thiết kế thay vì ghi output dưới input sai.

Không thêm constraint điện áp/DC bus vào NSGA-II. `DCBusVoltage=400` và drive gốc được giữ nguyên; điều này không đồng nghĩa bỏ qua mọi hành vi giới hạn điện áp nội bộ của drive. Cần kiểm tra cảnh báo Motor-CAD khi diễn giải kết quả ở miền điện áp cao.

## Ba mục tiêu và output bổ sung

| Cột CSV | Automation parameter | Định nghĩa | Đơn vị |
|---|---|---|---|
| average_torque_nm | AvTorqueMsVw | Mô-men điện từ trung bình từ Maxwell Stress và Virtual Work FE | Nm |
| power_factor | PhasorPowerFactor | PF từ giản đồ phasor; không tự lấy trị tuyệt đối | Không thứ nguyên |
| efficiency_pct | MotorEfficiency | Hiệu suất motor với mô hình tổn hao gốc | % |
| shaft_torque_nm | ShaftTorque | Mô-men tại trục, khác mô-men điện từ | Nm |
| system_efficiency_pct | SystemEfficiency | Hiệu suất hệ thống, lưu riêng với motor efficiency | % |
| phase_terminal_voltage_rms_v | PhasorRmsPhaseVoltage | Điện áp pha đầu cực RMS từ phasor | V |

Tên và mô tả được đối chiếu từ tài nguyên của executable Motor-CAD 2025.2.2, sau đó kiểm tra `get_variable` trực tiếp. Bằng chứng ở `inspection/automation_name_evidence.txt`, `inspection/parameter_probe.json` và `inspection/check/check_report.json`. Không dùng output IM/Lab thay cho output BPM E-Magnetic.

Tài liệu Ansys: [BPM E-Magnetic Output Data](https://ansyshelp.ansys.com/public/Views/Secured/MotorCAD/v252/en/Motor-CAD_UG/MotorCAD/topics/e-magnetics_bpm_output_data.html), [Power Factor](https://ansyshelp.ansys.com/public/Views/Secured/MotorCAD/v252/en/Motor-CAD_UG/MotorCAD/topics/powerfactor.html), [tìm tên automation](https://ansyshelp.ansys.com/public/Views/Secured/MotorCAD/v252/en/Motor-CAD_UG/MotorCAD/topics/activexinputandoutputparameters.html).

**Giới hạn hiệu suất:** baseline tắt `OnLoadLossCalculation` và `BackEMFLossCalculation`. Chương trình không tự bật thêm các phân tích này. Hiệu suất đọc từ Motor-CAD chỉ có ý nghĩa theo loss model gốc; chưa được xem là hiệu suất có mọi thành phần tổn hao FEA. Muốn thay loss model cần cấu hình/thí nghiệm mới với fingerprint mới, rồi chạy lại check.

## J = 7 A/mm²

Baseline dùng `CurrentDefinition=2`, `RMSCurrentDensity=7`. Chương trình giữ mode và target này, không cố định lại `PeakCurrent` hoặc tự đổi số vòng dây. Dòng có thể được Motor-CAD cập nhật muộn khi tính toán.

Sau mỗi FEA, chương trình kiểm tra thêm J từ `RmsCurrentCalc` và diện tích đồng tròn thực `Copper_Diameter`, với số parallel paths và strands in hand. Công thức áp dụng riêng cho winding sao, một cỡ dây tròn của model này; sai số chấp nhận 0.001 A/mm². Nếu không đọc được hoặc J lệch target, hàng đó bị loại. Các cột `actual_j_a_per_mm2`, `calculated_rms_line_current_a`, `copper_diameter_mm` giúp kiểm tra độc lập. Không tái dùng công thức cho delta, rectangular/litz hoặc mixed wire sizes.

## Dataset, cache, lỗi và ngân sách

Mỗi thư mục run có:

- `manifest.json`: hash model/executable, thư viện, định nghĩa output và config đầy đủ.
- `evaluations.sqlite`: ledger/cache chính, transaction `FULL synchronous`.
- `evaluations.csv`: một hàng mỗi lần đánh giá thực tế, gồm cả lỗi.
- `history.csv`: mọi yêu cầu đã trả kết quả, gồm cache hits và liên kết evaluation ID gốc.
- `summary.json`: tổng solver attempts, cache hits, trạng thái và thời gian tích lũy.
- `doe_plan.json` hoặc `nsga2_checkpoint.dill` để resume.
- `work/`: bản sao model/sidecar theo từng lần chuẩn bị thiết kế; giữ lại để truy vết.
- `analysis/`: Pareto và biểu đồ từ dữ liệu đã hoàn tất.

CSV gồm `schema_version`, `run_id`, `evaluation_id`, `source`, `generation`, `design_key`, `config_fingerprint`, bảy input, ba mục tiêu, output bổ sung, `status`, `reason`, `fea_started`, thời điểm UTC và thời gian. `readback_json` xác nhận giá trị đặt; ô mục tiêu trống khi lỗi. Các cột bổ sung không đọc được được ghi trong `optional_output_errors`. Phân tích yêu cầu fingerprint không rỗng; hàng khả thi cần schema hỗ trợ và run ID. Khi ghép nhiều run cùng fingerprint, evaluation ID được phân biệt theo run ID. Nếu có manifest cạnh CSV, fingerprint phải khớp. Phân tích rỗng sẽ loại hai PNG kết quả cũ để tránh hiển thị nhầm.

**Budget** là tổng số lần gọi `do_magnetic_calculation()`, gồm thành công, thất bại và gián đoạn. Một lần gọi có thể chứa nhiều FEA sub-solves bên trong Motor-CAD; chương trình không khẳng định đã đếm được từng sub-solve. Geometry bị loại trước solver không tính vào budget. Bộ đếm được ghi bền vững trước khi gọi solver, do đó crash không làm mất ngân sách đã tiêu. `--budget` khi resume là tổng, không phải ngân sách cộng thêm.

Cache nằm trong từng run, có fingerprint model + executable + mapping/config + dependency versions. Không âm thầm dùng cache từ chiến dịch tham chiếu cho baseline cùng budget. Để so sánh ANN sau này, tạo run độc lập với cùng định nghĩa ngân sách; cache chia sẻ cần một protocol riêng.

Sau gián đoạn, attempt đang `started` thành `interrupted`, vẫn tính budget và không có objective. Mặc định không retry thiết kế lỗi. `--retry-failed` cho thử lại mỗi thiết kế lỗi tạm thời/gián đoạn tối đa một lần trong lần gọi chương trình, không ghi đè lịch sử; mỗi lần thực gọi solver tiêu thêm budget. Lỗi khi gọi hàm kiểm tra geometry được ghi `geometry_check_failed` và cho phép retry rõ ràng vì có thể do RPC/license thay vì hình học. Invariant/readback lỗi xác định được cache, không retry tự động.

Chỉ một writer trên mỗi thư mục run. Không xóa hoặc sửa SQLite/checkpoint trong lúc chạy. Nếu dừng bằng Ctrl+C, dữ liệu đã hoàn tất được lưu; lần solver đang dở có thể không khôi phục được và cần retry rõ ràng.

## Tái sử dụng code cũ

Tái sử dụng thư viện PyMotorCAD, bảy tên biến và trình tự `set_variable` → `do_magnetic_calculation` → `get_variable` từ script Python nhúng trong `.mot`. Script bên ngoài được dùng để tham khảo cách gọi E-Magnetic và đọc ShaftTorque.

Không chạy nguyên bản script bên ngoài vì nó đổi 24 rãnh, vật liệu, tốc độ, dòng, phase advance và bus voltage. Không chỉnh script nhúng vì nó thay 11 input, chỉ lấy ShaftTorque, ghi đè CSV và có thể tiếp tục khi thiếu input. Các lỗi này được xử lý trong chương trình mới; hai script nguồn và file .mot/.bak giữ nguyên.

## Những điểm cần kiểm chứng thêm trước kết luận nghiên cứu

Một smoke FEA chỉ xác nhận luồng tại một thiết kế, không chứng minh toàn miền hình học khả thi. Cần đánh giá loss model/độ hội tụ mesh/time steps, nội dung tổn hao motor so với system, ảnh hưởng độ dài magnetic hiệu dụng, và hành vi điện áp của drive trên các ứng viên Pareto. Chương trình giữ cấu hình gốc và lưu lý do lỗi; nó không tự đưa ra giả định vật lý để lấp những khoảng này.

Công thức kiểm tra J độc lập hiện được khóa với hash của chính `Basic_Model.mot` được cung cấp. Nếu thay baseline, cần kiểm chứng lại loại dây/connection và công thức rồi điều chỉnh `validate_j_scope`; chương trình sẽ báo lỗi rõ ràng khi model khác hash. Đây là giới hạn có chủ ý để tránh áp nhầm công thức cho cấu hình dây khác.

Đã chạy đúng một thiết kế thật thành công, cùng 18 kiểm thử offline. Kết quả smoke và biểu đồ nằm trong `inspection/check/`; bản ghi kiểm chứng ở `inspection/VALIDATION.md`. Pymoo 0.6.1.5 có cảnh báo deprecation `np.row_stack` với NumPy 2; cảnh báo không làm các kiểm thử thất bại.
