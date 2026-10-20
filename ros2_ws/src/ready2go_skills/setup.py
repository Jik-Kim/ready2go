from glob import glob
from setuptools import find_packages, setup

package_name = 'ready2go_skills'

setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/ready2go_skills']),
        ('share/ready2go_skills', ['package.xml']),
        ('share/ready2go_skills/launch', glob('launch/*.launch.py')),
        ('share/ready2go_skills/params', glob('params/*.yaml')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='B 서동권',
    maintainer_email='todo@example.com',
    description='실물/시뮬/목 백엔드의 모션 원자 동작(DSR·RG2) — 로봇을 움직이는 유일한 패키지',
    license='Apache-2.0',
    tests_require=['pytest'],
    entry_points={'console_scripts': [
        'gripper_state = ready2go_skills.nodes.gripper_state_node:main',
        'skill_server = ready2go_skills.nodes.skill_server:main',
        'jog_gui = ready2go_skills.nodes.jog_gui:main',
    ]},
)
