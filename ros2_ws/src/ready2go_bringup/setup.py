from glob import glob
from setuptools import find_packages, setup

package_name = 'ready2go_bringup'

setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/ready2go_bringup']),
        ('share/ready2go_bringup', ['package.xml']),
        ('share/ready2go_bringup/launch', glob('launch/*.launch.py')),
        ('share/ready2go_bringup/params', glob('params/*.yaml')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='공동 (검토 C 이영훈)',
    maintainer_email='todo@example.com',
    description='launch · 노드 파라미터 기본값(params/*.yaml)',
    license='TODO',
    tests_require=['pytest'],
    entry_points={'console_scripts': []},
)
