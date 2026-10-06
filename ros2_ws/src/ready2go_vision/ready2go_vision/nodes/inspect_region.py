"""/vision/inspect_region 실제 노드: 손목 카메라 컬러·정렬 뎁스 + YOLO + 뎁스 덩어리 → result_json (core/inspect_real.py).

요청이 올 때 요청 이후에 도착한 프레임 한 쌍을 쓰고(오래된 프레임 방지), 광학 프레임의 서랍 좌표 변환은
TF base_link→광학 프레임(실시간)과 config/places.yaml 의 drawer_top.tf(서랍 정본)로 계산한다.
오류 코드: UNKNOWN_REGION, CAMERA_TIMEOUT, TF_UNAVAILABLE, DEPTH_INVALID, RESULT_INVALID (docs/runner.md).
"""
import json
import threading
import time
from pathlib import Path

import numpy as np
import rclpy
import yaml
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from rclpy.time import Time
from sensor_msgs.msg import CameraInfo, Image
from tf2_ros import Buffer, TransformListener

from ready2go_interfaces.srv import InspectRegion
from ready2go_vision.core.detector import YoloDetector
from ready2go_vision.core.geometry import Intrinsics, drawer_from_camera, make_T
from ready2go_vision.core.inspect_real import inspect_scene


def image_to_numpy(msg: Image):
    """cv_bridge 없이 변환. 컬러는 BGR uint8, 뎁스(16UC1 mm 또는 32FC1 m)는 m float."""
    buf = np.frombuffer(msg.data, dtype=np.uint8)
    if msg.encoding in ("bgr8", "rgb8"):
        img = buf.reshape(msg.height, msg.step)[:, :msg.width * 3].reshape(msg.height, msg.width, 3)
        return img[:, :, ::-1].copy() if msg.encoding == "rgb8" else img.copy()
    if msg.encoding == "16UC1":
        return np.frombuffer(msg.data, dtype=np.uint16).reshape(msg.height, msg.width).astype(np.float64) / 1000.0
    if msg.encoding == "32FC1":
        return np.frombuffer(msg.data, dtype=np.float32).reshape(msg.height, msg.width).astype(np.float64)
    raise ValueError(f"지원하지 않는 이미지 인코딩: {msg.encoding}")


def tf_to_T(ts):
    t, q = ts.transform.translation, ts.transform.rotation
    return make_T([t.x, t.y, t.z], [q.x, q.y, q.z, q.w])


class InspectRegionNode(Node):
    def __init__(self):
        super().__init__("inspect_region")
        d = self.declare_parameter
        d("config_dir", "/config"); d("world_path", "/knowledge/world.jsonld"); d("weights", "/models/yolo11n_ready2go_v1.pt")
        d("color_topic", "/wrist_cam/color/image_raw"); d("depth_topic", "/wrist_cam/aligned_depth_to_color/image_raw")
        d("info_topic", "/wrist_cam/color/camera_info"); d("base_frame", "base_link"); d("camera_frame", "wrist_cam_color_optical_frame")
        d("frame_timeout_s", 3.0); d("device", "0")
        p = lambda n: self.get_parameter(n).value
        cfg = Path(p("config_dir"))
        self._params = yaml.safe_load((cfg / "vision_params.yaml").read_text(encoding="utf-8"))
        places = yaml.safe_load((cfg / "places.yaml").read_text(encoding="utf-8"))
        tf = places["drawer_top"]["tf"]
        if not tf or tf.get("translation_m") is None:
            raise RuntimeError("places.yaml drawer_top.tf 가 비어 있음 — 3점 터치 결과가 필요")
        self._T_base_drawer = make_T(tf["translation_m"], tf["quaternion_xyzw"])
        world = yaml.safe_load(Path(p("world_path")).read_text(encoding="utf-8"))
        self._items = world.get("world", world)["items"]
        dev = p("device")
        self._detector = YoloDetector(p("weights"), self._params["detector"]["conf_min"], int(dev) if str(dev).isdigit() else dev)
        missing = [c for c in self._detector.names.values() if c not in self._items]
        if missing:
            self.get_logger().warn(f"모델 클래스 중 온톨로지에 없는 이름(무시됨): {missing}")
        self._base, self._cam, self._timeout = p("base_frame"), p("camera_frame"), float(p("frame_timeout_s"))
        self._tfbuf = Buffer(); self._tfl = TransformListener(self._tfbuf, self)
        self._lock = threading.Lock()
        self._color = self._depth = self._info = None          # (수신 시각, 메시지)
        cb = ReentrantCallbackGroup()
        self.create_subscription(Image, p("color_topic"), lambda m: self._store("_color", m), qos_profile_sensor_data, callback_group=cb)
        self.create_subscription(Image, p("depth_topic"), lambda m: self._store("_depth", m), qos_profile_sensor_data, callback_group=cb)
        self.create_subscription(CameraInfo, p("info_topic"), lambda m: self._store("_info", m), qos_profile_sensor_data, callback_group=cb)
        self.create_service(InspectRegion, "/vision/inspect_region", self._handle, callback_group=cb)
        self.get_logger().info(f"inspect_region 시작 (모델 {p('weights')}, 클래스 {list(self._detector.names.values())})")

    def _store(self, name, msg):
        with self._lock:
            setattr(self, name, (time.monotonic(), msg))

    def _fresh_frames(self, since):
        deadline = time.monotonic() + self._timeout
        while time.monotonic() < deadline:
            with self._lock:
                c, dp, inf = self._color, self._depth, self._info
            if c and dp and inf and c[0] > since and dp[0] > since:
                return c[1], dp[1], inf[1]
            time.sleep(0.02)
        return None

    def _handle(self, req, res):
        start = time.monotonic()
        if req.region != "drawer_top":
            res.success, res.error_code, res.result_json = False, "UNKNOWN_REGION", ""
            return res
        frames = self._fresh_frames(start)
        if frames is None:
            res.success, res.error_code, res.result_json = False, "CAMERA_TIMEOUT", ""
            return res
        color_m, depth_m, info = frames
        try:
            ts = self._tfbuf.lookup_transform(self._base, self._cam, Time.from_msg(depth_m.header.stamp),
                                              timeout=rclpy.duration.Duration(seconds=0.5))
        except Exception as e:                                   # 시각이 안 맞으면 가장 최근 변환으로 한 번 더 (로봇은 정지 상태가 전제)
            try:
                ts = self._tfbuf.lookup_transform(self._base, self._cam, Time())
            except Exception:
                self.get_logger().error(f"TF 없음 {self._base}→{self._cam}: {e}")
                res.success, res.error_code, res.result_json = False, "TF_UNAVAILABLE", ""
                return res
        T_drawer_cam = drawer_from_camera(self._T_base_drawer, tf_to_T(ts))
        K = Intrinsics(info.k[0], info.k[4], info.k[2], info.k[5])
        dets = self._detector.detect(image_to_numpy(color_m))
        res.success, res.error_code, res.result_json = inspect_scene(
            dets, image_to_numpy(depth_m), K, T_drawer_cam, self._params, self._items, req.region, req.search_target)
        self.get_logger().info(f"inspect_region {req.region}/{req.search_target}: 검출 {len(dets)}개 → success={res.success} {res.error_code} {res.result_json[:200]}")
        return res


def main():
    rclpy.init()
    node = InspectRegionNode()
    ex = MultiThreadedExecutor(num_threads=4)
    ex.add_node(node)
    try:
        ex.spin()
    finally:
        node.destroy_node()
        rclpy.shutdown()
