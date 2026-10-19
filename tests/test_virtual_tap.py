"""Independent oscillator truth, shape projection, lifecycle and shared-video checks."""
from copy import deepcopy
from dataclasses import replace
import csv
import io
import math

import cv2
import numpy as np
import pytest

import app as server
from modal_camera.virtual_tap import build_model, configure, oscillator, simulate, tap_frame, validate_tap_settings
from modal_camera.video_export import export_metadata, export_frames


@pytest.fixture
def standing(clean):
    video = replace(clean,fps=240,encoded_fps=30,timing_basis='user-assumed capture time: one frame per captured sample')
    shape = np.array([[1.,.7,-1.],[.6,.2,-.8],[-1.,-.7,1.]])
    angle = .63
    nodes = []
    for i, value in enumerate(shape.flat):
        fits = {}
        for component, gain in [('x',.3),('y',1.)]:
            z = .4*gain*value*np.exp(1j*angle)
            fits[component] = dict(coefficients_px=[z.real,-z.imag],phase_deg=float(np.angle(z,deg=True)),amplitude_peak_px=abs(z))
        row,col = divmod(i,3)
        nodes.append(dict(index=i,x=60+30*col,y=60+30*row,fit=fits))
    field = dict(frequency_hz=95.,axis='y',nodes=nodes,grid=dict(x0=60,y0=60,step=30,columns=3,rows=3))
    model,maps = build_model(video,field)
    return video,field,model,maps,shape


def test_common_phase_rotation_recovers_signed_standing_shape(standing):
    video,field,model,_,shape = standing
    np.testing.assert_allclose([n['shape'][1] for n in model['nodes']],shape.ravel(),atol=1e-12)
    np.testing.assert_allclose([n['shape'][0] for n in model['nodes']],.3*shape.ravel(),atol=1e-12)
    assert model['standing_phase_fraction'] == pytest.approx(1.)
    rotated = deepcopy(field)
    for n in rotated['nodes']:
        for fit in n['fit'].values():
            a,b = fit['coefficients_px']
            z = complex(a,-b)*np.exp(1j*1.7)
            fit['coefficients_px'] = [z.real,-z.imag]
    recovered,_ = build_model(video,rotated)
    np.testing.assert_allclose([n['shape'] for n in recovered['nodes']], [n['shape'] for n in model['nodes']],atol=1e-12)


def test_impulse_starts_at_rest_with_chosen_velocity_and_obeys_decay(standing):
    _,_,model,_,_ = standing
    config = configure(model,dict(damping_percent=1,strength=2,tap_node=0))
    omega = 2*math.pi*95
    velocity = 2*omega*.4
    assert oscillator(model,config,0) == 0
    assert float(oscillator(model,config,1e-9)/1e-9) == pytest.approx(velocity,rel=1e-7)
    wd = omega*math.sqrt(1-.01**2)
    times = np.array([math.pi/(2*wd),math.pi/(2*wd)+2*math.pi/wd])
    values = oscillator(model,config,times)
    assert values[1]/values[0] == pytest.approx(math.exp(-.01*omega*2*math.pi/wd))
    # Finite difference checks the differential equation independently of the closed form.
    t,dt = .013,1e-6
    a,b,c = oscillator(model,config,np.array([t-dt,t,t+dt]))
    assert abs((c-2*b+a)/dt**2+2*.01*omega*(c-a)/(2*dt)+omega**2*b) < .03


def test_strength_direction_tap_participation_and_point_traces(standing):
    _,_,model,_,_ = standing
    a = simulate(model,dict(tap_node=0,probe_a=0,probe_b=2))
    doubled = simulate(model,dict(strength=2,tap_node=0,probe_a=0,probe_b=2))
    reversed_ = simulate(model,dict(direction=-1,tap_node=0,probe_a=0,probe_b=2))
    opposite = simulate(model,dict(tap_node=2,probe_a=0,probe_b=2))
    values = np.array(a['traces'][0]['displacement_source_px'])
    np.testing.assert_allclose(doubled['traces'][0]['displacement_source_px'],2*values)
    np.testing.assert_allclose(reversed_['traces'][0]['displacement_source_px'],-values)
    np.testing.assert_allclose(opposite['traces'][0]['displacement_source_px'],-values)
    np.testing.assert_allclose(a['traces'][1]['displacement_source_px'],-values)
    zero = simulate(model,dict(strength=0))
    assert not any(zero['traces'][0]['displacement_source_px'])
    assert a['seconds_to_ten_percent'] == pytest.approx(.3857555784)
    assert a['normalized_matrices']['K'][0][0] == pytest.approx((2*math.pi*95)**2)
    slow = simulate(model,dict(display_cps=1))
    assert slow['time_s'] == a['time_s']
    assert slow['display_duration_s'] == 2*a['display_duration_s']


def test_missing_samples_are_not_extrapolated_and_original_is_preserved(standing):
    video,field,model,maps,_ = standing
    original = video.frames.copy()
    config = configure(model,{})
    np.testing.assert_array_equal(tap_frame(video,model,maps,config,0),video.frames[0])
    moved = tap_frame(video,model,maps,config,1/(4*95),20)
    np.testing.assert_array_equal(moved[~maps['support']],video.frames[0][~maps['support']])
    bad = deepcopy(field)
    bad['nodes'][0]['fit']['y']['phase_deg'] = None
    smaller,limited = build_model(video,bad)
    assert smaller['nodes'][0]['shape'] is None
    assert limited['support'].sum() < maps['support'].sum()
    with pytest.raises(ValueError,match='usable'):
        configure(smaller,dict(tap_node=0))
    np.testing.assert_array_equal(video.frames,original)


@pytest.mark.parametrize('data',[None,[],dict(damping_percent=0),dict(damping_percent=5.1),dict(strength=-1),dict(strength='nan'),dict(direction=0),dict(cycles=61),dict(display_cps=0),dict(tap_node=1.2),dict(tap_node=True),dict(probe_a=300)])
def test_bad_assumptions_rejected(data):
    with pytest.raises(ValueError):
        validate_tap_settings(data)


@pytest.fixture
def tap_client(standing):
    video,field,_,_,_ = standing
    server.app.config.update(TESTING=True)
    with server.app.app_context():
        session = server.install_clip(video).get_json()
    server.state.update(field=field,field_key='field')
    return server.app.test_client(),session


def test_api_csv_session_recovery_and_stale_field_rejection(tap_client):
    client,s = tap_client
    data = dict(id=s['id'],revision=s['revision'],key='field',tap=dict(tap_node=0,probe_a=0,probe_b=2))
    response = client.post('/api/tap',json=data)
    assert response.status_code == 200,response.get_json()
    prediction = response.get_json()
    config = prediction['settings']
    ui = dict(s['ui'],view='tap',tap=config)
    assert client.post('/api/settings',json=dict(id=s['id'],revision=s['revision'],ui=ui)).status_code == 200
    assert client.get('/api/session').get_json()['ui']['tap']['damping_percent'] == 1
    prepared = client.post('/api/export-data',json=dict(data,kind='tap-traces'))
    assert prepared.status_code == 200
    download = client.get(prepared.get_json()['url'])
    rows = list(csv.DictReader(io.StringIO(download.text)))
    assert len(rows) == len(prediction['time_s'])
    assert float(rows[20]['A_simulated_source_px']) == prediction['traces'][0]['displacement_source_px'][20]
    assert 'assumed' in rows[20]['interpretation'].lower()
    image = client.get(f"/api/frame/{s['id']}/0?view=tap&key=field&time=0.01&tap_node=0")
    assert image.status_code == 200 and image.mimetype == 'image/jpeg'
    assert client.get(f"/api/frame/{s['id']}/0?view=tap&key=field&time=-1").status_code == 400
    assert client.post('/api/tap',json=dict(data,key='old')).status_code == 400
    assert client.post('/api/tap',json=dict(data,revision='old')).status_code == 400
    changed = dict(s['settings'],frequency=90)
    assert client.post('/api/settings',json=dict(id=s['id'],revision=s['revision'],settings=changed)).status_code == 200
    for route in ('/api/tap','/api/export-video'):
        assert client.post(route,json=dict(data,view='tap')).status_code == 400
    assert server.state.get('tap_model') is None


def test_tap_mp4_has_truthful_timing_provenance_and_matching_preview(tap_client,standing,tmp_path):
    client,s = tap_client
    video,field,model,maps,_ = standing
    options = dict(cycles=5,display_cps=5,tap_node=0,probe_a=0,probe_b=2,damping_percent=2)
    prediction = simulate(model,options)
    metadata = export_metadata(video,'tap',85,8,0,tap=prediction)
    assert metadata['playback_slowdown'] == 19
    assert metadata['export_frames'] == 31
    prepared = client.post('/api/export-video?prepare=1',json=dict(id=s['id'],revision=s['revision'],key='field',view='tap',modal_gain=8,tap=options))
    assert prepared.status_code == 200,prepared.get_json()
    payload = client.get(prepared.get_json()['url']).data
    assert b'not an identified eigenmode' in payload and b'damping_percent' in payload
    assert b'user-assumed capture time' in payload
    path = tmp_path/'tap.mp4';path.write_bytes(payload)
    cap = cv2.VideoCapture(str(path))
    assert cap.get(cv2.CAP_PROP_FRAME_COUNT) == 31
    assert cap.get(cv2.CAP_PROP_FPS) == 30
    expected = iter(export_frames(video,metadata,tap_maps=maps))
    for i in range(31):
        ok,frame = cap.read()
        assert ok
        rgb = cv2.cvtColor(frame,cv2.COLOR_BGR2RGB)
        assert np.abs(rgb.astype(float)-next(expected)).mean() < 3
    cap.release()


def test_quadrature_loss_is_reported_and_sparse_maps_rejected(standing):
    video,field,_,_,_ = standing
    mixed = deepcopy(field)
    for n in mixed['nodes'][:4]:
        for fit in n['fit'].values():
            a,b = fit['coefficients_px'];fit['coefficients_px'] = [b,-a]
    projected,_ = build_model(video,mixed)
    assert .5 <= projected['standing_phase_fraction'] < .9
    sparse = deepcopy(field)
    for n in sparse['nodes']:
        if n['index'] not in (0,2,6,8):
            n['fit']['y']['phase_deg'] = None
    with pytest.raises(ValueError,match='no supported cells'):
        build_model(video,sparse)
    for n in sparse['nodes']:
        n['fit']['y']['phase_deg'] = None
    with pytest.raises(ValueError,match='four usable'):
        build_model(video,sparse)
