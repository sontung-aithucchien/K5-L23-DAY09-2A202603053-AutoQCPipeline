"""CHECK 6 — Ý kiến thứ hai: so nhãn với một model LỚN HƠN (yolo26l).   ★★★ (khó nhất, đáng điểm nhất)

Test:  pytest tests/test_second_opinion.py -q

Máy kiểm quy tắc, người kiểm ý nghĩa (slide). Các lỗi như thiếu nhãn / gán nhầm lớp hợp lệ / box lỏng
KHÔNG bắt được bằng quy tắc cú pháp. Ta nhờ một model mạnh hơn "nhìn lại" và CHỈ CẢNH BÁO (model cũng có thể sai):
những ảnh bị cờ sẽ vào hàng đợi cho NGƯỜI duyệt.

`preds[stem]` = list `[id_lớp, conf, cx, cy, w, h]` của model (lấy qua `get_preds(ds, cfg, "checker")` nếu preds=None).
`L = ds.valid_boxes(stem)` = list `(id_lớp, cx, cy, w, h)` của nhãn (đã bỏ dòng hỏng).
Ngưỡng ở `cfg["second_opinion"]`: conf, min_area_px, fp_conf, iou_missing, iou_match, iou_loose.

Thuật toán gợi ý, với từng ảnh (bỏ qua ảnh không có trong preds hoặc không có file nhãn):
  P = dự đoán có conf >= conf  VÀ diện tích px (w*W * h*H) >= min_area_px
  Với mỗi dự đoán r trong P: lấy các nhãn có IoU(r, nhãn) >= iou_missing  (cands)
   - không có cands                            -> POSSIBLE_MISSING     (model thấy vật mà nhãn không có box)
   - có cands cùng lớp, tốt nhất IoU < iou_loose -> POSSIBLE_LOOSE_BOX  (đúng vật, box lỏng/lệch)
   - không có cands cùng lớp, nhưng cands tốt nhất IoU >= iou_match (khác lớp) -> POSSIBLE_WRONG_CLASS
  Với mỗi dòng nhãn hợp lệ: nếu IoU với MỌI dự đoán (conf >= fp_conf, không lọc diện tích) đều < iou_missing
                                             -> POSSIBLE_FALSE_POS  (box nhãn không khớp vật nào model thấy; Issue.line = số dòng)

Chi tiết các ca biên (test kiểm đúng các ca này)
- `cands` gồm nhãn MỌI lớp có IoU >= iou_missing; "tốt nhất cùng lớp" = cands cùng lớp có IoU lớn nhất; "tốt nhất khác lớp" tương tự với cands khác lớp.
- Thứ tự quyết định cho mỗi dự đoán: (1) cands rỗng -> MISSING. (2) có cands cùng lớp: IoU tốt nhất < iou_loose -> LOOSE_BOX, ngược lại KHÔNG cờ
  (nhãn đúng lớp đã phủ vật này, kể cả khi còn nhãn khác lớp chồng lên). (3) không có cands cùng lớp: nếu IoU tốt nhất khác lớp >= iou_match -> WRONG_CLASS;
  nếu chỉ có khác lớp với IoU trong [iou_missing, iou_match) -> không cờ gì (mơ hồ: để cho FALSE_POS / lần duyệt khác).
- Một dự đoán sinh tối đa MỘT issue (MISSING / LOOSE_BOX / WRONG_CLASS); một ảnh có thể có nhiều issue.
- Thứ tự issue: theo `ds.image_files()` rồi theo thứ tự dự đoán trong `preds[stem]`, cuối cùng là các FALSE_POS theo số dòng; `Issue.image` = stem, `Issue.line` chỉ đặt cho FALSE_POS.

Lưu ý số dòng: dùng `ds.read_label_lines(stem)` (giữ số dòng gốc, kể cả dòng hỏng/trống) để lấy `Issue.line`; `valid_boxes` KHÔNG giữ số dòng.

Tất cả severity WARN; `Issue.extra` nên có {"conf": ...} hoặc {"iou": ...} (hàng đợi duyệt dùng conf để xếp ưu tiên).

Gợi ý
- `iou_xywh` có sẵn. Dòng nhãn hỏng không được làm script chết (dùng `ds.valid_boxes` và `parse_yolo_line` trong try).
- Kết quả phụ thuộc mạnh vào ngưỡng: calibrate chúng ở Bước 3 thay vì đoán.
"""
from ..common import WARN, Issue, iou_xywh, parse_yolo_line  # noqa: F401
from ..model_cache import get_preds  # noqa: F401


def run(ds, cfg, preds=None):
    if preds is None:
        preds = get_preds(ds, cfg, "checker")

    c = cfg["second_opinion"]
    conf_thresh = c["conf"]
    min_area_px = c["min_area_px"]
    fp_conf = c["fp_conf"]
    iou_missing = c["iou_missing"]
    iou_match = c["iou_match"]
    iou_loose = c["iou_loose"]

    issues = []

    for img_path in ds.image_files():
        stem = img_path.stem

        # Skip if no preds or no label file
        if stem not in preds:
            continue
        label_lines = ds.read_label_lines(stem)
        if label_lines is None:
            continue

        img_size = ds.image_size(stem)
        if img_size is None:
            continue
        W, H = img_size

        # Get valid label boxes
        L = ds.valid_boxes(stem)  # list of (cls, cx, cy, w, h)

        # Get predictions
        all_preds = preds[stem]  # list of [cls, conf, cx, cy, w, h]

        # Filter predictions for MISSING/LOOSE/WRONG: conf >= conf_thresh AND area >= min_area_px
        P = []
        for r in all_preds:
            r_cls, r_conf, r_cx, r_cy, r_w, r_h = r[0], r[1], r[2], r[3], r[4], r[5]
            if r_conf >= conf_thresh:
                area_px = (r_w * W) * (r_h * H)
                if area_px >= min_area_px:
                    P.append(r)

        # For each prediction in P
        for r in P:
            r_cls, r_conf = int(r[0]), r[1]
            r_box = (r[2], r[3], r[4], r[5])

            # Find candidates: labels with IoU >= iou_missing
            cands = []
            for lab in L:
                lab_cls = lab[0]
                lab_box = (lab[1], lab[2], lab[3], lab[4])
                iou = iou_xywh(r_box, lab_box)
                if iou >= iou_missing:
                    cands.append((lab_cls, iou))

            if not cands:
                # POSSIBLE_MISSING
                issues.append(Issue("second_opinion", WARN, "POSSIBLE_MISSING", stem,
                                    f"model thấy lớp {r_cls} conf={r_conf:.2f} mà nhãn không có box",
                                    extra={"conf": round(r_conf, 4)}))
                continue

            # Check same-class candidates
            same_class = [(iou_val) for (c, iou_val) in cands if c == r_cls]
            if same_class:
                best_iou = max(same_class)
                if best_iou < iou_loose:
                    issues.append(Issue("second_opinion", WARN, "POSSIBLE_LOOSE_BOX", stem,
                                        f"box lỏng IoU={best_iou:.2f} với dự đoán lớp {r_cls}",
                                        extra={"iou": round(best_iou, 4), "conf": round(r_conf, 4)}))
                # else: good match, no issue
                continue

            # No same-class candidates, check different-class
            diff_class = [(c, iou_val) for (c, iou_val) in cands if c != r_cls]
            if diff_class:
                best_diff_cls, best_diff_iou = max(diff_class, key=lambda x: x[1])
                if best_diff_iou >= iou_match:
                    issues.append(Issue("second_opinion", WARN, "POSSIBLE_WRONG_CLASS", stem,
                                        f"nhãn lớp {best_diff_cls} nhưng model nói lớp {r_cls} IoU={best_diff_iou:.2f}",
                                        extra={"conf": round(r_conf, 4), "iou": round(best_diff_iou, 4)}))
                # else: ambiguous (iou in [iou_missing, iou_match)), no flag

        # FALSE_POS: for each valid label line, check if any pred (conf >= fp_conf, no area filter) overlaps
        # Need to map valid boxes back to line numbers
        for lineno, text in label_lines:
            try:
                parsed = parse_yolo_line(text)
            except ValueError:
                continue
            lab_cls = parsed[0]
            if lab_cls < 0 or lab_cls >= len(ds.classes):
                continue
            lab_box = (parsed[1], parsed[2], parsed[3], parsed[4])

            # Check if ANY prediction with conf >= fp_conf has IoU >= iou_missing
            matched = False
            for r in all_preds:
                r_conf = r[1]
                if r_conf < fp_conf:
                    continue
                r_box = (r[2], r[3], r[4], r[5])
                if iou_xywh(lab_box, r_box) >= iou_missing:
                    matched = True
                    break

            if not matched:
                issues.append(Issue("second_opinion", WARN, "POSSIBLE_FALSE_POS", stem,
                                    f"box nhãn dòng {lineno} không khớp dự đoán nào",
                                    line=lineno,
                                    extra={"conf": 0}))

    return issues
