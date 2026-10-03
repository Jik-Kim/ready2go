#!/usr/bin/env python3
"""촬영 세션 수집 (담당 A, #14). 손목 카메라의 컬러·정렬 뎁스를 한 세션 폴더에 저장한다.

세션 = 물품 배치 하나(배치를 바꾸면 새 세션). 학습/검증 분할은 세션 단위로 하므로 폴더를 섞지 않는다.
실행(ROS 환경, realsense 컨테이너가 떠 있는 상태):
  python3 tools/yolo/capture_session.py s01_basic --note "시계·지갑·키, 겹침 없음, 조명 고정" --interval 1.0 --count 30
  # --interval 0 이면 Enter 키를 누를 때마다 1장 저장, q + Enter 로 종료
저장: data/raw/<세션>/images/NNNN.png (컬러 BGR), depth/NNNN.png (16bit, 단위 mm), session.yaml
이 스크립트는 로봇에 어떤 명령도 보내지 않는다(구독만). 로봇 이동은 B의 `drawer_top_view` 포즈 사용.
"""
import argparse
import sys
import threading
import time
from pathlib import Path

import cv2
import numpy as np
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image

ROOT = Path(__file__).resolve().parents[2]


def to_array(msg: Image) -> np.ndarray:
    """cv_bridge 없이 Image → numpy (rgb8/bgr8/16UC1)."""
    buf = np.frombuffer(msg.data, dtype=np.uint8)
    if msg.encoding in ("rgb8", "bgr8"):
        img = buf.reshape(msg.height, msg.step // 3, 3)[:, : msg.width]
        return img[:, :, ::-1] if msg.encoding == "rgb8" else img
    if msg.encoding == "16UC1":
        return buf.view(np.uint16).reshape(msg.height, msg.step // 2)[:, : msg.width]
    raise ValueError(f"지원하지 않는 인코딩: {msg.encoding}")


class Capture(Node):
    def __init__(self, color_topic, depth_topic):
        super().__init__("capture_session")
        self.color = self.depth = None
        self.create_subscription(Image, color_topic, lambda m: setattr(self, "color", m), 1)
        self.create_subscription(Image, depth_topic, lambda m: setattr(self, "depth", m), 1)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("session", help="세션 이름 (예: s01_basic)")
    ap.add_argument("--note", default="", help="배치·조명 등 메모 (session.yaml 에 기록)")
    ap.add_argument("--interval", type=float, default=0.0, help="초. 0이면 Enter 로 수동 저장")
    ap.add_argument("--count", type=int, default=0, help="--interval 사용 시 저장할 장수")
    ap.add_argument("--out", default=str(ROOT / "data/raw"))
    ap.add_argument("--color-topic", default="/wrist_cam/color/image_raw")
    ap.add_argument("--depth-topic", default="/wrist_cam/aligned_depth_to_color/image_raw")
    args = ap.parse_args()

    sess = Path(args.out) / args.session
    if (sess / "images").exists() and any((sess / "images").iterdir()):
        sys.exit(f"이미 사진이 있는 세션입니다: {sess} (다른 이름을 쓰세요)")
    (sess / "images").mkdir(parents=True, exist_ok=True)
    (sess / "depth").mkdir(exist_ok=True)

    rclpy.init()
    node = Capture(args.color_topic, args.depth_topic)
    executor = rclpy.executors.SingleThreadedExecutor()
    executor.add_node(node)
    spin = threading.Thread(target=executor.spin, daemon=True)
    spin.start()
    t0 = time.time()
    while (node.color is None or node.depth is None) and time.time() - t0 < 10:
        time.sleep(0.1)
    if node.color is None or node.depth is None:
        executor.shutdown()
        sys.exit("10초 동안 카메라 토픽이 없습니다. realsense 컨테이너와 ROS_DOMAIN_ID/CYCLONEDDS_URI 를 확인하세요.")

    n = 0

    def save():
        nonlocal n
        c, d = node.color, node.depth
        cv2.imwrite(str(sess / "images" / f"{n:04d}.png"), np.ascontiguousarray(to_array(c)))
        cv2.imwrite(str(sess / "depth" / f"{n:04d}.png"), np.ascontiguousarray(to_array(d)))
        n += 1
        print(f"[capture] {n}장 저장 ({args.session})", flush=True)

    if args.interval > 0:
        while not args.count or n < args.count:
            save()
            time.sleep(args.interval)
    else:
        print("Enter = 1장 저장, q + Enter = 종료", flush=True)
        while input().strip().lower() != "q":
            save()

    import yaml
    (sess / "session.yaml").write_text(yaml.safe_dump(
        {"session": args.session, "note": args.note, "images": n, "color_topic": args.color_topic,
         "depth_topic": args.depth_topic, "captured": time.strftime("%Y-%m-%d %H:%M:%S")},
        allow_unicode=True, sort_keys=False), encoding="utf-8")
    print(f"[capture] 완료: {n}장 → {sess}", flush=True)
    executor.shutdown()
    spin.join(timeout=2)
    node.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    main()
