# Thiết kế DoE và Direct NSGA-II cho Basic_Model.mot

Ngày: 12/11/2026. Trạng thái: bản thiết kế để người dùng duyệt; chưa triển khai chương trình tối ưu.

## Mục tiêu và phạm vi

Xây dựng chương trình Python điều khiển trực tiếp Motor-CAD 2025.2 với bốn lệnh `check`, `doe`, `nsga2`, `analyze`. Tối đa hóa đồng thời Average Torque, Power Factor và Efficiency. Dữ liệu mô phỏng thật được lưu thống nhất để tái sử dụng cho nghiên cứu ANN sau này. Không triển khai ANN hoặc surrogate trong giai đoạn này.

Không chạy chiến dịch FEA lớn trong lúc xây dựng. Không sửa Basic_Model.mot, file .bak hoặc script tham khảo. Chỉ thử một thiết kế sau khi kết nối và cách lấy đủ ba mục tiêu đã được xác nhận.

## Kết quả kiểm tra project

- Không có Git repository và không tìm thấy AGENTS.md trong workspace.
- Có Basic_Model.mot, Basic_Model.bak, script E-Magnetic bên ngoài và một message log. Không có CSV DoE riêng trong workspace.
- Basic_Model.mot là file văn bản của Motor-CAD 2025.2.2.1. SHA256 ban đầu: `1cfee7718f933e65908a5df30da9003786bd7886edc13f0c6db62a0816a41811`.
- Model lưu `Motor_Type=BPM`, `Slot_Type=Parallel_Tooth`, `BPM_Rotor=Surface_Radial`, 18 slots, 4 poles và `GeometryParameterisation=1`.
- Model có script Python nhúng, 114 dòng, dùng `ansys.motorcad.core`. Nó đọc một CSV đường dẫn cố định ngoài workspace, đặt 11 tham số, gọi `do_magnetic_calculation()` rồi lấy `ShaftTorque`.
- Cả bảy tên biến được yêu cầu đều tồn tại nguyên văn trong phần dữ liệu model. Điều này xác nhận tên trong file, chưa thay cho kiểm tra get/set qua API.
- `Stator_Lam_Dia=129.772` mm; `Stator_Lam_Length=117.839` mm. `Rotor_Lam_Length=83.472` mm và `Magnet_Length=83.472` mm.
- `RMSCurrentDensity=7` A/mm², `CurrentDefinition=2`, `RMSCurrent=4.32105629873388` A và `PeakCurrent=6.11089642144714` A. Cần xác nhận ý nghĩa enum 2 và việc dòng điện tự cập nhật khi đổi hình học bằng API/UI/tài liệu, không suy ra chỉ từ con số.
- Phần electromagnetic lưu tốc độ 1500 rpm, `PhaseAdvance=0`, `MagTurnsConductor=35`, ba pha và một parallel path. File còn có khóa Shaft_Speed trong phần khác; không đọc bằng parser chỉ giữ giá trị cuối mà bỏ ngữ cảnh.
- `TorqueCalculation=True`; `OnLoadLossCalculation=False`; `BackEMFLossCalculation=False`. Phải kiểm tra đầy đủ loss model và độ mới của hiệu suất; chưa kết luận tắt hai cờ này đồng nghĩa hiệu suất không thể tính.
- Python mặc định là 3.9.7, có SciPy 1.13.1 và pywin32; chưa có pymoo và ansys-motorcad-core trong interpreter này.
- Bộ cài `C:/Program Files/AnsysMotorCAD/v252_SP1` chứa Motor-CAD 2025.2.2, Python 3.11, PyMotorCAD 0.7.4, SciPy 1.16.0, NumPy 2.3.1 và Matplotlib 3.10.3. Chưa xác nhận pymoo trong interpreter đi kèm.
- Lần kiểm tra kết nối đầu tiên trong sandbox trên bản sao thất bại vì tiến trình Motor-CAD thoát trước khi kết nối RPC. Lần kiểm tra ngoài sandbox thành công, đọc được cả bảy biến cùng các tham số cố định, J, tốc độ, số vòng và cờ losses. `ShaftTorque` truy cập được nhưng bằng 0 khi chưa chạy FEA; không coi đây là kết quả thiết kế. Không gọi FEA ở cả hai lần. Chi tiết ở `inspection/connection_check.json` và `inspection/connection_check_external.json`. Kết quả phù hợp với hạn chế môi trường sandbox, nhưng hai lần thử chưa đủ chứng minh nguyên nhân khởi động thất bại; không cần sửa model hoặc cài lại Motor-CAD để có lần kết nối thành công này.

## Các cách triển khai đã xem xét

1. **PyMotorCAD JSON-RPC, đề xuất của người triển khai.** Tái sử dụng thư viện và chuỗi set/calculate/get của script nhúng. Dùng đúng executable 2025.2 và phiên làm việc riêng. Hợp với model hiện tại, hỗ trợ exception. Cần xử lý lỗi khởi động hiện tại trước khi kiểm chứng trực tiếp.
2. **ActiveX/COM như script bên ngoài.** Tái sử dụng được khái niệm SetVariable, DoMagneticCalculation, GetVariable và ExportResults nhưng phải xử lý mã thành công, tuple trả về và đăng ký phiên bản COM. Máy có nhiều phiên bản Motor-CAD nên COM có thêm rủi ro trỏ sai executable.

Đề xuất chỉ một backend PyMotorCAD trong bản đầu để giữ code gọn. Không xây hai backend cùng lúc. Đây là lựa chọn đề xuất, chưa phải lựa chọn người dùng đã duyệt.

## Những phần được tái sử dụng và vấn đề code cũ

Từ script nhúng: danh sách tên bảy biến, trình tự `set_variable` → `do_magnetic_calculation` → `get_variable`, và CSV theo tên cột. Từ script bên ngoài: cách gọi E-Magnetic và xuất kết quả để đối chiếu.

Không chạy nguyên script bên ngoài: nó đổi 24 rãnh, vật liệu, tốc độ 1000 rpm, dòng đỉnh 3 A, điện áp bus, phase advance và các tùy chọn tính toán. Nó không load Basic_Model.mot và dùng thư mục C:/Workspace cố định.

Script nhúng có các điểm cần khắc phục trong chương trình mới:

- Nếu thiếu khóa CSV hoặc chuyển float thất bại, code vẫn tiếp tục tính toán, có thể trộn input mới với giá trị còn lại của thiết kế trước.
- Nó ghi đè file kết quả với mode `w`, không có cache, resume, trạng thái từng thiết kế hoặc flush bền vững.
- Nó thay cả đường kính, chiều dài và chỉ có một output ShaftTorque; không đáp ứng phạm vi bảy biến và ba mục tiêu hiện tại.
- Không có kiểm tra geometry và xác thực toàn bộ output sau từng lần chạy.
- Không có load/reset model gốc rõ ràng trước từng thiết kế.

Không chỉnh các script nguồn; chỉ tái sử dụng các lệnh phù hợp trong file mới.

## Biến thiết kế và các bất biến

| Tên | Min | Max | Step |
|---|---:|---:|---:|
| Ratio_Bore | 0.5 | 0.8 | 0.0001 |
| Ratio_SlotDepth_ParallelTooth | 0.5 | 0.8 | 0.0001 |
| Ratio_ToothWidth | 0.3 | 0.65 | 0.0001 |
| Ratio_ShaftD | 0.5 | 0.8 | 0.0001 |
| Ratio_MagnetArc | 0.7 | 0.9 | 0.05 |
| Magnet_Thickness | 3 | 5 | 0.5 |
| Slot_Corner_Radius | 0 | 2 | 0.5 |

Tối ưu trên chỉ số nguyên của lưới; giải mã bằng lower + index × step. Khóa cache dùng các chỉ số, tránh so sánh float. LHS của SciPy được chiếu về lưới và loại trùng. NSGA-II dùng repair và duplicate elimination dựa trên cùng lưới.

Giữ cố định đường kính, chiều dài stator, số vòng dây, topology, pole/slot, vật liệu, tốc độ, drive, phase advance và thermal assumptions. Lưu snapshot các bất biến trước khi chạy và kiểm tra lại trước mỗi FEA. Không tự ép hai chiều dài rotor/nam châm thành chiều dài stator: chỉ áp dụng liên kết nếu model thực sự yêu cầu và đã xác nhận. Bất kỳ thay đổi bắt buộc nào đến cấu hình vật lý phải báo người dùng trước.

Chỉ chấp nhận thiết kế có J=7 A/mm² trong dung sai được ghi rõ trong metadata. Xác nhận current-density mode hoạt động và ghi cả dòng điện thực. Nếu không xác nhận được hoặc mode không giữ J khi đổi hình học, dừng với lý do; không tự chuyển sang fixed-current hoặc âm thầm đổi điều kiện vận hành.

## Xác nhận mục tiêu và cơ chế chặn

Đề xuất Average torque (FE), tức electromagnetic airgap torque, làm mục tiêu torque để đúng chữ Average Torque; lưu ShaftTorque như output bổ sung. Đơn vị Nm. Không dùng hai định nghĩa thay thế nhau giữa các thiết kế.

Power Factor: chọn một định nghĩa cố định phù hợp drive của model, ưu tiên fundamental/phasor PF nếu có. Lưu tên automation, định nghĩa, khoảng giá trị và đơn vị không thứ nguyên. Không lấy trị tuyệt đối hoặc tráo sang waveform PF tự động.

Efficiency: cần xác nhận output E-Magnetic được chọn là motor efficiency hay System Efficiency của màn hình E-Magnetic, tổn hao nào được bao gồm và đơn vị %. Không nhầm với System Efficiency trong Lab hoặc mặc nhiên gọi System Efficiency là Motor Efficiency. Nếu chỉ có system efficiency, phải ghi đúng tên và định nghĩa trong dataset, báo rõ trước khi dùng làm mục tiêu.

Không đoán tên automation cho Average torque (FE), PF, efficiency hoặc phase voltage. `check` phải xác nhận mapping từ automation của Motor-CAD hoặc kết quả export có nhãn, đối chiếu tài liệu và đọc lại bằng API. Những mục tiêu chưa xác nhận sẽ chặn `doe`/`nsga2`; không tạo output giả để cho chương trình chạy tiếp.

`check` mặc định không FEA: load bản sao, kiểm tra kết nối, get/set/readback trên bản sao, đối chiếu bất biến và báo trạng thái từng mục. Giá trị output đọc trước FEA chỉ chứng minh khả năng truy cập; không được coi là kết quả mô phỏng mới.

Nếu hiệu suất cần thêm phép tính loss, báo chính xác cờ/cấu hình phải thay và yêu cầu người dùng quyết định; không bật loss/thermal assumptions tự động. Không áp ràng buộc điện áp hoặc DC bus trong optimizer. Không thay đổi drive gốc để tránh giới hạn; nếu drive gốc tự giới hạn thì phải báo rõ.

## Luồng đánh giá thiết kế

Trước khi load một model cho chiến dịch, kiểm tra cơ chế script tự chạy/callback của Motor-CAD. File gốc lưu `ScriptAutoRun=0` và `ScriptAutoRun_PythonClasses=0`; xác nhận ý nghĩa và đọc lại hai cờ qua API trước khi tính. Không gọi ExecuteScript hoặc hàm chạy script nhúng. Không cần xóa script nhúng nếu xác nhận được các cờ đã vô hiệu toàn bộ callback liên quan. Chặn solver nếu không chứng minh được sự cô lập này, báo đúng cờ chưa xác nhận thay vì tự sửa nội dung script. Bản sao kiểm tra kết nối đã được load thành công nhưng chưa phải bằng chứng mọi callback khi tính toán đều an toàn.

1. Kiểm tra fingerprint của model, phiên bản Motor-CAD, mapping output và các thiết lập vật lý; tạo evaluation ID và design key.
2. Tra cache đúng fingerprint, gồm cả thiết kế lỗi đã hoàn tất. Lần gọi lại được ghi là cache hit và liên kết evaluation gốc.
3. Load bản sao baseline sạch; đặt toàn bộ bảy biến; đọc lại. Mismatch hoặc Motor-CAD tự sửa hình học thì đánh dấu không khả thi thay vì gắn output với input sai.
4. Kiểm tra geometry không cho tự sửa. Đã tìm thấy `check_if_geometry_is_valid(0)` trong PyMotorCAD 0.7.4, nhưng cần kiểm chứng cách trả trạng thái: tài liệu method và lớp RPC có xử lý đặc biệt. Không coi 0/1 là Boolean thông thường khi chưa kiểm chứng.
5. Kiểm tra J và các bất biến; xác nhận quyền chạy trong FEA budget còn lại.
6. Ghi ledger bền vững `started` trước lệnh solver; tăng bộ đếm solve attempts trước khi gọi để crash không làm hụt budget. Một đơn vị budget được định nghĩa là một lần gọi tính E-Magnetic cho một thiết kế; số sub-solves nội bộ có thể lớn hơn và phải được mô tả rõ.
7. Chạy E-Magnetic, kiểm tra exception/trạng thái; chỉ đọc mục tiêu sau khi tính thành công. Không lấy lại kết quả từ thiết kế trước hoặc tự thay bằng 0.
8. Kiểm tra tất cả output bắt buộc hữu hạn, đúng đơn vị/khoảng giá trị, J và readback sau tính vẫn hợp lệ; ghi trạng thái cuối và flush ngay.

Geometry failure, calculation failure, missing output, invariant violation và interrupted phải có reason riêng. Ô mục tiêu lỗi để trống trong CSV. Pymoo nhận objective/constraint phục vụ loại nghiệm lỗi; giá trị phạt nội bộ không xuất như dữ liệu Motor-CAD. Pareto chỉ lấy hàng `ok` có đủ ba mục tiêu thật.

## Lưu trữ, cache và resume

Mỗi run có thư mục riêng chứa manifest JSON, ledger bền vững, CSV thống nhất, checkpoint thuật toán, thống kê và biểu đồ. Ledger có thể dùng SQLite của Python để tránh CSV ghi dở và đếm sai ngân sách; CSV được xuất từ ledger sau từng kết quả và khi kết thúc. Chỉ một tiến trình và một phiên Motor-CAD đánh giá tuần tự.

Fingerprint bao gồm hash model, phiên bản ứng dụng, spec bảy biến, mapping/đơn vị mục tiêu và các lựa chọn tính toán. Không tái sử dụng cache khi fingerprint khác. Không tự đưa cache chiến dịch tham chiếu vào baseline so sánh cùng budget; mỗi thí nghiệm có cache namespace riêng, chia sẻ chỉ khi được lựa chọn và ghi rõ.

Phân loại lỗi: geometry/readback/invariant vi phạm đã xác nhận là lỗi xác định và được cache; lỗi RPC, giấy phép, process hoặc solver chưa xác định nguyên nhân là lỗi có thể thử lại. Mặc định không tự retry để tránh tiêu ngân sách ngoài dự kiến. Người dùng có thể chọn retry theo evaluation ID hoặc nhóm lỗi có thể thử lại; bản ghi cũ không bị ghi đè, mỗi lần thử có attempt ID mới và nếu gọi solver phải trừ thêm budget. Thiết kế lỗi xác định chỉ thử lại khi có yêu cầu rõ ràng; sửa cấu hình vật lý/mapping tạo fingerprint mới. Output chưa xác nhận toàn chiến dịch sẽ chặn run thay vì cache hàng loạt lỗi thiết kế.

Resume DoE tiếp tục danh sách mẫu đã lưu, không lấy lại mẫu mới. Resume NSGA-II khôi phục population, RNG và trạng thái thuật toán tại generation đã hoàn tất; cache tái sử dụng kết quả của generation đang dở. Các lượt `started` không có kết quả sau crash giữ trạng thái `interrupted`, tính vào solve attempts; chỉ retry theo lựa chọn rõ ràng và phải tốn thêm budget. Không giả vờ tiếp tục chính xác từ giữa solver.

Checkpoint ghi atomic sau generation và trước khi dừng theo budget. Tổng attempts không vượt giới hạn cả khi resume. Khi hết budget giữa generation, dừng có kiểm soát và xuất Best-known Pareto Reference từ toàn bộ kết quả khả thi đã có; không ép population còn thiếu bằng output giả.

Ghi tách biệt requests, cache hits, solve attempts, successful solves, failed solves, interrupted attempts, geometry rejections, thời gian solver, và wall time tích lũy qua các lần resume. Không gọi solve attempts là số phần tử FEA nội bộ khi chưa đo được.

## CSV và phân tích

Nhóm cột tối thiểu:

- `schema_version, run_id, evaluation_id, source, generation, design_key, model_sha256, config_fingerprint`.
- Bảy cột input đúng tên yêu cầu; có readback hoặc bản ghi readback đi kèm.
- `average_torque_nm, power_factor, efficiency_pct`, với mapping chính xác ghi trong manifest.
- Các output bổ sung đã xác nhận: ShaftTorque, voltage pha (ghi rõ RMS/peak và phase/line), RMS/peak current, current density, speed và losses khi truy cập được.
- `status, reason, started_at_utc, finished_at_utc, elapsed_s, solver_attempt_id, cache_hit, original_evaluation_id`.

`analyze` đọc CSV và manifest mà không tạo Motor-CAD instance. Loại hàng lỗi, thiếu output, NaN/Inf và fingerprint không tương thích trước khi tính nondominated set. Xuất `pareto.csv`, scatter ba cặp mục tiêu và scatter 3D, nhãn rõ đơn vị và “Best-known Pareto Reference”. Nếu chưa có điểm khả thi thì báo rõ, không tạo Pareto giả. Không chọn một nghiệm tốt nhất duy nhất nếu người dùng chưa đưa trọng số.

## File bàn giao và trình tự triển khai dự kiến

Ưu tiên một file chạy chính `motorcad_optimize.py`, một file kiểm thử `test_motorcad_optimize.py`, hướng dẫn tiếng Việt `README.md` và danh sách thư viện. Các file JSON/CSV/ảnh là cấu hình và kết quả, không chia chương trình thành nhiều module.

1. Hoàn tất `check`, báo nguyên nhân lỗi startup và xác nhận mapping mục tiêu/J/geometry. Mọi điểm chưa xác nhận được liệt kê rõ.
2. Xây đánh giá tuần tự, cache/ledger, bảo vệ model, lượng tử hóa, budget và export.
3. Xây LHS DoE với số điểm cấu hình, đề xuất 40; lưu mẫu trước chạy.
4. Tích hợp NSGA-II của pymoo, ba mục tiêu maximize chuyển dấu nhất quán, constraints, seed và checkpoint/resume.
5. Xây analyze, CSV Pareto và đồ thị 2D/3D.
6. Kiểm thử offline có ý nghĩa: lưới và duplicate, lỗi solver không lọt Pareto, invariants, cache/fingerprint, crash accounting và resume/budget. Kiểm thử bằng mock được đánh dấu là mock, không ghi vào dataset thực.
7. Chỉ sau khi check đạt: chạy tối đa một thiết kế thật để kiểm tra luồng. Không tự chạy 40 điểm hoặc một population NSGA-II trong lần bàn giao.

Chạy chương trình không truyền lệnh chỉ in help. README trình bày cài thư viện trong môi trường riêng, chọn đúng Python/executable, lệnh từng mode, cách resume, định nghĩa budget và danh sách chưa xác nhận. Chưa cung cấp lệnh chạy các file chưa được tạo như thể chúng đã tồn tại.

## Nguồn đối chiếu

- Model gốc và hai script đã đọc đầy đủ phần liên quan, cùng API PyMotorCAD 0.7.4 tại bộ cài địa phương.
- Ansys 2025 R2, E-Magnetics BPM Output Data: https://ansyshelp.ansys.com/public/Views/Secured/MotorCAD/v252/en/Motor-CAD_UG/MotorCAD/topics/e-magnetics_bpm_output_data.html
- Ansys 2025 R2, Power Factor: https://ansyshelp.ansys.com/public/Views/Secured/MotorCAD/v252/en/Motor-CAD_UG/MotorCAD/topics/powerfactor.html
- Lab Output Parameters (chỉ đối chiếu sự khác nhau về định nghĩa, không dùng thay mapping EMag): https://ansyshelp.ansys.com/public/Views/Secured/MotorCAD/v252/en/Motor-CAD_UG/MotorCAD/topics/output_parameters.html

## Rà soát thiết kế

Một lượt builder review độc lập đã chỉ ra hai điểm cần bổ sung: cô lập script nhúng và chính sách retry lỗi tạm thời. Hai điểm đã được ghi rõ trong luồng đánh giá và cache/resume ở trên; đều là lựa chọn triển khai nhằm giữ đúng phạm vi đã yêu cầu, không đổi vật lý model.

## Các mục chưa xác nhận trước triển khai/chạy thật

Kết nối RPC đã thử thành công ngoài sandbox; còn cần kiểm chứng độ ổn định và set/readback bảy biến khi đổi hình học. Chưa xác nhận enum CurrentDefinition và J khi hình học thay đổi; yêu cầu liên kết chiều dài; automation names/đơn vị/độ mới cho Average torque FE, PF, efficiency và voltage; semantics kiểm tra geometry; loss configuration để hiệu suất có ý nghĩa; drive gốc có tự giới hạn điện áp không; số solver nội bộ tương ứng một lần gọi EMag.
