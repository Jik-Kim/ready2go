from glob import glob
from setuptools import find_packages, setup

package_name = 'ready2go_vision'

setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/ready2go_vision']),
        ('share/ready2go_vision', ['package.xml']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='A 김병직',
    maintainer_email='todo@example.com',
    description='inspect_region: 검출 · 뎁스 3D 위치 · 가림 순서 · 인스턴스 ID 추적',
    license='TODO',
    tests_require=['pytest'],
    entry_points={'console_scripts': ['inspect_region_stub = ready2go_vision.nodes.inspect_region_stub:main',
                                      'inspect_region = ready2go_vision.nodes.inspect_region:main']},
)
