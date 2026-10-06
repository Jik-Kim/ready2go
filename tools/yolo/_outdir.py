"""auto_label_single.py 의 출력 폴더 처리 (표준 라이브러리만 사용 — CI 에서 cv2 없이 시험한다).

① 같은 세션을 --exclude 나 class_ranges.txt 를 바꿔 다시 돌리면 이번에 제외한 이미지의 이전 images/labels 가 남아
   build_dataset 의 학습 데이터에 섞일 수 있다 → 기존 출력이 있으면 기본은 중단하고, --force 일 때만 교체한다.
② 실행 도중 오류로 끊기면 앞부분만 있는 불완전한 세션이 남고 build_dataset 은 이를 정상으로 받아들인다
   → 결과는 작업 폴더(<out 의 상위>/../.auto_label_work/<세션>)에 전부 만든 뒤 끝까지 성공했을 때만 한 번에 교체한다.
   실패하면 기존 출력은 그대로이고 작업 폴더만 남는다(다음 실행 때 지움; data/labeled 밖이라 데이터셋에 섞이지 않는다).
원본 data/raw 는 건드리지 않는다.
"""
import shutil
from pathlib import Path

SUBDIRS = ("images", "labels", "preview")


def existing_outputs(out: Path) -> dict[str, int]:
    """출력 폴더에 이미 있는 파일 수 (폴더 이름 → 장수). 없으면 빈 사전."""
    return {s: sum(1 for p in (out / s).iterdir() if p.is_file()) for s in SUBDIRS if (out / s).is_dir()
            and any(p.is_file() for p in (out / s).iterdir())}


def work_dir(out: Path) -> Path:
    return out.resolve().parent.parent / ".auto_label_work" / out.name


def prepare_output(out: Path, raw: Path, force: bool) -> tuple[Path, dict[str, int]]:
    """검사하고 빈 작업 폴더를 만든다. 반환: (작업 폴더, 교체될 기존 파일 수). 기존 출력은 건드리지 않는다.
    기존 파일이 있고 force 가 아니면 FileExistsError, 출력이 원본과 겹치면 ValueError."""
    out, raw = out.resolve(), raw.resolve()
    if out == raw or raw in out.parents or out in raw.parents:
        raise ValueError(f"출력 폴더가 원본 폴더와 겹칩니다: out={out} raw={raw}")
    found = existing_outputs(out)
    if found and not force:
        raise FileExistsError(
            f"{out} 에 이전 결과가 있습니다 {found}. 다시 만들면 이 폴더의 라벨(손으로 고친 것 포함)이 모두 교체됩니다. "
            "계속하려면 --force 를 붙이세요(원본 data/raw 는 바뀌지 않음).")
    work = work_dir(out)
    if work.exists():
        shutil.rmtree(work)
    for s in SUBDIRS:
        (work / s).mkdir(parents=True)
    return work, found


def commit_output(work: Path, out: Path) -> None:
    """끝까지 성공한 작업 폴더로 출력 폴더를 한 번에 교체한다(기존 출력은 그때 지워짐)."""
    out = out.resolve()
    if out.exists():
        shutil.rmtree(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    work.rename(out)
