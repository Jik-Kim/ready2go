"""YOLO 검출 래퍼 (ultralytics 는 처음 쓸 때 import — 테스트·CI 에서 없어도 다른 모듈이 import 된다)."""
from __future__ import annotations


class YoloDetector:
    def __init__(self, weights: str, conf_min: float = 0.25, device=None, imgsz: int = 640):
        from ultralytics import YOLO
        self._model = YOLO(weights)
        self._conf, self._device, self._imgsz = conf_min, device, imgsz
        self.names = dict(self._model.names)

    def detect(self, bgr) -> list[dict]:
        """BGR 이미지 한 장 → [{class, conf, box(x1,y1,x2,y2 픽셀)}]. 클래스 이름은 모델이 저장한 학습 때 이름."""
        res = self._model.predict(bgr, conf=self._conf, imgsz=self._imgsz, device=self._device, verbose=False)[0]
        out = []
        for b in res.boxes:
            x1, y1, x2, y2 = (float(v) for v in b.xyxy[0].tolist())
            out.append({"class": self.names[int(b.cls[0])], "conf": float(b.conf[0]), "box": (x1, y1, x2, y2)})
        return out
