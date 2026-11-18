"""BƯỚC 2/4 — Sửa tự động những lỗi bắt buộc mà máy sửa được AN TOÀN.   ★★

Test:  pytest tests/test_autofix.py -q

`fix(ds, issues, cfg) -> list[dict]`: duyệt `issues` (chỉ lỗi severity ERROR), sửa thẳng vào thư mục `ds`,
và trả về danh sách thay đổi; mỗi phần tử có khoá: image, line, action, before, after
(đây chính là file `03_fixes.csv` — bằng chứng pipeline đã làm gì, người có thể kiểm lại).

| code lỗi                                       | cách sửa                                    | action           |
|------------------------------------------------|---------------------------------------------|------------------|
| BAD_FORMAT, BAD_CLASS_ID, BOX_ZERO, DUP_BOX    | xoá dòng đó khỏi file nhãn                  | "drop_line"      |
| BOX_OUT_OF_IMAGE                               | cắt box về trong [0,1] (giữ nguyên lớp)     | "clip_box"       |
| MISSING_LABEL_FILE                             | KHÔNG sửa file (máy không thể bịa nhãn): ghi 1 dòng fix, before="(không có file)", after="chuyển người gán" | "needs_label" |
| BAD_CLASS_NAME                                 | ghi lại `names` trong data.yaml đúng `cfg["classes"]` | "rename_classes" |
| DUP_IMAGE_*, LEAK_TEST, CORRUPT_IMAGE, BAD_SIZE| xoá ảnh + nhãn khỏi `ds`                    | "remove_image"   |

Bẫy cần nghĩ tới (có test cho từng cái)
- Một file có NHIỀU dòng lỗi: số dòng trong `issues` là số dòng GỐC. Nếu xoá từng dòng một thì số dòng lệch.
  Gom theo file, rồi ghi lại MỘT lần.
- Sau khi cắt, box có thể không còn diện tích (nằm hẳn ngoài ảnh): lúc đó xoá dòng thay vì ghi box rỗng.
- Một dòng có 2 lỗi (vd. BOX_OUT_OF_IMAGE + DUP_BOX): xoá dòng thắng, chỉ ghi 1 fix `drop_line`, không ghi thêm `clip_box`. Dòng trống ở giữa file vẫn đếm vào số dòng gốc.
- Ảnh vừa bị xoá (DUP_IMAGE_*...) mà còn issue dòng của chính nó: bỏ qua êm, không được báo lỗi/chết.
- Không động tới lỗi WARN (cảnh báo là việc của người). Không sửa file ở `data/raw/` — chỉ sửa `ds`.
- Chạy lần 2 trên dữ liệu đã sửa phải không làm gì thêm (idempotent) — NGOẠI LỆ duy nhất: `needs_label` được ghi lại mỗi lần còn lỗi `MISSING_LABEL_FILE` (vì ảnh vẫn chưa có nhãn).

- `needs_label` KHÔNG tạo file nhãn rỗng (rỗng = "ảnh nền", khác với "chưa gán"). `review_queue` sẽ đẩy ảnh này lên đầu hàng đợi cho người.

Gợi ý: `yaml.safe_load / safe_dump`.
"""
from collections import defaultdict  # noqa: F401

import yaml  # noqa: F401

from ..common import ERROR, parse_yolo_line  # noqa: F401


def fix(ds, issues, cfg):
    fixes = []

    # Only process ERROR issues
    error_issues = [i for i in issues if i.severity == ERROR]

    # Group actions by image
    # Determine which images to remove
    remove_codes = {"DUP_IMAGE_EXACT", "DUP_IMAGE_NEAR", "LEAK_TEST", "CORRUPT_IMAGE", "BAD_SIZE"}
    images_to_remove = set()
    for i in error_issues:
        if i.code in remove_codes:
            images_to_remove.add(i.image)

    # Process remove_image first
    for i in error_issues:
        if i.code in remove_codes:
            img_path = ds.image_path(i.image)
            label_path = ds.label_path(i.image)
            before_parts = []
            if img_path and img_path.exists():
                before_parts.append(img_path.name)
                img_path.unlink()
            if label_path.exists():
                before_parts.append(label_path.name)
                label_path.unlink()
            fixes.append({
                "image": i.image,
                "line": "",
                "action": "remove_image",
                "before": ", ".join(before_parts) if before_parts else i.image,
                "after": "(xoá)",
            })

    # Process MISSING_LABEL_FILE -> needs_label (no file created)
    for i in error_issues:
        if i.code == "MISSING_LABEL_FILE":
            fixes.append({
                "image": i.image,
                "line": "",
                "action": "needs_label",
                "before": "(không có file)",
                "after": "chuyển người gán",
            })

    # Process BAD_CLASS_NAME -> rename_classes in data.yaml
    for i in error_issues:
        if i.code == "BAD_CLASS_NAME":
            names = {idx: name for idx, name in enumerate(cfg["classes"])}
            data = yaml.safe_load(ds.yaml_path.read_text(encoding="utf-8")) or {}
            data["names"] = names
            ds.yaml_path.write_text(yaml.safe_dump(data, allow_unicode=True, default_flow_style=False), encoding="utf-8")
            fixes.append({
                "image": "data.yaml",
                "line": "",
                "action": "rename_classes",
                "before": str(i.message),
                "after": str(cfg["classes"]),
            })
            break  # only fix once

    # Group line-level issues by file (drop_line and clip_box)
    line_issues_by_image = defaultdict(dict)  # image -> {lineno -> list of issues}
    for i in error_issues:
        if i.image in images_to_remove:
            continue  # skip issues for removed images
        if i.line is not None and i.code not in {"MISSING_LABEL_FILE", "BAD_CLASS_NAME"}:
            if i.line not in line_issues_by_image[i.image]:
                line_issues_by_image[i.image][i.line] = []
            line_issues_by_image[i.image][i.line].append(i)

    drop_codes = {"BAD_FORMAT", "BAD_CLASS_ID", "BOX_ZERO", "DUP_BOX"}

    for stem in sorted(line_issues_by_image.keys()):
        line_issues = line_issues_by_image[stem]
        label_path = ds.label_path(stem)
        if not label_path.exists():
            continue

        all_lines = label_path.read_text(encoding="utf-8").splitlines()
        new_lines = []
        file_fixes = []

        for idx, line_text in enumerate(all_lines, 1):
            if idx in line_issues:
                codes = {iss.code for iss in line_issues[idx]}
                # If any drop code, drop the line
                if codes & drop_codes:
                    file_fixes.append({
                        "image": stem,
                        "line": idx,
                        "action": "drop_line",
                        "before": line_text,
                        "after": "(xoá)",
                    })
                    continue  # don't add to new_lines
                elif "BOX_OUT_OF_IMAGE" in codes:
                    # Clip box
                    try:
                        cls_id, cx, cy, w, h = parse_yolo_line(line_text)
                    except ValueError:
                        new_lines.append(line_text)
                        continue

                    left = max(0.0, cx - w / 2)
                    top = max(0.0, cy - h / 2)
                    right = min(1.0, cx + w / 2)
                    bottom = min(1.0, cy + h / 2)

                    new_w = right - left
                    new_h = bottom - top

                    if new_w <= 0 or new_h <= 0:
                        # Box fully outside -> drop
                        file_fixes.append({
                            "image": stem,
                            "line": idx,
                            "action": "drop_line",
                            "before": line_text,
                            "after": "(xoá — box nằm hẳn ngoài ảnh)",
                        })
                        continue

                    new_cx = left + new_w / 2
                    new_cy = top + new_h / 2
                    new_text = f"{cls_id} {new_cx:.6f} {new_cy:.6f} {new_w:.6f} {new_h:.6f}"
                    file_fixes.append({
                        "image": stem,
                        "line": idx,
                        "action": "clip_box",
                        "before": line_text,
                        "after": new_text,
                    })
                    new_lines.append(new_text)
                    continue

            new_lines.append(line_text)

        # Write back
        label_path.write_text("\n".join(new_lines) + "\n" if new_lines else "", encoding="utf-8")
        fixes.extend(file_fixes)

    return fixes
