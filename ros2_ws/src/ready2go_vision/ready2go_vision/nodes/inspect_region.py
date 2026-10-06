"""/vision/inspect_region 실제 노드: 손목 카메라 컬러·정렬 뎁스 + YOLO + 뎁스 덩어리 → result_json (core/inspect_real.py).

요청이 올 때 요청 이후에 도착한 프레임 한 쌍을 쓰고(오래된 프레임 방지), 광학 프레임의 서랍 좌표 변환은
TF base_link→광학 프레임(실시간)과 config/places.yaml 의 drawer_top.tf(서랍 정본)로 계산한다.
오류 코드: UNKNOWN_REGION, CAMERA_TIMEOUT, TF_UNAVAILABLE, DEPTH_INVALID, RESULT_INVALID (docs/runner.md).

진단(결과에는 영향 없음): 요청마다 검출별 판단 근거와 카메라로 본 서랍 바닥 z(core/floor_probe.py)를 로그로 남긴다.
dump_dir 파라미터를 주면 그 요청에 쓴 컬러·뎁스·K·TF·검출·결과를 .npz 로 저장한다(tools/dev/replay_inspect_dump.py 로 재계산).
"""
import datetime
import hashlib
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
from ready2go_vision.core.floor_probe import floor_probe
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
        d("frame_timeout_s", 3.0); d("device", "0"); d("dump_dir", ""); d("code_sha", "")
        p = lambda n: self.get_parameter(n).value
        cfg = Path(p("config_dir"))
        self._params = yaml.safe_load((cfg / "vision_params.yaml").read_text(encoding="utf-8"))
        places = yaml.safe_load((cfg / "places.yaml").read_text(encoding="utf-8"))
        tf = places["drawer_top"]["tf"]
        self._interior = places["drawer_top"]["interior_m"][:2]
        if not tf or tf.get("translation_m") is None:
            raise RuntimeError("places.yaml drawer_top.tf 가 비어 있음 — 3점 터치 결과가 필요")
        self._T_base_drawer = make_T(tf["translation_m"], tf["quaternion_xyzw"])
        sha = lambda f: hashlib.sha256(Path(f).read_bytes()).hexdigest()[:12]
        self._versions = {"code_sha": p("code_sha"), "weights_sha256": sha(p("weights")), "places_sha256": sha(cfg / "places.yaml"),
                          "vision_params_sha256": sha(cfg / "vision_params.yaml"), "drawer_top_tf": tf}
        self._dump = Path(p("dump_dir")) if p("dump_dir") else None
        if self._dump:
            self._dump.mkdir(parents=True, exist_ok=True)
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
        self.get_logger().info(f"inspect_region 시작 (모델 {p('weights')}, 클래스 {list(self._detector.names.values())}, "
                               f"버전 {json.dumps(self._versions, ensure_ascii=False)}, 덤프 {self._dump or '끔'})")

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
        color, depth = image_to_numpy(color_m), image_to_numpy(depth_m)
        dets = self._detector.detect(color)
        debug = []
        res.success, res.error_code, res.result_json = inspect_scene(
            dets, depth, K, T_drawer_cam, self._params, self._items, req.region, req.search_target, self._interior, debug)
        floor = floor_probe(depth, K, T_drawer_cam, self._interior, [dt["box"] for dt in dets], self._params["floor_probe"])
        log = self.get_logger()
        log.info(f"inspect_region {req.region}/{req.search_target}: 검출 {len(dets)}개 → success={res.success} {res.error_code} {res.result_json[:300]}")
        for item in debug:
            log.info(f"  검출 {json.dumps(item, ensure_ascii=False)}")
        log.info(f"  바닥(카메라, 서랍 z) {json.dumps(floor)}")
        if self._dump:
            self._save(color, depth, K, ts, T_drawer_cam, dets, debug, floor, req, res)
        return res

    def _save(self, color, depth, K, ts, T_drawer_cam, dets, debug, floor, req, res):
        now = datetime.datetime.now(datetime.timezone.utc)                     # UTC (컨테이너 시간대와 무관)
        stamp = f"{now:%Y%m%d_%H%M%S}_{now.microsecond // 1000:03d}Z"
        path = self._dump / f"inspect_{stamp}.npz"
        meta = {"request": {"region": req.region, "search_target": req.search_target}, "success": res.success,
                "error_code": res.error_code, "result_json": res.result_json, "detections": dets, "debug": debug, "floor": floor,
                "K": [K.fx, K.fy, K.cx, K.cy], "versions": self._versions, "interior_m": self._interior}
        try:
            np.savez_compressed(path, color=color, depth_m=depth.astype(np.float32), T_base_cam=tf_to_T(ts),
                                T_base_drawer=self._T_base_drawer, T_drawer_cam=T_drawer_cam,
                                meta=np.array(json.dumps(meta, ensure_ascii=False, default=float)))
            self.get_logger().info(f"  덤프 {path}")
        except Exception as e:                                   # 덤프 실패가 서비스 응답을 막지 않게
            self.get_logger().warn(f"덤프 실패 {path}: {e}")


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
