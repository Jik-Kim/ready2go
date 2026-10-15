from glob import glob
from pathlib import Path
from os.path import relpath
from setuptools import find_packages, setup

package_name = 'ready2go_knowledge'

setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/ready2go_knowledge']),
        ('share/ready2go_knowledge', ['package.xml']),
        ('share/ready2go_knowledge/knowledge', [relpath(
            Path(__file__).resolve().parents[3] / 'knowledge' / name)
            for name in ('refusal_reasons.json', 'semantics.ttl')]),
        ('share/ready2go_knowledge/config', [relpath(
            Path(__file__).resolve().parents[3] / 'config/yolo_retired_classes.txt')]),
    ],
    install_requires=['setuptools', 'PyYAML', 'rdflib>=6.1.1,<8'],
    zip_safe=True,
    maintainer='E 고희태',
    maintainer_email='todo@example.com',
    description='OntologyManager: 로봇 온톨로지 로딩 · 정합성 검사 · 상태 읽기/쓰기',
    license='TODO',
    tests_require=['pytest'],
    entry_points={'console_scripts': []},
)
