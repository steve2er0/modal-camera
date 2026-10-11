import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import pytest
from modal_camera.synthetic import write_demos
from modal_camera.processing import decode_video

@pytest.fixture(scope='session')
def demos(tmp_path_factory):
    directory = tmp_path_factory.mktemp('demo')
    write_demos(directory)
    return directory

@pytest.fixture(scope='session')
def clean(demos):
    return decode_video(demos/'known_motion.avi')

@pytest.fixture(scope='session')
def clean_traces(clean):
    from modal_camera.processing import track_points
    return track_points(clean,[[90,94],[230,94]])
