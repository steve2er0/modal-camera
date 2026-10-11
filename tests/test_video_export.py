from dataclasses import replace

import cv2
import numpy as np
import pytest

import app as server
from modal_camera.processing import magnify
from modal_camera.response import measure_field
from modal_camera.video_export import (
    annotate, band_frame, export_frames, export_metadata, modal_display_frame,
    response_layers, visibility, write_mp4,
)


@pytest.fixture(scope='module')
def export_setup(clean):
    # Slow-motion playback and capture timing deliberately differ by 8x.
    video = replace(clean, fps=240, encoded_fps=30,
                    timing_basis='user-assumed capture time: one frame per captured sample')
    rendered, info, response = magnify(video, 10, 14, 4, return_response=True)
    display = np.clip(response/max(info['response']['display_reference_rms'], 1e-6)*255, 0, 255).astype(np.uint8)
    field, _, maps = measure_field(video, 12, points=[[90,94],[230,94]])
    return video, rendered, info, display, field, maps


@pytest.fixture
def export_client(export_setup):
    video, rendered, info, display, field, maps = export_setup
    server.app.config.update(TESTING=True)
    with server.app.app_context():
        cid = server.install_clip(video).get_json()['id']
    server.state.update(render=rendered, render_info=info, response_display=display, render_key='band',
                        field=field, field_maps=maps, field_key='field')
    return server.app.test_client(), cid


def test_sensitivity_and_compositing_match_display():
    original = np.full((1,3,3), 100, np.uint8)
    amplified = np.full((1,3,3), 200, np.uint8)
    response = np.array([[0,128,255]], np.uint8)
    layers = response_layers(response, 85)
    isolated = band_frame(original, amplified, layers, 'isolated')
    np.testing.assert_array_equal(isolated[0,0], [8,13,19])
    np.testing.assert_array_equal(isolated[0,2], [200]*3)
    heatmap = band_frame(original, amplified, layers, 'heatmap')
    np.testing.assert_array_equal(heatmap[0,0], [54,56,60])
    np.testing.assert_allclose(heatmap[0,2], [.15*54+.85*255, .15*56.5+.85*191, .15*59.5+.85*102], atol=1)
    assert visibility(.2,100) > visibility(.2,0)
    assert visibility(0,100) == 0


@pytest.mark.parametrize('view', ['heatmap','isolated','modal'])
def test_download_decodes_all_frames_and_preserves_timing(export_setup,export_client,tmp_path,view):
    video, rendered, info, display, field, maps = export_setup
    client, cid = export_client
    original = video.frames.copy()
    prepared = client.post('/api/export-video?prepare=1', json=dict(id=cid, view=view,
                           key='field' if view=='modal' else 'band', sensitivity=85, modal_gain=8, phase_start=90))
    assert prepared.status_code == 200
    download = prepared.get_json()
    assert download['filename'].endswith(f'{view}.mp4')
    response = client.get(download['url'])
    assert response.status_code == 200
    assert response.mimetype == 'video/mp4'
    assert response.headers['Content-Disposition'].endswith(f'{view}.mp4')
    assert b'ftyp' in response.data[:40]
    assert response.data.find(b'moov') < response.data.find(b'mdat')  # Fast-start MP4.
    path = tmp_path/f'{view}.mp4'
    path.write_bytes(response.data)
    cap = cv2.VideoCapture(str(path))
    try:
        assert cap.isOpened()
        assert cap.get(cv2.CAP_PROP_FPS) == pytest.approx(30, abs=.01)
        count = 120 if view=='modal' else len(video.frames)
        assert cap.get(cv2.CAP_PROP_FRAME_COUNT) == count
        assert cap.get(cv2.CAP_PROP_FOURCC) in [cv2.VideoWriter_fourcc(*codec) for codec in ('avc1','h264')]
        decoded = []
        while True:
            ok, image = cap.read()
            if not ok:
                break
            decoded.append(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
        assert len(decoded) == count
        assert decoded[0].shape[1] == 640 and decoded[0].shape[0]%2 == 0
        metadata = export_metadata(video,view,85,8,90,info,field)
        frames = export_frames(video,metadata,rendered,display,field,maps)
        expected = next(frames)
        assert np.abs(decoded[0].astype(float)-expected).mean() < 2.5
        if view=='modal':
            # Repeat four cycles and actually animate, with the current start phase.
            assert np.abs(decoded[0].astype(float)-decoded[30]).mean() < 1
            assert np.abs(decoded[0][64:464].astype(float)-decoded[15][64:464]).mean() > .5
            assert metadata['export_duration_s'] == 4
            assert metadata['frequency_hz'] == 12
        else:
            assert metadata['export_duration_s'] == len(video.frames)/30
            assert metadata['analysis_fps'] == 240  # Never export captured samples at assumed capture speed.
        assert b'user-assumed capture time' in response.data  # Embedded provenance survives sharing.
    finally:
        cap.release()
    np.testing.assert_array_equal(video.frames, original)


def test_modal_displacement_and_sensitivity_are_used(export_setup):
    video, _, info, _, field, maps = export_setup
    zero = modal_display_frame(video,field,maps,0,0,100)
    positive = modal_display_frame(video,field,maps,0,10,100)
    negative = modal_display_frame(video,field,maps,180,10,100)
    assert not np.array_equal(zero, positive)
    assert not np.array_equal(positive, negative)
    assert not np.array_equal(positive, modal_display_frame(video,field,maps,0,10,0))
    # Header/footer expose the difference between physical/analysis and display timing.
    metadata = export_metadata(video,'modal',85,10,90,info,field)
    annotated = annotate(positive,metadata,90)
    assert annotated.shape[0] > positive.shape[0]
    assert metadata['phase_start_deg'] == 90 and metadata['display_cycles_per_second'] == 1


@pytest.mark.parametrize('settings', [dict(key='stale'),dict(sensitivity=-1),dict(sensitivity=101),
    dict(sensitivity='nan'),dict(modal_gain=21),dict(phase_start='infinite'),dict(view='phase')])
def test_export_invalid_inputs_are_rejected(export_client,settings):
    client, cid = export_client
    data = dict(id=cid,view='heatmap',key='band')
    data.update(settings)
    assert client.post('/api/export-video',json=data).status_code == 400


def test_missing_reference_timebase_replacement_and_security(export_client,export_setup):
    client, cid = export_client
    server.state['field'] = dict(server.state['field'],reference=dict(phase_deg=None))
    assert client.post('/api/export-video',json=dict(id=cid,view='modal',key='field')).status_code == 400
    data = dict(id=cid,view='heatmap',key='band')
    assert client.post('/api/export-video',json=data,headers={'Origin':'https://external.example'}).status_code == 403
    assert client.post('/api/timebase',json=dict(id=cid,capture_fps=600,one_frame_per_sample=True)).status_code == 200
    assert client.post('/api/export-video',json=data).status_code == 400
    with server.app.app_context():
        server.install_clip(export_setup[0])
    assert client.post('/api/export-video',json=data).status_code == 400


def test_failed_encoder_cleans_temporary_file_and_releases_export_lock(export_client,monkeypatch):
    client, cid = export_client
    paths = []
    def fail(path,frames,metadata):
        paths.append(path)
        path.write_bytes(b'partial')
        raise ValueError('Encoder failed')
    monkeypatch.setattr(server,'write_mp4',fail)
    for _ in range(2):
        response = client.post('/api/export-video',json=dict(id=cid,view='heatmap',key='band'))
        assert response.status_code == 400 and response.get_json()['error']=='Encoder failed'
    assert all(not p.exists() and not p.parent.exists() for p in paths)
    assert not server.video_export_lock.locked()


def test_export_rejects_non_object_settings_and_concurrent_job(export_client):
    client, cid = export_client
    for data in (None,[],42,'heatmap'):
        assert client.post('/api/export-video',json=data,content_type='application/json').status_code == 400
    server.video_export_lock.acquire()
    try:
        response = client.post('/api/export-video',json=dict(id=cid,view='heatmap',key='band'))
        assert response.status_code == 400
        assert 'in progress' in response.get_json()['error']
    finally:
        server.video_export_lock.release()


def test_only_latest_download_is_cached_and_bad_links_are_rejected(export_client,monkeypatch):
    client, cid = export_client
    def encode(path,frames,metadata):
        path.write_bytes(metadata['view'].encode())
    monkeypatch.setattr(server,'write_mp4',encode)
    heatmap = client.post('/api/export-video?prepare=1',json=dict(id=cid,view='heatmap',key='band')).get_json()
    assert client.get(heatmap['url']).data == b'heatmap'
    isolated = client.post('/api/export-video?prepare=1',json=dict(id=cid,view='isolated',key='band')).get_json()
    assert client.get(heatmap['url']).status_code == 400
    assert client.get(isolated['url']).data == b'isolated'
    assert client.get(isolated['url']+'-wrong').status_code == 400
    assert client.get('/api/export-video/stale/response.mp4').status_code == 400


def test_encoder_error_does_not_serve_a_partial_mp4(export_setup,tmp_path,monkeypatch):
    import imageio_ffmpeg
    monkeypatch.setattr(imageio_ffmpeg,'get_ffmpeg_exe',lambda: '/usr/bin/false')
    video, rendered, info, display, field, maps = export_setup
    metadata = export_metadata(video,'heatmap',85,10,0,info,field)
    with pytest.raises(ValueError,match='encoding failed'):
        write_mp4(tmp_path/'failed.mp4',export_frames(video,metadata,rendered,display),metadata)


def test_export_owns_snapshot_while_other_tab_replaces_clip(export_client,export_setup,monkeypatch):
    client, cid = export_client
    video, rendered, info, display, field, maps = export_setup
    metadata = export_metadata(video,'isolated',85,10,0,info,field)
    expected = next(export_frames(video,metadata,rendered,display))
    def replace_during_encoding(path,frames,metadata):
        with server.app.app_context():
            server.install_clip(replace(video, frames=np.zeros_like(video.frames)))
        np.testing.assert_array_equal(next(frames),expected)
        path.write_bytes(b'checked-snapshot')
    monkeypatch.setattr(server,'write_mp4',replace_during_encoding)
    assert client.post('/api/export-video',json=dict(id=cid,view='isolated',key='band')).data == b'checked-snapshot'
