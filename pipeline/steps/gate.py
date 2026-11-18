"""BƯỚC 4 — Cửa chặn: quyết định Release / Hold / Rework.   ★

Test:  pytest tests/test_gate.py -q

Cây quyết định Day 07 (slide Day 09: "Lỗi bắt buộc chặn pipeline; lỗi cảnh báo chuyển người xem"):

  còn ≥ 1 lỗi bắt buộc (severity ERROR)                          -> "Rework"
  không còn lỗi bắt buộc, nhưng tỉ lệ ẢNH còn cảnh báo
      >= cfg["gate"]["warn_ratio_hold"]                          -> "Hold"
  còn lại                                                        -> "Release"

Tỉ lệ cảnh báo = (số ẢNH khác nhau có ≥ 1 cảnh báo) / (tổng số ảnh).  Chú ý:
- chỉ đếm issue có `image` nằm trong `image_stems` (bỏ "<dataset>", "data.yaml");
- bỏ qua ảnh nằm trong `reviewed` (người đã xem, cảnh báo của ảnh đó coi như đã xử lý) — nhưng LỖI BẮT BUỘC thì không bao giờ được bỏ qua;
- mẫu số là số ảnh, không phải số issue.

Trả về dict: decision, n_errors, n_warn_images, n_images, warn_ratio (làm tròn 4 chữ số), reasons (list[str], giải thích bằng tiếng Việt, có số liệu).
"""
from ..common import ERROR, WARN  # noqa: F401


def decide(issues, image_stems, cfg, reviewed=frozenset()):
    stems_set = set(image_stems)
    n_images = len(image_stems)

    # Count errors (never ignored by reviewed)
    n_errors = sum(1 for i in issues if i.severity == ERROR)

    # Count distinct images with warnings (excluding reviewed, <dataset>, data.yaml, and images not in stems)
    warn_images = set()
    for i in issues:
        if i.severity == WARN and i.image in stems_set and i.image not in reviewed:
            warn_images.add(i.image)
    n_warn_images = len(warn_images)

    # Warn ratio
    warn_ratio = round(n_warn_images / n_images, 4) if n_images > 0 else 0

    # Decision tree
    reasons = []
    if n_errors > 0:
        decision = "Rework"
        reasons.append(f"Còn {n_errors} lỗi bắt buộc (severity ERROR) chưa sửa")
    elif warn_ratio >= cfg["gate"]["warn_ratio_hold"]:
        decision = "Hold"
        reasons.append(f"{n_warn_images}/{n_images} ảnh ({warn_ratio:.1%}) còn cảnh báo chưa người duyệt, >= ngưỡng {cfg['gate']['warn_ratio_hold']:.0%}")
    else:
        decision = "Release"
        if n_warn_images > 0:
            reasons.append(f"{n_warn_images}/{n_images} ảnh còn cảnh báo ({warn_ratio:.1%}), dưới ngưỡng")
        else:
            reasons.append("Không còn lỗi hay cảnh báo")

    return {
        "decision": decision,
        "n_errors": n_errors,
        "n_warn_images": n_warn_images,
        "n_images": n_images,
        "warn_ratio": warn_ratio,
        "reasons": reasons,
    }
