"""auto_label_single.py 의 출력 폴더 정리 (표준 라이브러리만 사용 — CI 에서 cv2 없이 시험한다).

같은 세션을 --exclude 나 class_ranges.txt 를 바꿔 다시 돌리면 이번에 제외한 이미지의 이전 images/labels 가 남아
build_dataset 의 학습 데이터에 섞일 수 있다. 그래서 기존 출력이 있으면 기본은 중단하고, --force 일 때만 비우고 다시 만든다.
지우는 곳은 <out>/<세션>/{images,labels,preview} 안의 파일뿐이다(원본 data/raw 는 건드리지 않는다).
"""
import shutil
from pathlib import Path

SUBDIRS = ("images", "labels", "preview")


def existing_outputs(out: Path) -> dict[str, int]:
    """출력 폴더에 이미 있는 파일 수 (폴더 이름 → 장수). 없으면 빈 사전."""
    return {s: sum(1 for p in (out / s).iterdir() if p.is_file()) for s in SUBDIRS if (out / s).is_dir()
            and any(p.is_file() for p in (out / s).iterdir())}


def prepare_output(out: Path, raw: Path, force: bool) -> dict[str, int]:
    """출력 폴더를 비워 둔 상태로 만든다. 기존 파일이 있고 force 가 아니면 FileExistsError. 반환: 지운 파일 수."""
    out, raw = out.resolve(), raw.resolve()
    if out == raw or raw in out.parents or out in raw.parents:
        raise ValueError(f"출력 폴더가 원본 폴더와 겹칩니다: out={out} raw={raw}")
    found = existing_outputs(out)
    if found and not force:
        raise FileExistsError(
            f"{out} 에 이전 결과가 있습니다 {found}. 다시 만들면 이 폴더의 라벨(손으로 고친 것 포함)이 모두 덮어써집니다. "
            "계속하려면 --force 를 붙이세요(원본 data/raw 는 바뀌지 않음).")
    for s in SUBDIRS:
        if (out / s).is_dir():
            shutil.rmtree(out / s)
        (out / s).mkdir(parents=True, exist_ok=True)
    return found
