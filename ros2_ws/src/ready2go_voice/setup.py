from glob import glob
from setuptools import find_packages, setup

package_name = 'ready2go_voice'

setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/ready2go_voice']),
        ('share/ready2go_voice', ['package.xml']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='E 고희태',
    maintainer_email='todo@example.com',
    description='웨이크워드 · STT · LLM 인텐트/목표 추출 · TTS',
    license='TODO',
    tests_require=['pytest'],
    entry_points={'console_scripts': []},
)
