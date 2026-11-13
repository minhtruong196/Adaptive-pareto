# Motor-CAD: Exploratory DoE và Direct NSGA-II

Ngày cập nhật: 13/11/2026.

## Quyết định hiện tại

Người dùng chấp nhận kết quả thăm dò hiện tại để chuyển sang model Vernier mới. **Dừng thử nghiệm trên model SPM này; không chạy thêm test, seed, ngân sách hoặc FEA chỉ để cải thiện bảng kết quả.** Đây là quyết định chuyển giai đoạn nghiên cứu, không phải khẳng định phương pháp đã được chứng minh vượt trội trên mọi bài toán.

## Phần đã hoàn thành

- Tự động hóa Motor-CAD, biến rời rạc, kiểm tra J, quản lý cache/FEA records/checkpoint và chạy song song.
- Direct NSGA-II thực tế 800 FEA, đã được đối chiếu thủ công một số thiết kế trong Motor-CAD.
- Conventional ANN + NSGA-II; Adaptive Sequential G–G–L–L; Adaptive Alternating G–L–G–L.
- Hai chiến dịch chính theo quy ước mới: **pool 60 + 20 verification cuối** và **pool 100 + 20 verification cuối**, seed 17. Các FEA trong hai chiến dịch này đều hợp lệ.
- Báo cáo sai số trung bình/lớn nhất, RMSE/R², FEA archive Pareto, verified-subset Pareto/HV và chi phí. Các run/code/config dành riêng cho budget cũ đã được loại bỏ; chỉ giữ các kết quả chính và dữ liệu nguồn cần thiết.

## Thuật ngữ và cách đếm đã thực hiện

**Pool ANN gồm fitting + validation. Không gọi pool 100 là 100 điểm trực tiếp fit mạng.** Tám điểm validation cố định được dùng chọn checkpoint, không vào gradient fitting hoặc fit scaler. Cả ba phương pháp có cùng kích thước pool/fitting/validation tại cùng một mức.

| Pool cuối | Fitting | Validation | Verification cuối, không train lại | FEA tính ngân sách mỗi phương pháp |
|---:|---:|---:|---:|---:|
| 60 | 52 | 8 | 20 | 80 |
| 100 | 92 | 8 | 20 | 120 |

Conventional lấy đủ pool từ initial/DoE toàn miền, train một lần. Adaptive train initial và một lần ở mỗi stage. **Sau verification không train lại ngay**; kết quả đó chỉ đi vào training cùng DoE mới ở stage kế tiếp.

| Pool cuối | Initial | DoE bốn stage | Verification trung gian đi vào pool | Pool qua các lần train |
|---:|---:|---|---:|---|
| 60 | 20 | 7, 6, 6, 6 | 3 × 5 = 15 | 20 → 27 → 38 → 49 → 60 |
| 100 | 40 | 12, 11, 11, 11 | 3 × 5 = 15 | 40 → 52 → 68 → 84 → 100 |

Do đó Adaptive pool 60 = **45 initial/DoE + 15 verification cũ**; pool 100 = **85 initial/DoE + 15 verification cũ**. Không cộng verification trung gian hai lần. Verification cuối có 20 thiết kế mới, nằm ngoài toàn bộ pool và không dùng để train lại.

Initial được dùng chung chính xác trong mỗi chiến dịch, tái sử dụng từ dữ liệu initial đã kiểm chứng fingerprint/LHS. Chiến dịch pool 60 chạy thêm 180 solver calls; pool 100 chạy thêm 240 solver calls. Các initial tái sử dụng vẫn được tính vào ngân sách từng phương pháp. Không dùng bộ Direct800 cho training hoặc adaptive sampling. Nguồn initial nay nằm riêng tại `data/spm_initial20/` và `data/spm_initial40/`; calibration HV cố định tại `data/spm_hv_calibration.json`. CSV nguồn được sao chép nguyên vẹn và đối chiếu SHA256 trước khi xóa run cũ.

## Kết quả trên cùng thang HV cố định

Model đã thử là **SPM 18 slots/4 poles**, không phải model Vernier mới. Ba mục tiêu tối đa hóa: average electromagnetic torque `AvTorqueMsVw`, phasor PF `PhasorPowerFactor`, motor efficiency `MotorEfficiency`. Stator diameter 129.772 mm; stator/rotor/magnet lengths 100 mm; J = 7 A/mm²; tốc độ 1500 rpm. Đây là thiết lập của testbed cũ, không mặc định áp sang model mới.

HV archive dùng mọi điểm FEA thật đã có của phương pháp. HV verification20 chỉ dùng 20 điểm kiểm chứng cuối. Không đưa dự đoán ANN chưa kiểm chứng vào các HV này.

| Pool | Phương pháp | HV archive | HV verification20 |
|---:|---|---:|---:|
| 60 | Conventional | 1.050064 | 0.994969 |
| 60 | Sequential | 1.102307 | 1.095134 |
| 60 | Alternating | 1.098929 | 1.094071 |
| 100 | Conventional | 1.086135 | 1.067533 |
| 100 | Sequential | 1.125000 | 1.097108 |
| 100 | Alternating | 1.122135 | 1.099679 |

**Direct NSGA-II 800 FEA: HV = 1.147174**, là tham chiếu độc lập khác ngân sách, không phải Pareto ground truth.

Tất cả HV trên giữ nguyên calibration của báo cáo 100 FEA ban đầu: objective order Torque/PF/Efficiency; min = `[4.54883620411918, 0.884752904222439, 79.5612967771118]`; span = `[18.52456735421862, 0.11341821372885497, 11.529350551225392]`. Với mục tiêu maximize, `z=(y-min)/span`, `F=1-z`, reference = `[1.1,1.1,1.1]`. Không đổi calibration giữa các dòng hoặc trộn với bảng HV từng dùng calibration khác.

## Sai số verification20: trung bình và lớn nhất khác nhau

Đơn vị dưới đây là sai số tương đối tuyệt đối (%): `100 × abs(ANN − FEA) / abs(FEA)`. Mỗi ô ghi **trung bình / lớn nhất** trên 20 thiết kế mới của phương pháp đó.

| Pool | Phương pháp | Torque | PF | Efficiency |
|---:|---|---:|---:|---:|
| 60 | Conventional | 16.5929 / 32.4898 | 0.2073 / 0.3700 | 0.9783 / 1.7419 |
| 60 | Sequential | 12.4408 / 44.2177 | 0.5252 / 2.3646 | 0.7873 / 2.0571 |
| 60 | Alternating | 6.1224 / 20.7821 | 0.4917 / 1.2642 | 0.5978 / 1.5411 |
| 100 | Conventional | 9.7819 / 24.4201 | 0.3483 / 1.0337 | 0.6745 / 1.3244 |
| 100 | Sequential | 2.8286 / 10.5001 | 0.1429 / 0.4159 | 0.1755 / 0.5226 |
| 100 | Alternating | 2.9524 / 9.6607 | 0.1649 / 0.9771 | 0.2018 / 1.1471 |

Sequential pool 60 có **sai số torque trung bình thấp hơn Conventional**, dù sai số torque lớn nhất cao hơn. Không dùng outlier để phủ nhận kết quả trung bình; cũng không dùng trung bình để bỏ qua outlier. PF của Adaptive pool 60 có sai số trung bình cao hơn Conventional.

## Kết luận được giữ lại

- Trong các lượt seed 17 này, cả hai Adaptive tìm được tập FEA có HV tốt hơn Conventional ở cùng ngân sách mỗi mức.
- Ở pool 60, HV verification20 của hai Adaptive cao hơn Conventional khoảng 10%; HV verification20 cũng gần các giá trị tương ứng ở pool 100. Đây là tín hiệu thăm dò về hiệu quả lấy mẫu/tiết kiệm FEA đáng để chuyển sang bài toán động cơ mục tiêu.
- Chất lượng thiết kế tìm được và độ chính xác ANN là hai tiêu chí riêng. Adaptive không thắng mọi chỉ số dự đoán; đặc biệt pool 60 vẫn có sai số torque lớn tại một số điểm.
- Tập validation chỉ có 8 điểm và dùng chọn checkpoint; verification20 được chọn trên Pareto riêng của mỗi phương pháp. Chưa có tập test toàn miền chung độc lập hoặc kết quả nhiều seed. Không biến kết quả thăm dò thành tuyên bố vượt trội phổ quát.
- Không chạy thêm SPM để tìm seed đẹp hoặc làm bảng số liệu thuận lợi hơn. Người dùng quyết định chuyển sang Vernier tại đây.

## Bàn giao sang model Vernier

Tái sử dụng phần tự động hóa, cache/checkpoint, ANN và workflow đã chạy. **Không tự động tái sử dụng dữ liệu SPM làm dữ liệu huấn luyện Vernier**, không gộp archive hoặc so raw HV giữa hai động cơ. Model mới cần danh tính/config/fingerprint và thư mục dữ liệu riêng.

Trước triển khai model mới cần có file model và định nghĩa biến/ràng buộc/điều kiện vận hành của Vernier. Không mặc định giữ 7 biến, giới hạn, chiều dài 100 mm, cấu hình winding hay công thức kiểm tra J của SPM cho Vernier. Chỉ rà soát những phần phụ thuộc model mới; không mở lại chiến dịch test hoặc FEA SPM. Chưa khởi chạy hoặc sửa model Vernier trong bước chốt tài liệu này.


## Nơi lưu bằng chứng

Các thư mục `runs/` được đưa lên Git, gồm dữ liệu FEA, kết quả, checkpoint ANN/NSGA-II, log, báo cáo và biểu đồ. File model Motor-CAD (`.mot`, `.bak`) và thư mục solver `work/` được giữ trên máy local vì dung lượng lớn. Khi chạy mô phỏng trên máy khác, cần cung cấp model Motor-CAD phù hợp và cập nhật đường dẫn trong cấu hình.

- [Báo cáo pool60 + verification20](runs/ann_pool60_ver20_seed17/REPORT.md)
- [Báo cáo pool100 + verification20](runs/ann_pool100_ver20_seed17/REPORT.md)
- [So sánh pool60–100, cùng calibration](runs/ann_pool60_vs100_ver20_seed17/REPORT.md)
- [Direct NSGA-II800 summary](runs/nsga2_L100_20261112_130156_685894/summary.json)
- Các thư mục run lưu `comparison.json`, `correctness_audit.json`, CSV FEA, ANN checkpoint, metrics từng stage, verification từng điểm, log và biểu đồ. Raw files được giữ nguyên để chuyên gia kiểm tra lại.

## Mã và cấu hình đang giữ

- `code/ann_campaign.py`: chương trình Conventional/Adaptive, chỉ giữ quy ước pool + verification cuối riêng.
- `code/motorcad_optimize.py`: Motor-CAD adapter, cache/ledger, DoE và phân tích kết quả.
- `code/nsga2_motorcad.py`: Direct NSGA-II.
- `code/test_*.py`: kiểm thử offline hỗ trợ bảo trì, không tham gia mô phỏng thông thường; không chạy lại trong lần dọn này.
- `config/ann_pool60_ver20_config.json`, `config/ann_pool100_ver20_config.json`: các cấu hình SPM chính đã thực hiện.
- `config/motorcad_config.json`, `config/nsga2_config.json`: cấu hình kết nối/model SPM hiện tại.
- `data/`: initial và calibration HV đã tách khỏi các run budget cũ. Metadata nguồn được giữ để truy xuất.

Các đường dẫn cấu hình và manifest của hai run chính đã chuyển sang nguồn `data/`; `cleanup_migration.json` ghi nhận việc chuyển đường dẫn. Không thay đổi FEA CSV, ANN checkpoint hay giá trị metrics của các run chính. Đây không phải cấu hình Vernier mới; chỉ tiếp tục triển khai khi có model Vernier.
