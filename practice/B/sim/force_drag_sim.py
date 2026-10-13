"""넛지 누르기·끌기 — 위치 방식(지금 기본) vs 힘 제어(drag.force_mode) 1차원 접촉 모델 비교
[추정 모델 — 실물 검증 전. 사용자 10/13 "시뮬 돌려서 기존 방식보다 좋으면 그렇게"].

물체 윗면을 스프링으로 봄: 누르는 힘 F = k · max(0, 윗면 − 손끝 z)
  k: 단단한 물체 8 N/mm [실측 B 10/06 "위치로 누르면 1 mm 에 2 → 10 N"], 빈 상자 0.3 N/mm [추정]
A. 접촉 찾기 — 예상 윗면 위 3 mm 에서 시작 (실제 윗면은 비전 오차·물체 모양으로 다를 수 있음)
  - 위치: 2 mm/s 로 내려가며 힘 5 N(touch_force_n) 넘으면 닿음, 예상 윗면 아래 4 mm(search_below_mm)까지 — 그 뒤 멈춘 채 3번 확인
          (휘는 물체는 멈춘 동안 힘이 빠짐 [실측 10/13 트러블슈팅 1] → 확인 실패로 봄: 이완율 creep 이 있으면 5 N 아래로)
  - 힘 제어: 목표 힘(0.85 N)이 될 때까지 내려감, 예상 윗면 아래 12 mm(force_search_below_mm)까지
B. 끄는 동안 유지 — 물체는 손끝과 같이 움직이므로 손끝 아래 윗면 높이는 서랍 바닥 기울기만큼 바뀜
  - 위치: 처음 맞춘 높이 고정(수평 직선), 힘 제어: z 를 1차 지연 τ 로 목표 힘 높이로 따라감
  끌림 = F ≥ 0.3 N, 멈춤 = F > 10 N(drag.max_force_z_n)
  python3 practice/B/sim/force_drag_sim.py
"""
F_TARGET, F_TOUCH, F_MIN, F_MAX = 0.85, 5.0, 0.3, 10.0
SEARCH_POS_MM, SEARCH_FORCE_MM, START_ABOVE_MM = 4.0, 12.0, 3.0
TAU_S, SPEED_MM_S, DT = 0.05, 10.0, 0.002


def find_contact(actual_off_mm, k, creep, mode):
    """actual_off_mm: 실제 윗면 − 예상 윗면 (음수 = 실제가 더 낮음). → (닿음, 닿았을 때 힘 N)."""
    if mode == "pos":
        z_need = actual_off_mm - F_TOUCH / k              # 5 N 이 되는 손끝 높이 (예상 윗면 기준)
        if z_need < -SEARCH_POS_MM:
            return False, 0.0                              # 찾는 깊이 안에서 5 N 못 만듦
        if creep > 0 and F_TOUCH * (1 - creep) < F_TOUCH:  # 멈춘 채 확인하는 동안 힘이 빠짐 (휘는 상자)
            return False, F_TOUCH * (1 - creep)
        return True, F_TOUCH
    z_need = actual_off_mm - F_TARGET / k
    return (z_need >= -SEARCH_FORCE_MM), F_TARGET


def hold_while_drag(tilt_mm, k, dist_mm, mode):
    z = -F_TARGET / k                                      # 처음 맞춘 높이 (윗면 0 기준)
    t, x, fs = 0.0, 0.0, []
    while x <= dist_mm:
        top = -tilt_mm * x / dist_mm                       # 바닥 기울기만큼 물체 윗면이 내려감
        if mode == "force":
            z += ((top - F_TARGET / k) - z) * min(1.0, DT / TAU_S)
        fs.append(k * max(0.0, top - z))
        t += DT
        x = SPEED_MM_S * t
    ok = sum(F_MIN <= f <= F_MAX for f in fs) / len(fs)
    return ok, min(fs), max(fs)


CONTACT_CASES = [("지우개, 비전 높이 맞음", 0.0, 8.0, 0.0), ("지우개, 비전 높이 +2.5 mm 높게 봄", -2.5, 8.0, 0.0),
                 ("몽키 머리 (윗면이 top_z 보다 4~5 mm 낮음)", -5.0, 8.0, 0.0),
                 ("빈 캐러멜 상자 (부드러움·누르면 힘 빠짐)", 0.0, 0.3, 0.3), ("빈 칸 (물체 없음, 바닥 12 mm 아래)", -20.0, 8.0, 0.0)]
DRAG_CASES = [("서랍 바닥 기울기 0.5 mm / 40 mm", 0.5, 8.0), ("기울기 1.0 mm / 40 mm", 1.0, 8.0),
              ("빈 상자 + 기울기 0.5 mm", 0.5, 0.3)]

if __name__ == "__main__":
    print("A. 접촉 찾기")
    for name, off, k, creep in CONTACT_CASES:
        r = {m: find_contact(off, k, creep, m) for m in ("pos", "force")}
        print(f"  {name:<34} 위치: {'닿음' if r['pos'][0] else '실패'}   힘제어: {'닿음' if r['force'][0] else '실패(정상 거부)' if off <= -SEARCH_FORCE_MM else '실패'}")
    print("B. 끄는 동안 힘 유지 (정상 끌림 %, 힘 min~max N)")
    for name, tilt, k in DRAG_CASES:
        r = {m: hold_while_drag(tilt, k, 40.0, m) for m in ("pos", "force")}
        print(f"  {name:<34} 위치: {r['pos'][0] * 100:5.1f}% ({r['pos'][1]:.2f}~{r['pos'][2]:.2f})   "
              f"힘제어: {r['force'][0] * 100:5.1f}% ({r['force'][1]:.2f}~{r['force'][2]:.2f})")
