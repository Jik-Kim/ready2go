"""명시 실행하는 프로젝트 내부 MeloTTS CPU 설치기. ROS 환경에 pip install하지 않습니다."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

SOURCE_REVISION = '209145371cff8fc3bd60d7be902ea69cbdb7965a'
MODELS = {
    'myshell-ai/MeloTTS-Korean': ('0207e5adfc90129a51b6b03d89be6d84360ed323', ['config.json', 'checkpoint.pth']),
    'kykim/bert-kor-base': ('1779cc0982ada0216dd6de0dd4e86fb78201926d',
                          ['config.json', 'pytorch_model.bin', 'tokenizer_config.json', 'special_tokens_map.json', 'vocab.txt']),
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--project-root', type=Path, required=True)
    args = parser.parse_args()
    root = args.project_root.resolve()
    package = Path(__file__).resolve().parents[2]
    assets = root / 'models/tts/melotts'
    runtime = root / '.venvs/melotts'
    env = os.environ.copy()
    for key in ('PYTHONPATH', 'PYTHONHOME', 'OPENAI_API_KEY', 'HF_TOKEN', 'HUGGING_FACE_HUB_TOKEN'):
        env.pop(key, None)
    env['HF_HUB_DISABLE_IMPLICIT_TOKEN'] = '1'
    assets.mkdir(parents=True, exist_ok=True)
    if not runtime.exists():
        subprocess.run([sys.executable, '-m', 'venv', str(runtime)], env=env, check=True)
    python = str(runtime / 'bin/python')  # symlink를 resolve하면 venv가 사라집니다
    requirements = package / 'params/melotts_requirements.txt'
    subprocess.run([python, '-m', 'pip', 'install', '--extra-index-url', 'https://download.pytorch.org/whl/cpu',
                    '-r', str(requirements)], env=env, check=True)
    source = assets / 'source'
    if not source.exists():
        subprocess.run(['git', 'clone', 'https://github.com/myshell-ai/MeloTTS.git', str(source)], check=True)
        subprocess.run(['git', 'checkout', SOURCE_REVISION], cwd=source, check=True)
    current = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=source, text=True).strip()
    if current != SOURCE_REVISION:
        raise RuntimeError('기존 source revision 불일치: 덮어쓰지 않습니다')
    patch = package / 'params/melotts_kr.patch'
    applied = subprocess.run(['git', 'apply', '--reverse', '--check', str(patch)], cwd=source,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
    if not applied:
        subprocess.run(['git', 'apply', '--check', str(patch)], cwd=source, check=True)
        subprocess.run(['git', 'apply', str(patch)], cwd=source, check=True)
    (assets / 'requirements.lock').write_text(requirements.read_text())
    code = '''import json, sys
from pathlib import Path
from huggingface_hub import snapshot_download
import nltk
assets = Path(sys.argv[1]); models = json.loads(sys.argv[2]); manifest = {}
for repo, (revision, patterns) in models.items():
    path = snapshot_download(repo, revision=revision, allow_patterns=patterns, cache_dir=str(assets/'hf'), token=False)
    manifest[repo] = {'revision':revision, 'path':path}
(assets/'model_manifest.json').write_text(json.dumps(manifest, indent=2)+'\\n')
assert nltk.download('cmudict', download_dir=str(assets/'nltk'), quiet=True)
'''
    subprocess.run([python, '-c', code, str(assets), json.dumps(MODELS)], env=env, check=True)
    subprocess.run([python, '-m', 'pip', 'check'], env=env, check=True)
    print('설치 완료. 음성 노드를 재시작하기 전에 README의 단문 시험을 수행하십시오.')


if __name__ == '__main__':
    main()
