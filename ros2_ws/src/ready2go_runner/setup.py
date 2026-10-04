from glob import glob
from setuptools import find_packages, setup

package_name = 'ready2go_runner'

setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/ready2go_runner']),
        ('share/ready2go_runner', ['package.xml']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='C 이영훈',
    maintainer_email='todo@example.com',
    description='JSON Runner · 플래너 · 상태 추적 · 실행 로그(LogStore→MongoDB)',
    license='TODO',
    tests_require=['pytest'],
    entry_points={'console_scripts': [
        'mock_backend = ready2go_runner.nodes.mock_backend:main',
    ]},
)
