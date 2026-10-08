"""YOLO 검출 래퍼 (ultralytics 는 처음 쓸 때 import — 테스트·CI 에서 없어도 다른 모듈이 import 된다)."""
from __future__ import annotations


class YoloDetector:
    def __init__(self, weights: str, conf_min: float = 0.25, device=None, imgsz: int = 640):
        from ultralytics import YOLO
        self._model = YOLO(weights)
        self._conf, self._device, self._imgsz = conf_min, device, imgsz
        self.names = dict(self._model.names)
        self.is_seg = getattr(self._model, "task", "") == "segment"      # 분할 모델(yolo*-seg)이면 검출마다 마스크

    def detect(self, bgr) -> list[dict]:
        """BGR 이미지 한 장 → [{class, conf, box(x1,y1,x2,y2 픽셀)[, mask]}]. 클래스 이름은 모델이 저장한 학습 때 이름.
        분할 모델이면 mask = 이미지 크기 bool 배열(retina_masks: 원본 해상도). JSON 에 넣을 때는 빼야 한다."""
        res = self._model.predict(bgr, conf=self._conf, imgsz=self._imgsz, device=self._device, verbose=False,
                                  retina_masks=self.is_seg)[0]
        masks = res.masks.data.cpu().numpy() > 0.5 if self.is_seg and res.masks is not None else None
        out = []
        for i, b in enumerate(res.boxes):
            x1, y1, x2, y2 = (float(v) for v in b.xyxy[0].tolist())
            d = {"class": self.names[int(b.cls[0])], "conf": float(b.conf[0]), "box": (x1, y1, x2, y2)}
            if masks is not None:
                d["mask"] = masks[i]
            out.append(d)
        return out
