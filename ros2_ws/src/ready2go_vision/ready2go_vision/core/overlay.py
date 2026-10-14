"""촬영 장면 오버레이(#348): inspect_region 한 번의 컬러 사진 위에 분할 마스크·이름·신뢰도·윗면 높이·가리는 물체·방향을 그린다.
웹 대시보드 '최근 촬영' 칸용 — 결과(result_json)를 바꾸지 않고 그림만 만든다. 서랍 안쪽만 잘라 16:9 로 키워 작은 칸에서도 글씨가 보이게.
글꼴: 한글 글꼴(font_paths 중 있는 것)이 없으면 영어 클래스 이름으로 그린다(비전 이미지에 한글 글꼴이 없을 수 있음)."""
import math
from pathlib import Path

import numpy as np

PALETTE = [(0, 150, 199), (230, 126, 34), (46, 204, 113), (155, 89, 182), (231, 76, 60), (241, 196, 15)]   # RGB
OUT_W, OUT_H = 1280, 720
FONT_PATHS = ("/usr/share/fonts/truetype/nanum/NanumBarunGothicBold.ttf", "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")


def _font(paths, size):
    from PIL import ImageFont
    for p in paths:
        if Path(p).exists():
            return ImageFont.truetype(p, size), "Nanum" in p
    return ImageFont.load_default(), False


def _crop_box(K, T_drawer_cam, interior_m, w, h, margin_px=20):
    """서랍 안쪽 바닥 네 모서리를 이미지에 투영한 범위(+여백)를 16:9 로 넓힌 잘라낼 상자. 투영이 안 되면 전체."""
    try:
        Tc = np.linalg.inv(T_drawer_cam)
        pts = []
        for x in (0.0, interior_m[0]):
            for y in (0.0, interior_m[1]):
                p = Tc[:3, :3] @ np.array([x, y, 0.0]) + Tc[:3, 3]
                if p[2] <= 0:
                    return 0, 0, w, h
                pts.append((K.fx * p[0] / p[2] + K.cx, K.fy * p[1] / p[2] + K.cy))
        us, vs = [p[0] for p in pts], [p[1] for p in pts]
        x0, x1, y0, y1 = min(us) - margin_px, max(us) + margin_px, min(vs) - margin_px, max(vs) + margin_px
    except Exception:
        return 0, 0, w, h
    cw, ch = x1 - x0, y1 - y0
    if cw / ch < OUT_W / OUT_H:
        cw = ch * OUT_W / OUT_H
    else:
        ch = cw * OUT_H / OUT_W
    cw, ch = min(cw, w), min(ch, h)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    x0 = int(round(min(max(cx - cw / 2, 0), w - cw))); y0 = int(round(min(max(cy - ch / 2, 0), h - ch)))
    return x0, y0, int(round(x0 + cw)), int(round(y0 + ch))


def _match(dets, objs, K, T_drawer_cam):
    """결과 물체 → 검출 짝 {검출 번호: 물체}. 물체 위치(서랍 좌표)를 사진에 투영해 같은 클래스 검출 중 마스크(없으면 상자) 안에 들거나
    상자 중심이 가장 가까운 것. 같은 클래스 중복 병합·서랍 밖 제외로 검출과 결과 수가 달라도 엉뚱한 물체에 라벨이 붙지 않게."""
    out = {}
    Tc = np.linalg.inv(T_drawer_cam) if T_drawer_cam is not None else None
    for o in objs:
        cls = o["id"].split("#")[0]
        cand = [i for i, d in enumerate(dets) if d["class"] == cls and i not in out]
        if not cand:
            continue
        if Tc is None:
            out[cand[0]] = o
            continue
        x, y = o["pose"]["position"][:2]
        p = Tc[:3, :3] @ np.array([x, y, (o.get("top_z") or 0) / 2]) + Tc[:3, 3]
        if p[2] <= 0:
            continue
        u, v = K.fx * p[0] / p[2] + K.cx, K.fy * p[1] / p[2] + K.cy

        def score(i):
            d = dets[i]; b = d["box"]; m = d.get("mask")
            inside = (m is not None and 0 <= int(v) < m.shape[0] and 0 <= int(u) < m.shape[1] and bool(m[int(v), int(u)])) or \
                     (m is None and b[0] <= u <= b[2] and b[1] <= v <= b[3])
            return (0 if inside else 1, math.hypot((b[0] + b[2]) / 2 - u, (b[1] + b[3]) / 2 - v))
        out[min(cand, key=score)] = o
    return out


def render_overlay(color_bgr, dets, result, K, T_drawer_cam, interior_m, items, request, shot_text, font_paths=FONT_PATHS, error_code=""):
    """color_bgr: HxWx3 uint8 BGR(노드·덤프의 컬러). dets: 검출(class·conf·box, 분할이면 mask bool HxW).
    result: result_json 을 읽은 dict(실패면 {}). K: Intrinsics. T_drawer_cam: 4x4 또는 None(TF 없음 — 방향 선·잘라내기 안 함).
    items: 온톨로지 world.items. request: {region, search_target}. shot_text: 머리 띠에 쓸 촬영 시각 글자. error_code: 실패 요청의 오류 코드(머리 띠에 표시).
    반환: OUT_H x OUT_W x 3 uint8 RGB."""
    from PIL import Image, ImageDraw
    h, w = color_bgr.shape[:2]
    font, korean = _font(font_paths, 30)
    small, _ = _font(font_paths, 24)
    name = (lambda c: (items.get(c) or {}).get("name_ko", c)) if korean else (lambda c: c)
    if T_drawer_cam is not None and interior_m:
        x0, y0, x1, y1 = _crop_box(K, T_drawer_cam, interior_m, w, h)
    else:
        x0, y0, x1, y1 = 0, 0, w, h
    s = OUT_W / (x1 - x0)
    to_out = lambda u, v: ((u - x0) * s, (v - y0) * s)
    img = Image.fromarray(np.ascontiguousarray(color_bgr[y0:y1, x0:x1, ::-1])).resize((OUT_W, OUT_H), Image.BILINEAR).convert("RGBA")

    objs = ([result["target"]] if result.get("target") else []) + list(result.get("candidates") or [])
    match = _match(dets, objs, K, T_drawer_cam)
    pairs = [(d, match.get(i), PALETTE[i % len(PALETTE)]) for i, d in enumerate(dets)]

    import cv2
    over = Image.new("RGBA", img.size, (0, 0, 0, 0))
    cents = []
    for d, o, col in pairs:
        m = d.get("mask")
        if m is not None and m.any():
            mc = cv2.resize(m[y0:y1, x0:x1].astype(np.uint8), (OUT_W, OUT_H), interpolation=cv2.INTER_NEAREST).astype(bool)
            fill = np.zeros((OUT_H, OUT_W, 4), np.uint8); fill[mc] = (*col, 90)
            over = Image.alpha_composite(over, Image.fromarray(fill))
            od = ImageDraw.Draw(over)
            cs, _ = cv2.findContours(mc.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            for c in cs:
                if len(c) > 2:
                    od.line([tuple(p[0]) for p in c] + [tuple(c[0][0])], fill=(*col, 255), width=4)
            vs, us = np.nonzero(m)
            cents.append(to_out(float(us.mean()), float(vs.mean())))
        else:
            bx = d["box"]
            ImageDraw.Draw(over).rectangle([*to_out(bx[0], bx[1]), *to_out(bx[2], bx[3])], outline=(*col, 255), width=4)
            cents.append(to_out((bx[0] + bx[2]) / 2, (bx[1] + bx[3]) / 2))
        if o and o["pose"].get("yaw_valid") and T_drawer_cam is not None:
            size = (items.get(d["class"]) or {}).get("size_m")
            if size:
                Tc = np.linalg.inv(T_drawer_cam)
                x, y = o["pose"]["position"][:2]; yaw = o["pose"]["yaw"]; L = size[0] / 2; z = (o.get("top_z") or 0) / 2
                ends = []
                for sgn in (-1, 1):
                    p = Tc[:3, :3] @ np.array([x + sgn * L * math.cos(yaw), y + sgn * L * math.sin(yaw), z]) + Tc[:3, 3]
                    ends.append(to_out(K.fx * p[0] / p[2] + K.cx, K.fy * p[1] / p[2] + K.cy))
                ImageDraw.Draw(over).line(ends, fill=(255, 255, 255, 230), width=4)
    img = Image.alpha_composite(img, over)
    dr = ImageDraw.Draw(img)

    boxes = []
    for (d, o, col), c in zip(pairs, cents):
        lines = [f"{name(d['class'])}  {d['conf']:.2f}"]
        if o:
            sub = (f"윗면 높이 {o['top_z'] * 1000:.0f} mm" if korean else f"top {o['top_z'] * 1000:.0f} mm")
            if not o["pose"].get("yaw_valid"):
                sub += " · 방향 모름" if korean else " / yaw unknown"
            ob = o.get("occluded_by")
            if ob:
                sub += (" · 가리는 물체: " if korean else " / under: ") + ", ".join(name(i.split("#")[0]) for i in ob)
            elif ob is not None:
                sub += " · 가리는 물체 없음" if korean else " / not covered"
            lines.append(sub)
        tw = max(dr.textlength(lines[0], font=font), dr.textlength(lines[-1], font=small) if len(lines) > 1 else 0) + 24
        th = 44 + (32 if len(lines) > 1 else 0)
        boxes.append((c, lines, tw, th, col))
    if boxes:
        cx_all = [b[0][0] for b in boxes]
        right = min(max(cx_all) + 120, OUT_W - 8 - max(b[2] for b in boxes))
        left_side = right < max(cx_all) + 40                     # 오른쪽 공간이 없으면 왼쪽에
        y_next = 64
        for c, lines, tw, th, col in sorted(boxes, key=lambda b: b[0][1]):
            ty = min(max(c[1] - th / 2, y_next), OUT_H - th - 8); y_next = ty + th + 14
            tx = max(min(cx_all) - 120 - tw, 8) if left_side else right
            ax = tx + tw if left_side else tx
            dr.line([c, (ax, ty + th / 2)], fill=(*col, 255), width=4)
            dr.ellipse([c[0] - 8, c[1] - 8, c[0] + 8, c[1] + 8], fill=(*col, 255), outline="white", width=3)
            dr.rounded_rectangle([tx, ty, tx + tw, ty + th], 10, fill=(*col, 240), outline="white", width=2)
            dr.text((tx + 12, ty + 6), lines[0], font=font, fill="white")
            if len(lines) > 1:
                dr.text((tx + 12, ty + 44), lines[1], font=small, fill="white")

    reg = request.get("region") or ""
    if korean:
        head = {"drawer_top": "위 칸", "drawer_bottom": "아래 칸", "handover_zone": "전달 트레이"}.get(reg, reg)
        tgt = request.get("search_target")
        head += (f" · 찾는 물건: {name(tgt)}" if tgt else "") + f" · 촬영 {shot_text}"
    else:
        head = f"{reg}" + (f" / target: {request.get('search_target')}" if request.get("search_target") else "") + f" / shot {shot_text}"
    if error_code:
        head += (" · 실패 " if korean else " / failed ") + error_code
    elif not dets:
        head += " · 검출 없음" if korean else " / no detection"
    dr.rectangle([0, 0, OUT_W, 52], fill=(20, 33, 61, 235))
    dr.text((16, 10), head, font=font, fill="white")
    return np.asarray(img.convert("RGB"))


def encode_jpeg(rgb, quality=85) -> bytes:
    import cv2
    ok, buf = cv2.imencode(".jpg", np.ascontiguousarray(rgb[:, :, ::-1]), [cv2.IMWRITE_JPEG_QUALITY, int(quality)])
    if not ok:
        raise RuntimeError("JPEG 인코딩 실패")
    return buf.tobytes()
