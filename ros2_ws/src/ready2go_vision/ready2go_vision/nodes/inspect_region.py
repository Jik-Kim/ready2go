"""/vision/inspect_region 실제 노드: 손목 카메라 컬러·정렬 뎁스 + YOLO + 뎁스 덩어리 → result_json (core/inspect_real.py).

요청이 올 때 요청 이후에 도착한 프레임 한 쌍을 쓰고(오래된 프레임 방지), 광학 프레임의 서랍 좌표 변환은
TF base_link→광학 프레임(실시간)과 config/places.yaml 의 요청 지역 tf(서랍 정본: drawer_top, drawer_bottom)로 계산한다.
drawer_top.tf 는 시작에 필수, drawer_bottom.tf 가 아직 null 이면 그 지역 요청만 UNKNOWN_REGION (#155).
전달 트레이 handover_zone 은 tf·floor_m 이 있으면 지원(#43). 지역 바닥이 충분히 안 보이면 REGION_NOT_VISIBLE.
오류 코드: UNKNOWN_REGION, CAMERA_TIMEOUT, TF_UNAVAILABLE, REGION_NOT_VISIBLE, DEPTH_INVALID, RESULT_INVALID (docs/runner.md).

진단(결과에는 영향 없음): 요청마다 검출별 판단 근거와 카메라로 본 서랍 바닥 z(core/floor_probe.py)를 로그로 남긴다.
dump_dir 파라미터를 주면 그 요청에 쓴 컬러·뎁스·K·TF·검출·결과를 .npz 로 저장한다(tools/dev/replay_inspect_dump.py 로 재계산).
요청마다 그 촬영 장면 오버레이(마스크·이름·윗면 높이·가리는 물체·방향)를 /vision/inspect_overlay (CompressedImage JPEG)로 최대 1장
발행한다(#348, docs/vision.md#inspect-overlay). 응답을 막지 않게 별도 작업 스레드가 가장 최근 요청 하나만 그린다. overlay_enable=false 면 끔.
분할 모델(weights 가 yolo*-seg)이면 검출 마스크를 덤프 masks(packbits)로 함께 저장한다(meta.detections 순서와 같음).
기본 가중치는 P2 분할 모델 yolo11s_seg_ready2go_v2(가림 필드 occluded_by·visible_area_m2 를 냄, #109 4단계 — 10/12 3단 쌓기·판 밑 보강, #229). 이전 분할 v1 은 weights 로 지정해 되돌릴 수 있음. 박스 모델 v1(P1)은 weights 로 지정하면 가림 필드 없이 동작.
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
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy, qos_profile_sensor_data
from rclpy.time import Time
from sensor_msgs.msg import CameraInfo, CompressedImage, Image
from tf2_ros import Buffer, TransformListener

from ready2go_interfaces.srv import InspectRegion
from ready2go_vision.core.detector import YoloDetector
from ready2go_vision.core.dump_masks import split_masks
from ready2go_vision.core.floor_probe import floor_probe
from ready2go_vision.core.geometry import Intrinsics, drawer_from_camera, make_T
from ready2go_vision.core.inspect_real import SUPPORTED_REGIONS, inspect_scene, region_frames
from ready2go_vision.core.overlay import encode_jpeg, render_overlay

OVERLAY_TOPIC = "/vision/inspect_overlay"
OVERLAY_QOS = QoSProfile(reliability=ReliabilityPolicy.RELIABLE, durability=DurabilityPolicy.TRANSIENT_LOCAL,
                         history=HistoryPolicy.KEEP_LAST, depth=1)      # 늦게 붙은 화면도 마지막 한 장 (docs/interfaces.md)


KST = datetime.timezone(datetime.timedelta(hours=9))           # 오버레이 머리 띠 촬영 시각 표시 (팀 시간대)


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
        d("config_dir", "/config"); d("world_path", "/knowledge/world.jsonld"); d("weights", "/models/yolo11s_seg_ready2go_v2.pt")
        d("color_topic", "/wrist_cam/color/image_raw"); d("depth_topic", "/wrist_cam/aligned_depth_to_color/image_raw")
        d("info_topic", "/wrist_cam/color/camera_info"); d("base_frame", "base_link"); d("camera_frame", "wrist_cam_color_optical_frame")
        d("frame_timeout_s", 3.0); d("device", "0"); d("dump_dir", ""); d("code_sha", "")
        d("overlay_enable", True); d("overlay_jpeg_quality", 85)
        p = lambda n: self.get_parameter(n).value
        cfg = Path(p("config_dir"))
        self._params = yaml.safe_load((cfg / "vision_params.yaml").read_text(encoding="utf-8"))
        places = yaml.safe_load((cfg / "places.yaml").read_text(encoding="utf-8"))
        self._regions = region_frames(places)
        if "drawer_top" not in self._regions:
            raise RuntimeError("places.yaml drawer_top.tf 가 비어 있음 — 3점 터치 결과가 필요")
        sha = lambda f: hashlib.sha256(Path(f).read_bytes()).hexdigest()[:12]
        self._versions = {"code_sha": p("code_sha"), "weights_sha256": sha(p("weights")), "places_sha256": sha(cfg / "places.yaml"),
                          "vision_params_sha256": sha(cfg / "vision_params.yaml"),
                          **{f"{r}_tf": (self._regions[r]["tf"] if r in self._regions else None) for r in SUPPORTED_REGIONS}}
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
        self._ov_enable, self._ov_quality = bool(p("overlay_enable")), int(p("overlay_jpeg_quality"))
        self._ov_cv = threading.Condition()
        self._ov_job = None                                     # 아직 안 그린 가장 최근 요청 하나 (새 요청이 오면 덮음)
        self._ov_last_stamp = -1                                 # 발행한 사진의 촬영 시각(ns) — 이보다 오래된 것은 발행 안 함
        if self._ov_enable:
            self._ov_pub = self.create_publisher(CompressedImage, OVERLAY_TOPIC, OVERLAY_QOS)
            threading.Thread(target=self._overlay_loop, daemon=True).start()
        self.create_service(InspectRegion, "/vision/inspect_region", self._handle, callback_group=cb)
        self.get_logger().info(f"inspect_region 시작 (모델 {p('weights')} {'분할 — 가림 필드 냄' if self._detector.is_seg else '박스 — 가림 필드 없음'}, 클래스 {list(self._detector.names.values())}, "
                               f"버전 {json.dumps(self._versions, ensure_ascii=False)}, 덤프 {self._dump or '끔'}, 오버레이 {OVERLAY_TOPIC if self._ov_enable else '끔'})")

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
        region = self._regions.get(req.region)
        if region is None:
            why = "places.yaml tf 미측정" if req.region in SUPPORTED_REGIONS else "지원하지 않는 지역"
            self.get_logger().warn(f"inspect_region {req.region!r}: UNKNOWN_REGION ({why})")
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
                self._overlay_submit(color_m, image_to_numpy(color_m), [], "", None, None, None, req, "TF_UNAVAILABLE")
                return res
        T_drawer_cam = drawer_from_camera(region["T_base_drawer"], tf_to_T(ts))
        K = Intrinsics(info.k[0], info.k[4], info.k[2], info.k[5])
        color, depth = image_to_numpy(color_m), image_to_numpy(depth_m)
        dets = self._detector.detect(color)
        debug, info = [], {}
        res.success, res.error_code, res.result_json = inspect_scene(
            dets, depth, K, T_drawer_cam, self._params, self._items, req.region, req.search_target, region["interior_m"], debug,
            seg_model=self._detector.is_seg, region_height_m=region["height_m"], info=info)
        floor = floor_probe(depth, K, T_drawer_cam, region["interior_m"], [dt["box"] for dt in dets], self._params["floor_probe"])
        log = self.get_logger()
        log.info(f"inspect_region {req.region}/{req.search_target}: 검출 {len(dets)}개 → success={res.success} {res.error_code} {res.result_json[:300]}")
        for item in debug:
            log.info(f"  검출 {json.dumps(item, ensure_ascii=False)}")
        log.info(f"  바닥(카메라, 서랍 z) {json.dumps(floor)}  지역 바닥 보인 비율 {info.get('region_visible_ratio')}")
        if self._dump:
            self._save(color, depth, K, ts, T_drawer_cam, region, dets, debug, floor, req, res, info)
        self._overlay_submit(color_m, color, dets, res.result_json, K, T_drawer_cam, region["interior_m"], req,
                             "" if res.success else res.error_code)
        return res

    def _overlay_submit(self, color_m, color, dets, result_json, K, T_drawer_cam, interior_m, req, error_code=""):
        """그릴 재료만 넘기고 바로 돌아감 — 그리기·인코딩·발행은 _overlay_loop (서비스 응답을 막지 않음)."""
        if not self._ov_enable:
            return
        st = color_m.header.stamp
        job = dict(stamp=st, stamp_ns=st.sec * 1_000_000_000 + st.nanosec, frame_id=color_m.header.frame_id, color=color, dets=dets,
                   result_json=result_json, K=K, T=T_drawer_cam, interior_m=interior_m,
                   request={"region": req.region, "search_target": req.search_target}, error_code=error_code)
        with self._ov_cv:
            self._ov_job = job                                   # 아직 안 그린 이전 요청은 버림
            self._ov_cv.notify()

    def _overlay_loop(self):
        while rclpy.ok():
            with self._ov_cv:
                while self._ov_job is None:
                    self._ov_cv.wait(timeout=1.0)
                    if not rclpy.ok():
                        return
                job, self._ov_job = self._ov_job, None
            try:
                msg = self._overlay_msg(job)
                if job["stamp_ns"] <= self._ov_last_stamp:        # 이미 더 새 촬영을 발행함
                    continue
                self._ov_pub.publish(msg)
                self._ov_last_stamp = job["stamp_ns"]
            except Exception as e:                               # 오버레이 실패가 인식에 영향 주지 않게 — 경고만
                self.get_logger().warn(f"오버레이 생략: {e}")

    def _overlay_msg(self, job):
        t = datetime.datetime.fromtimestamp(job["stamp_ns"] / 1e9, KST)
        result = json.loads(job["result_json"]) if job["result_json"] else {}
        rgb = render_overlay(job["color"], job["dets"], result, job["K"], job["T"], job["interior_m"], self._items, job["request"],
                             f"{t:%H:%M:%S}", error_code=job["error_code"])
        msg = CompressedImage()
        msg.header.stamp, msg.header.frame_id = job["stamp"], job["frame_id"]
        msg.format = "jpeg"
        msg.data = encode_jpeg(rgb, self._ov_quality)
        return msg

    def _save(self, color, depth, K, ts, T_drawer_cam, region, dets, debug, floor, req, res, info=None):
        now = datetime.datetime.now(datetime.timezone.utc)                     # UTC (컨테이너 시간대와 무관)
        stamp = f"{now:%Y%m%d_%H%M%S}_{now.microsecond // 1000:03d}Z"
        path = self._dump / f"inspect_{stamp}.npz"
        plain, extra = split_masks(dets)
        meta = {"request": {"region": req.region, "search_target": req.search_target}, "success": res.success,
                "error_code": res.error_code, "result_json": res.result_json,
                "detections": plain, "debug": debug, "floor": floor, "info": info or {},
                "K": [K.fx, K.fy, K.cx, K.cy], "versions": self._versions,
                "interior_m": region["interior_m"], "region_height_m": region["height_m"], "region_tf": region["tf"]}
        try:
            np.savez_compressed(path, **extra, color=color, depth_m=depth.astype(np.float32), T_base_cam=tf_to_T(ts),
                                T_base_drawer=region["T_base_drawer"], T_drawer_cam=T_drawer_cam,
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
