# Kiểm chứng triển khai ngày 12/11/2026

- Đã kiểm tra kết nối và mọi tên input/output qua API Motor-CAD 2025.2.2.
- Chính xác **một lần gọi E-Magnetic** trên một bản sao, gần baseline sau lượng tử hóa. Không chạy chiến dịch DoE/NSGA-II thật.
- Kết quả: Average electromagnetic torque = 8.70066939994197 Nm; phasor PF = 0.989817602426816; MotorEfficiency = 84.5216846555276%.
- ShaftTorque = 8.45972916507941 Nm; SystemEfficiency = 84.5216846555276%; RMS phase terminal voltage = 121.095373163296 V.
- Actual J = 7.000000000000005 A/mm², kiểm tra từ RmsCurrentCalc = 4.3214272240336 A và Copper_Diameter = 0.886583493073646 mm; một parallel path, một strand, winding sao.
- Chiều dài stator/rotor/nam châm và mọi thông số cố định được giữ nguyên. Không bật thêm loss flags, không chỉnh tốc độ/số vòng/thermal assumptions.
- CSV thật: `check/evaluations.csv`. Report: `check/check_report.json`. Pareto/đồ thị: `check/analysis/`.
- Hash .mot và .bak vẫn là `1cfee7718f933e65908a5df30da9003786bd7886edc13f0c6db62a0816a41811`.
- Hash script tham khảo vẫn là `a3e18cf6dfe0719e54dac3acafd71b84956650aecf21143e4250812e04510557`.

Một điểm không chứng minh Pareto hoặc sự đánh đổi. Hiệu suất ở đây thuộc mô hình tổn hao gốc, với OnLoadLossCalculation=False và BackEMFLossCalculation=False; chưa phải kiểm chứng mọi thành phần tổn hao FEA.

Các bài kiểm thử offline dùng dữ liệu giả lập chỉ trong thư mục tạm do unittest tạo, không trộn vào CSV mô phỏng thật. Chúng kiểm tra giới hạn budget/cache, crash accounting, integer grid, J, invariant/readback, Pareto và tính lặp lại của resume giữa thế hệ NSGA-II.
