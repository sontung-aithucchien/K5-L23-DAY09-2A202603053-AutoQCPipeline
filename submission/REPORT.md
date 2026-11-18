# Báo cáo Day 09 — Nguyễn Sơn Tùng, 2A202603053

## 1. Kết luận trước
Pipeline đưa ra kết luận **HOLD** (mã thoát 10). Tổng số ảnh đầu vào là **224 ảnh** từ lô `raw/`, qua cửa nhận dữ liệu (intake) loại bỏ 21 ảnh lỗi, giữ lại **203 ảnh** đưa vào quy trình QC và xuất ra dataset sạch nháp tại `submission/export/clean_v1/`. Pipeline không bị Rework do đã sạch 100% lỗi bắt buộc (`n_errors = 0`), nhưng phải dừng ở mức Hold do còn **44/203 ảnh (21.67%)** có cảnh báo ngữ nghĩa chưa được người duyệt, vượt ngưỡng quy định 10%.

## 2. Lỗi và phân việc
Tổng hợp lỗi từ báo cáo `02_error_list_v1` (trên tổng số 203 ảnh nhận vào):

| Mã lỗi | Số ảnh/dòng | Ai sửa (máy/người) | Vì sao |
|---|---:|---|---|
| `BAD_SIZE` | 3 ảnh | Máy (intake) | Cạnh ngắn < 250px không đủ tiêu chuẩn độ phân giải của dự án; máy tự loại bỏ. |
| `CORRUPT_IMAGE` | 2 ảnh | Máy (intake) | File ảnh bị hỏng/cắt cụt không mở được bằng thư viện ảnh; máy tự loại bỏ. |
| `DUP_IMAGE_EXACT` | 8 ảnh | Máy (intake) | Trùng từng byte (MD5) với ảnh đã nhận trước đó; máy tự loại bỏ để tránh lặp dữ liệu. |
| `DUP_IMAGE_NEAR` | 3 ảnh | Máy (intake) | Trùng gần đúng (khoảng cách pHash ≤ 6) do thu nhỏ/đổi sáng; máy tự loại bỏ. |
| `LEAK_TEST` | 5 ảnh | Máy (intake) | Trùng với ảnh trong tập `test/` hoặc `gold_val/`; máy loại bỏ ngay để chống rò rỉ dữ liệu. |
| `BAD_FORMAT` | 3 dòng | Máy (autofix) | Dòng thiếu cột hoặc chứa NaN không parse được; máy tự động xoá dòng (`drop_line`). |
| `BAD_CLASS_ID` | 6 dòng | Máy (autofix) | ID lớp ngoài dải 0..3 (chứa 93, 4, -1); máy tự động xoá dòng (`drop_line`). |
| `BOX_ZERO` | 4 dòng | Máy (autofix) | Box có width hoặc height bằng 0 (suy biến); máy tự động xoá dòng (`drop_line`). |
| `BOX_OUT_OF_IMAGE` | 8 dòng | Máy (autofix) | Toạ độ mép tràn ngoài [0, 1] vượt dung sai; máy cắt an toàn về [0, 1] (`clip_box`). |
| `DUP_BOX` | 7 dòng | Máy (autofix) | Trùng lặp cùng lớp với box trước có IoU > 0.9; máy tự động xoá dòng sau (`drop_line`). |
| `BAD_CLASS_NAME` | 2 lỗi | Máy (autofix) | Tên lớp trong `data.yaml` viết hoa sai (`Person`, `Bus`); máy ghi lại chuẩn (`rename_classes`). |
| `MISSING_LABEL_FILE` | 6 ảnh | Người (review) | Máy không thể tự bịa nhãn; đánh dấu `needs_label` đưa lên đầu hàng đợi để người gán. |
| `BOX_TINY` | 6 dòng | Người (review) | Box có cạnh ngắn < 12px; chuyển người kiểm tra xem là vật thể xa hay viền nhiễu. |
| `BOX_HUGE` | 3 dòng | Người (review) | Box chiếm > 95% diện tích ảnh; chuyển người xác nhận có phải đối tượng hợp lệ. |
| `CLASS_RARE` | 4 cảnh báo | Người (review) | Cảnh báo mất cân bằng dữ liệu cấp dataset cho quản lý dự án. |
| `EMPTY_LABEL` | 12 ảnh | Người (review) | File nhãn rỗng; chuyển người phân định là ảnh nền (background) hay bỏ sót nhãn. |
| `POSSIBLE_WRONG_CLASS` | 18 box | Người (review) | Model ý kiến thứ hai nghi ngờ gán nhầm lớp (hệ số ưu tiên 3); người cần sửa nhãn. |
| `POSSIBLE_MISSING` | 68 box | Người (review) | Model nghi ngờ bỏ sót vật thể (hệ số 2); người cần bổ sung box. |
| `POSSIBLE_FALSE_POS` | 29 dòng | Người (review) | Nhãn có box mà model không phát hiện vật thể (hệ số 2); người cần kiểm tra. |
| `POSSIBLE_LOOSE_BOX` | 31 box | Người (review) | Khớp lớp nhưng IoU < 0.5 (hệ số 1.5); người cần chỉnh lại khung bounding box. |

**Giải thích hàng đợi `05_review_queue.csv`:**
- Hàng đợi gồm **130 ảnh** được sắp xếp theo tổng điểm trọng số lỗi giảm dần. Sáu ảnh thiếu file nhãn (`MISSING_LABEL_FILE`) được gán trọng số cao nhất (`NEEDS_LABEL`: 10) nên luôn đứng đầu danh sách duyệt, đảm bảo người gán nhãn trước tiên để loại bỏ lỗi bắt buộc. Tiếp sau đó là các ảnh chứa lỗi ngữ nghĩa nặng: gán nhầm lớp (`POSSIBLE_WRONG_CLASS`: 3), sót box (`POSSIBLE_MISSING`: 2) và box thừa (`POSSIBLE_FALSE_POS`: 2).
- Với ngân sách **80 ảnh**, người duyệt đã xử lý toàn bộ 6 ảnh thiếu nhãn và 74 ảnh chứa lỗi ngữ nghĩa nghiêm trọng nhất. Kết quả sau duyệt: số cảnh báo của checker giảm từ 146 xuống còn 74 cảnh báo, giải quyết triệt để lỗi trên 86 ảnh. Tuy nhiên, 44 ảnh còn lại chưa kịp duyệt vẫn chiếm 21.67% tổng số ảnh, khiến pipeline dừng ở mức Hold.

## 3. Calibration (2 ngưỡng)
| Tham số | Khởi đầu | Đã chọn | Precision / Recall (trước → sau) | Lý do (đánh đổi) |
|---|---|---|---|---|
| `duplicates.phash_dist` | 2 | 6 | DUP_IMAGE_NEAR: 1.00 / 0.50 → 1.00 / 0.67 (calib) | Tăng recall để bắt ảnh trùng qua resize nhẹ (như `img_0223` của `img_0077` có dist=6) và rò rỉ test (`img_0221`), trong khi vẫn giữ Precision tuyệt đối 1.00 (không xóa nhầm ảnh tốt). |
| `second_opinion.conf` | 0.25 | 0.50 | MISSING: 0.50 / 1.00 → 0.57 / 1.00; WRONG_CLASS: 0.56 / 0.83 → 0.56 / 0.83 | Tăng Precision từ 0.50 lên 0.57 giúp giảm cảnh báo giả chuyển cho người duyệt, đồng thời giữ nguyên 100% Recall đối với lỗi bỏ sót vật thể (MISSING). Không chọn conf > 0.6 vì Recall sẽ sụt giảm (0.88 ở 0.7 và 0.75 ở 0.8). |

**Một chỗ calibration có thể đánh lừa bạn (Calibration Trap):**
- Khi nhìn sweep trên `data/calib/`, ngưỡng `phash_dist = 16` đạt Recall cao nhất (0.83 so với 0.67) mà Precision vẫn là 1.00. Điều này dễ đánh lừa rằng ngưỡng 16 là tối ưu nhất.
- Nhưng thực tế: `calib` chỉ có 39 ảnh nhỏ và không có kho ảnh tham chiếu test đối chiếu, nên không gian băm 64-bit chưa xuất hiện đụng độ băm (hash collision). Khi mang `phash_dist = 16` sang áp dụng trên dữ liệu `raw` (224 ảnh) và kho test (140 ảnh), số ảnh bị cờ trùng/rò rỉ vọt từ 16 lên 26 ảnh:
  - Cụ thể: `img_0013` bị gán `LEAK_TEST` nhầm với `test/test_087.jpg` dù độ lệch pixel trung bình lên tới 114.56 (hai bức ảnh nội dung hoàn toàn khác nhau).
  - Tương tự, `img_0011` bị cờ trùng với `img_0008` (độ lệch pixel 66.21).
- Vì trùng ảnh là lỗi nghiêm trọng tự động loại bỏ (`remove_image`), nếu tin vào calib mà đặt ngưỡng 16, pipeline sẽ xóa oan ít nhất 9 ảnh sạch khỏi dataset. Do đó, phải giữ `phash_dist = 6` để đảm bảo Precision = 1.00 trên dữ liệu thật.

## 4. Cửa chặn và điều pipeline KHÔNG bắt được
**(a) Chứng minh cửa chặn (Gate) hoạt động đúng:**
- Khi chạy thử nghiệm với ngân sách duyệt bằng 0: `python -m pipeline.run --budget 0 --reports work/rep_nb --export-dir work/exp_nb`, toàn bộ 6 ảnh thiếu file nhãn (`MISSING_LABEL_FILE`) không có người duyệt gán nhãn, dẫn đến lỗi bắt buộc ở vòng 3 còn nguyên (`n_errors = 6`).
- Cửa chặn ngay lập tức đưa ra kết luận **REWORK** và thoát với mã **20**. Pipeline dừng lại và hoàn toàn **không xuất** thư mục dataset (`work/exp_nb/clean_v1`), ngăn chặn 100% việc phát hành dữ liệu phế phẩm.

**(b) Ít nhất 2 điểm mù của pipeline có bằng chứng thực tế:**
1. *Box lỏng nhẹ hoặc lệch viền:* Kiểm tra cú pháp không thể đánh giá độ ôm sát của bounding box. Model checker chỉ cờ `POSSIBLE_LOOSE_BOX` khi IoU < `iou_loose` (0.50). Những bounding box bị vẽ lỏng tay hoặc lệch biên vừa phải (IoU đạt 0.55 – 0.70) hoàn toàn bị bỏ sót và được coi là nhãn tốt.
2. *Lỗi nhầm lẫn mà cả người gán lẫn model ý kiến thứ hai (yolo26l) đều mắc phải:* Đối với các vật thể bị che khuất nặng hoặc góc chụp phức tạp (ví dụ xe tải nhỏ bị nhầm thành ô tô con `car`), nếu model ý kiến thứ hai cũng dự đoán sai theo cùng cách đó thì checker sẽ đồng thuận ngầm (agreement is silent), lỗi ngữ nghĩa này sẽ lọt lưới hoàn toàn.
3. *Ảnh trùng lặp bị biến đổi quá mạnh:* Để tránh đụng độ băm xóa nhầm ảnh, ngưỡng `phash_dist` phải ghim ở mức 6. Do đó, các ảnh bị crop > 50%, xoay góc hoặc chỉnh màu biến dạng mạnh sẽ có khoảng cách pHash > 6 và pipeline không thể phát hiện trùng lặp.

## 5. Train: raw vs clean (tùy chọn, chấm riêng)
Chưa chạy (bỏ qua phần train tùy chọn để tập trung kiểm định phần lõi pipeline; đánh giá bằng `make check-core`).

## 6. Quyết định và ghi chú AI
**(a) Quyết định cuối:**
- Quyết định hiện tại: **HOLD**.
- Điều kiện để chuyển thành **RELEASE**: Cần tăng ngân sách duyệt của con người (`budget_images`) từ 80 ảnh lên ít nhất 110 ảnh (duyệt thêm khoảng 24 ảnh trong số 44 ảnh còn cảnh báo), đưa tỉ lệ ảnh nghi ngờ xuống dưới 10% ($\le 20/203 \approx 9.85\%$). Sau khi reviewer hoàn tất gán/sửa nhãn cho nhóm ảnh này, chạy lại pipeline sẽ tự động phát hành bản Release chính thức.

**(b) Ghi chú sử dụng AI:**
- *Prompt chính:* Yêu cầu triển khai 4 module theo phong cách TDD (`label_format.py`, `gate.py`, `autofix.py`, `second_opinion.py`) dựa trên docstring và quy chuẩn slide Day 09, đảm bảo pass toàn bộ unit test và không làm ảnh hưởng thư mục `data/raw/`.
- *Cách kiểm tra code do AI sinh ra:* Chạy liên tục bộ kiểm thử tự động 79 test (`pytest -q`), đối chiếu kết quả sweep calibration trên bộ dữ liệu kiểm định `data/calib/`, và chạy công cụ quét lỗi tĩnh `scripts/check_submission.py --no-train`.
- *Một lần AI sai và cách khắc phục:* Ở module `label_format.py`, AI ban đầu đặt lệnh `continue` ngay sau khi phát hiện lỗi `BOX_OUT_OF_IMAGE`. Điều này khiến các lỗi phía sau trên cùng dòng như `DUP_BOX` bị bỏ qua. Tôi đã phát hiện thông qua test case `test_line_with_two_errors_is_dropped_once` và sửa lại để không thoát sớm, đảm bảo bắt đủ cả hai lỗi trên cùng một dòng.
