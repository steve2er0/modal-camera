from io import BytesIO
import json
import cv2
import numpy as np
import pytest
import app as server
from modal_camera.processing import decode_video


@pytest.fixture
def client():
    server.app.config.update(TESTING=True)
    server.state.clear()
    return server.app.test_client()


def post_video(client,path,name='motion.avi'):
    return client.post('/api/load',data={'video':(BytesIO(path.read_bytes()),name)},content_type='multipart/form-data')


def test_malformed_unsupported_and_missing_files(client,tmp_path):
    assert client.post('/api/load').status_code==400
    broken=tmp_path/'broken.avi';broken.write_bytes(b'not a video')
    assert post_video(client,broken).status_code==400
    assert post_video(client,broken,'bad.txt').status_code==400
    with pytest.raises(ValueError):decode_video(broken)


def test_repeated_loads_analysis_render_export_and_stale_state(client,demos):
    path=demos/'known_motion.avi'
    first=post_video(client,path).get_json();second=post_video(client,path).get_json()
    assert first['id']!=second['id']
    assert client.get(f"/api/frame/{first['id']}/0").status_code==400
    cid=second['id'];data=dict(id=cid,points=[[90,94],[230,94]],axis='y',frequency=3)
    a=client.post('/api/analyze',json=data)
    assert a.status_code==200
    assert a.get_json()['psd_metadata']['units']=='source pixels squared per Hz'
    assert len(a.get_json()['points'][0]['psd_px2_per_hz'])==181
    assert a.get_json()['points'][1]['fit']['relative_phase_deg']==pytest.approx(60,abs=5)
    for bad in [dict(low=3,high=2,gain=4),dict(low=2.5,high=3.5,gain=99),dict(low=2.5,high=3.5,gain=4,roi=[-1,0,20,20])]:
        assert client.post('/api/render',json=dict(id=cid,**bad)).status_code==400
    render=client.post('/api/render',json=dict(id=cid,low=2.5,high=3.5,gain=2)).get_json()
    r=client.get(f"/api/frame/{cid}/45?view=amplified&key={render['key']}")
    assert r.status_code==200 and r.mimetype=='image/jpeg'
    assert client.get(f"/api/frame/{cid}/45?view=amplified&key=stale").status_code==400
    assert client.get(f"/api/frame/{cid}/9999").status_code==400
    export=client.get(f'/api/export/{cid}')
    assert json.loads(export.data)['measurement']['units'].startswith('source pixels')
    csv=client.get(f'/api/csv/{cid}').data.decode()
    assert 'source_px' in csv and len(csv.splitlines())==361
    # Rendering does not mutate the original point measurements.
    b=client.post('/api/analyze',json=data).get_json()
    assert b['points'][0]['fit']==a.get_json()['points'][0]['fit']
    third=post_video(client,path).get_json()
    assert server.state['analysis'] is None and server.state['render'] is None
    assert third['id']!=cid


def test_invalid_analysis_inputs_and_local_security(client,demos):
    cid=post_video(client,demos/'known_motion.avi').get_json()['id']
    for points,f in [([],3),([[1,1]],3),([[90,94]],30),([[90,94]],'nan')]:
        assert client.post('/api/analyze',json=dict(id=cid,points=points,frequency=f)).status_code==400
    assert client.post('/api/demo',json={},headers={'Origin':'https://external.example'}).status_code==403
    assert client.get('/',headers={'Host':'external.example'}).status_code==403
    assert client.get('/').status_code==200


def test_too_many_frames_and_short_clip(tmp_path):
    for n in [16,601]:
        path=tmp_path/f'{n}.avi'
        writer=cv2.VideoWriter(str(path),cv2.VideoWriter_fourcc(*'FFV1'),30,(32,32))
        assert writer.isOpened()
        for i in range(n):writer.write(np.full((32,32,3),i%255,np.uint8))
        writer.release()
        with pytest.raises(ValueError):decode_video(path)


def test_irregular_timestamps_and_truncated_file(monkeypatch):
    class Capture:
        def __init__(self,*a):self.i=0
        def isOpened(self):return True
        def get(self,key):
            if key==cv2.CAP_PROP_FPS:return 30.
            if key==cv2.CAP_PROP_FRAME_COUNT:return 40
            if key in (3,4):return 32
            if key==cv2.CAP_PROP_POS_MSEC:return (self.i-1)/30*1000+(10 if self.i==15 else 0)
            return 0
        def read(self):
            if self.i>=40:return False,None
            self.i+=1;return True,np.zeros((32,32,3),np.uint8)
        def release(self):pass
    monkeypatch.setattr(cv2,'VideoCapture',Capture)
    with pytest.raises(ValueError,match='Irregular'):decode_video('fake')
    original=Capture.read
    def truncated(self):
        if self.i>=33:return False,None
        return original(self)
    monkeypatch.setattr(Capture,'read',truncated)
    with pytest.raises(ValueError,match='ended'):decode_video('fake')


def test_explicit_timebase_override_and_revert(client,demos):
    cid=post_video(client,demos/'known_motion.avi').get_json()['id']
    data=dict(id=cid,points=[[90,94],[230,94]],axis='y',frequency=3)
    original=client.post('/api/analyze',json=data).get_json()
    assert client.post('/api/timebase',json=dict(id=cid,capture_fps=600)).status_code==400
    assert client.post('/api/timebase',json=dict(id=cid,capture_fps='nan',one_frame_per_sample=True)).status_code==400
    changed=client.post('/api/timebase',json=dict(id=cid,capture_fps=600,one_frame_per_sample=True)).get_json()
    assert changed['metadata']['encoded_fps']==60
    assert changed['metadata']['fps']==600
    assert changed['metadata']['duration']==.6
    assert 'user-assumed' in changed['metadata']['timing_basis']
    assert server.state['analysis'] is None and server.state['render'] is None
    scaled=client.post('/api/analyze',json=dict(data,frequency=30)).get_json()
    assert scaled['peak_frequency_hz']==pytest.approx(30)
    assert scaled['points'][0]['fit']['amplitude_peak_px']==pytest.approx(original['points'][0]['fit']['amplitude_peak_px'],abs=1e-10)
    reverted=client.post('/api/timebase',json=dict(id=cid,capture_fps=None)).get_json()
    assert reverted['metadata']['fps']==60
