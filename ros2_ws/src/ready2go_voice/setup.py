from glob import glob
from pathlib import Path
from setuptools import find_packages, setup

package_name = 'ready2go_voice'

setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/ready2go_voice']),
        ('share/ready2go_voice', ['package.xml']),
        ('share/ready2go_voice/params', glob('params/*.yaml') + glob('params/melotts_*')),
        ('share/ready2go_voice/tasks', [str(Path(__file__).resolve().parents[3] / 'tasks' / name)
                                     for name in ('find_item.json', 'find_with_unpack.json')]),
    ],
    install_requires=['setuptools', 'jsonschema>=4,<5', 'PyYAML>=6,<7', 'numpy>=1.24,<2'],
    extras_require={
        'api': ['openai>=1,<3', 'langchain-openai>=0.2,<2', 'langchain-core>=0.3,<2'],
        'audio': ['sounddevice>=0.4,<1', 'openwakeword==0.6.0'],
    },
    zip_safe=True,
    maintainer='E 고희태',
    maintainer_email='todo@example.com',
    description='웨이크워드 · STT · LLM 인텐트/목표 추출 · TTS',
    license='TODO',
    tests_require=['pytest'],
    entry_points={'console_scripts': ['voice_node = ready2go_voice.nodes.voice_node:main']},
)
