"""CHECK 2 — Dòng nhãn YOLO: sai định dạng, ID lớp lạ, box tràn ảnh, box rỗng, box lặp.   (Script 2 trong slide)   ★★

Test:  pytest tests/test_label_format.py -q

Mỗi dòng nhãn: `id cx cy w h` (5 số, toạ độ 0–1). Trả về list[Issue]; `Issue.line` = số dòng (đếm từ 1).

| code             | severity | khi nào                                                                  |
|------------------|----------|--------------------------------------------------------------------------|
| BAD_FORMAT       | ERROR    | không đúng 5 cột số (dùng `parse_yolo_line`, bắt `ValueError`)           |
| BAD_CLASS_ID     | ERROR    | id lớp ngoài 0..len(ds.classes)-1                                        |
| BOX_ZERO         | ERROR    | w <= 0 hoặc h <= 0                                                       |
| BOX_OUT_OF_IMAGE | ERROR    | mép box vượt [0,1] quá `cfg["label_format"]["overflow_tol"]`; extra={"overflow": mức tràn} |
| DUP_BOX          | ERROR    | cùng lớp với một dòng TRƯỚC ĐÓ và IoU > `dup_box_iou`; báo ở dòng SAU    |
| BOX_TINY         | WARN     | cạnh ngắn của box (px) < `min_box_px`  (cần `ds.image_size(stem)`)       |
| BOX_HUGE         | WARN     | w*h > `max_box_frac`                                                     |

Gợi ý
- Mép trái = x - w/2, mép phải = x + w/2 (xem câu hỏi "dòng YOLO nào lỗi?" trong slide).
- Một dòng hỏng (BAD_FORMAT, BAD_CLASS_ID, BOX_ZERO) thì `continue`, đừng kiểm tiếp hình học của dòng đó.
- Dòng thiếu cột làm script của slide dừng giữa chừng: đây là lý do phải `try/except`.
- `iou_xywh(a, b)` có sẵn trong common.py.
- Ngưỡng nằm trong `cfg["label_format"]` — đừng viết cứng số vào code.
"""
from ..common import ERROR, WARN, Issue, iou_xywh, parse_yolo_line  # noqa: F401


def run(ds, cfg):
    c = cfg["label_format"]
    overflow_tol = c["overflow_tol"]
    min_box_px = c["min_box_px"]
    max_box_frac = c["max_box_frac"]
    dup_box_iou = c["dup_box_iou"]
    num_classes = len(ds.classes)
    issues = []

    for lf in ds.label_files():
        stem = lf.stem
        img_size = ds.image_size(stem)  # (W, H) or None
        label_lines = ds.read_label_lines(stem)
        if label_lines is None:
            continue

        valid_boxes = []  # list of (class_id, cx, cy, w, h, line_no)

        for lineno, text in label_lines:
            # Parse
            try:
                cls_id, cx, cy, w, h = parse_yolo_line(text)
            except ValueError:
                issues.append(Issue("label_format", ERROR, "BAD_FORMAT", stem,
                                    f"dòng không đúng 5 cột số: {text[:60]}", line=lineno))
                continue

            # BAD_CLASS_ID
            if cls_id < 0 or cls_id >= num_classes:
                issues.append(Issue("label_format", ERROR, "BAD_CLASS_ID", stem,
                                    f"id lớp {cls_id} ngoài 0..{num_classes - 1}", line=lineno,
                                    extra={"class_id": cls_id}))
                continue

            # BOX_ZERO
            if w <= 0 or h <= 0:
                issues.append(Issue("label_format", ERROR, "BOX_ZERO", stem,
                                    f"box rỗng w={w} h={h}", line=lineno))
                continue

            # BOX_OUT_OF_IMAGE
            left = cx - w / 2
            top = cy - h / 2
            right = cx + w / 2
            bottom = cy + h / 2
            overflow = max(-left, -top, right - 1, bottom - 1, 0)
            if overflow > overflow_tol:
                issues.append(Issue("label_format", ERROR, "BOX_OUT_OF_IMAGE", stem,
                                    f"box tràn {overflow:.4f}", line=lineno,
                                    extra={"overflow": round(overflow, 6)}))
                # still check dup/tiny/huge below? No - spec says continue after fatal
                # But the test shows broken line does not crash AND other lines still checked
                # BOX_OUT_OF_IMAGE is ERROR so we still add to valid_boxes for dup check
                # Actually looking at test: test_line_with_two_errors_is_dropped_once
                # means a line can have both BOX_OUT_OF_IMAGE and DUP_BOX
                # So we should NOT continue here - let it also check DUP_BOX
                # But the docstring says "Một dòng hỏng (BAD_FORMAT, BAD_CLASS_ID, BOX_ZERO) thì continue"
                # BOX_OUT_OF_IMAGE is not in that list, so we don't continue

            # DUP_BOX - check against valid_boxes with same class
            is_dup = False
            for prev_cls, prev_cx, prev_cy, prev_w, prev_h, _ in valid_boxes:
                if prev_cls == cls_id:
                    iou = iou_xywh((cx, cy, w, h), (prev_cx, prev_cy, prev_w, prev_h))
                    if iou > dup_box_iou:
                        issues.append(Issue("label_format", ERROR, "DUP_BOX", stem,
                                            f"box lặp IoU={iou:.3f}", line=lineno,
                                            extra={"iou": round(iou, 4)}))
                        is_dup = True
                        break

            # BOX_TINY / BOX_HUGE (WARN) - only if no fatal error on this line
            if img_size is not None and not is_dup:
                W, H = img_size
                box_w_px = w * W
                box_h_px = h * H
                short_side = min(box_w_px, box_h_px)
                if short_side < min_box_px:
                    issues.append(Issue("label_format", WARN, "BOX_TINY", stem,
                                        f"cạnh ngắn {short_side:.1f}px < {min_box_px}px", line=lineno,
                                        extra={"min_side_px": round(short_side, 2)}))
                if w * h > max_box_frac:
                    issues.append(Issue("label_format", WARN, "BOX_HUGE", stem,
                                        f"box chiếm {w * h:.2%} ảnh", line=lineno,
                                        extra={"area_frac": round(w * h, 4)}))

            valid_boxes.append((cls_id, cx, cy, w, h, lineno))

    return issues
