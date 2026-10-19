"""Plate benchmarks, shape fitting, reciprocal modal impulses and actual warps."""
from copy import deepcopy
import csv
import io
import json
import math
from urllib.parse import urlencode

import cv2
import numpy as np
from numpy.polynomial.legendre import leggauss
import pytest

import app as server
from modal_camera.plate_modes import validate_plate_settings, solve_plate, evaluate, build_plate_model
from modal_camera.processing import Video
from modal_camera.virtual_tap import configure, plate_coordinates, simulate, tap_frame
from modal_camera.video_export import export_metadata, export_frames


def test_simply_supported_plate_matches_analytic_bending_frequencies():
    # Kirchhoff-Love SSSS omega = pi² sqrt(D/rhoh) ((m/a)²+(n/b)²).
    expected = sorted(math.pi**2*((m/2)**2+n*n) for m in range(1, 10) for n in range(1, 10))[:8]
    for poisson in (.1, .33, .49):
        solution = solve_plate(validate_plate_settings(dict(mounting='simply-supported', poisson=poisson)))
        np.testing.assert_allclose(np.sqrt(solution['eigenvalues']), expected, rtol=2e-4)
        edges = evaluate(solution, [[0,.3],[1,.7],[.6,0],[.4,1]])
        np.testing.assert_allclose(edges, 0, atol=1e-10)


def test_free_plate_refinement_and_peak_normalized_modal_mass():
    cfg = validate_plate_settings({})
    coarse, fine = solve_plate(cfg, order=9), solve_plate(cfg, order=11)
    assert fine['rigid_modes_removed'] == 3
    assert (fine['eigenvalues'] > 0).all()
    np.testing.assert_allclose(np.sqrt(coarse['eigenvalues']), np.sqrt(fine['eigenvalues']), rtol=.002)
    # Independent integration: peak-normalized mass must not be forced to I.
    g, weights = leggauss(16)
    u,v = np.meshgrid((g+1)/2, (g+1)/2)
    shapes = evaluate(fine, np.column_stack([u.ravel(), v.ravel()]))
    integral = shapes.T @ (np.outer(weights, weights).ravel()[:,None]/4*shapes)
    np.testing.assert_allclose(integral, np.diag(fine['modal_mass']), atol=1e-9)
    assert not np.allclose(fine['modal_mass'], 1)


def test_mount_stiffness_changes_shape_and_frequency_ratios():
    free = solve_plate(validate_plate_settings({}))
    supported = solve_plate(validate_plate_settings(dict(mounting='center')), order=15)
    assert supported['rigid_modes_removed'] == 0
    assert not np.allclose(free['eigenvalues']/free['eigenvalues'][0], supported['eigenvalues']/supported['eigenvalues'][0])
    stiff = solve_plate(validate_plate_settings(dict(mounting='center', mount_stiffness=50000)), order=15)
    assert (stiff['eigenvalues'] >= supported['eigenvalues']-1e-6).all()


@pytest.fixture
def plate():
    rng = np.random.default_rng(42)
    # Grayscale texture avoids testing intentional H.264 4:2:0 chroma loss on
    # independent per-pixel RGB noise rather than the simulation renderer.
    frame = np.repeat(rng.integers(30, 220, (180,300,1), dtype=np.uint8), 3, axis=2)
    video = Video(np.repeat(frame[None], 40, axis=0), 240, 600, 360, 'synthetic-plate.avi', [], encoded_fps=30)
    cfg = validate_plate_settings(dict(corners=[[20,20],[280,20],[280,160],[20,160]]))
    solution = solve_plate(cfg)
    x,y = np.meshgrid(np.linspace(40,260,7), np.linspace(35,145,5))
    uv = np.column_stack([(x.ravel()-20)/260, (y.ravel()-20)/140])
    truth = evaluate(solution, uv)[:,2]
    nodes=[]
    for i,(xx,yy,value) in enumerate(zip(x.ravel(),y.ravel(),truth)):
        z = .4*value*np.exp(.67j)
        fits = {axis:dict(coefficients_px=[z.real*gain,-z.imag*gain],phase_deg=float(np.angle(z,deg=True)),amplitude_peak_px=abs(z)*gain) for axis,gain in [('x',.2),('y',1.)]}
        nodes.append(dict(index=i,x=float(xx),y=float(yy),fit=fits))
    field = dict(axis='y',frequency_hz=95.,nodes=nodes,grid=dict(x0=40,y0=35,step=36,columns=7,rows=5))
    model,maps = build_plate_model(video,field,cfg)
    return video,field,model,maps,cfg


def test_shape_match_finds_third_mode_and_scales_every_frequency(plate):
    video,field,model,_,cfg = plate
    assert model['anchor_mode'] == 2
    assert model['fit_mac'] == pytest.approx(1)
    assert model['fit_samples'] == 35
    assert model['modes'][2]['frequency_hz'] == pytest.approx(95)
    assert model['max_basis_change_percent'] < .2
    doubled = deepcopy(field);doubled['frequency_hz'] = 190
    other,_ = build_plate_model(video,doubled,cfg)
    np.testing.assert_allclose([m['frequency_hz'] for m in other['modes']], [2*m['frequency_hz'] for m in model['modes']])
    override,_ = build_plate_model(video,field,dict(cfg,anchor_mode=0))
    assert override['anchor_mode'] == 0 and override['fit_mac'] < 1
    assert override['modes'][0]['frequency_hz'] == pytest.approx(95)


def test_combined_impulse_superposition_reciprocity_and_velocity(plate):
    _,_,model,_,_ = plate
    options = dict(model_source='plate',plate=model['plate'],enabled_modes=[0,2,5],tap_node=0,probe_a=0,probe_b=34,cycles=5)
    cfg = configure(model, options)
    times = np.linspace(0,.03,501)
    all_q = plate_coordinates(model,cfg,times)
    individual = [plate_coordinates(model,configure(model,dict(options,enabled_modes=[i])),times) for i in [0,2,5]]
    np.testing.assert_allclose(all_q, sum(individual))
    assert not plate_coordinates(model,cfg,0).any()
    m = model['modes'][2];anchor=model['modes'][model['anchor_mode']]
    impulse = 2*math.pi*95*model['reference_amplitude_source_px']*anchor['modal_mass']
    expected_velocity=impulse*model['nodes'][0]['modes'][2]/m['modal_mass']
    assert plate_coordinates(model,cfg,1e-10)[2]/1e-10 == pytest.approx(expected_velocity,rel=1e-6)
    a = simulate(model,options)
    b = simulate(model,dict(options,tap_node=34,probe_a=34,probe_b=0))
    np.testing.assert_allclose(a['traces'][1]['displacement_source_px'],b['traces'][1]['displacement_source_px'],atol=1e-12)
    doubled = simulate(model,dict(options,strength=2))
    np.testing.assert_allclose(doubled['traces'][0]['displacement_source_px'],2*np.array(a['traces'][0]['displacement_source_px']))
    slow = simulate(model,dict(options,display_cps=1))
    assert slow['time_s'] == a['time_s']
    assert a['settings']['max_frequency_hz']/a['playback_slowdown'] <= 2+1e-10
    assert max(np.diff(a['time_s'])) <= 1/(24*a['settings']['max_frequency_hz'])+1e-12


def test_higher_mode_moves_texture_only_on_plate_with_its_own_clock(plate):
    video,_,model,maps,cfg = plate
    settings = configure(model,dict(model_source='plate',plate=cfg,motion='mode',solo_mode=7,strength=2))
    f=model['modes'][7]['frequency_hz']
    assert f > video.fps/2
    assert settings['clock_hz'] == f
    times=np.array([0, .25/f, .5/f, .75/f, 1/f])
    q=plate_coordinates(model,settings,times)
    np.testing.assert_allclose(q[7],2*model['reference_amplitude_source_px']*np.array([0,1,0,-1,0]),atol=1e-12)
    np.testing.assert_array_equal(tap_frame(video,model,maps,settings,0),video.frames[0])
    moved=tap_frame(video,model,maps,settings,.25/f,20)
    np.testing.assert_array_equal(moved[~maps['support']],video.frames[0][~maps['support']])
    assert np.abs(moved.astype(float)-video.frames[0])[maps['support']].mean() > 5
    different=dict(settings,solo_mode=0,active_modes=[0])
    assert not np.array_equal(moved,tap_frame(video,model,maps,different,.25/95,20))
    zero=dict(settings,strength=0)
    np.testing.assert_array_equal(tap_frame(video,model,maps,zero,.25/f),video.frames[0])


@pytest.mark.parametrize('settings',[
    dict(aspect_ratio=0),dict(aspect_ratio='nan'),dict(poisson=.5),dict(mounting='clamped'),
    dict(corners=[[0,0],[100,100],[0,100],[100,0]]), dict(corners=[[0,0]]),dict(anchor_mode=True),
    dict(corners=[[0,0],[1,0],[1,1],[0,1]])])
def test_invalid_plate_assumptions_rejected(settings):
    with pytest.raises(ValueError): validate_plate_settings(settings)


def test_missing_outline_samples_and_bad_projection_are_actionable(plate):
    video,field,_,_,cfg=plate
    for bad,match in [(dict(cfg,corners=None),'four plate corners'),(dict(cfg,projection_angle_deg=0),'Projection'),
                      (dict(cfg,corners=[[0,0],[400,0],[400,160],[0,160]]),'inside')]:
        with pytest.raises(ValueError,match=match): build_plate_model(video,field,bad)
    sparse=deepcopy(field)
    for n in sparse['nodes'][4:]:n['fit']['y']['phase_deg']=None
    with pytest.raises(ValueError,match='six usable'):build_plate_model(video,sparse,cfg)


def test_predicted_api_session_exports_and_model_identity(plate,tmp_path):
    video,field,model,maps,cfg=plate
    with server.app.app_context():s=server.install_clip(video).get_json()
    server.state.update(field=field,field_key='field')
    client=server.app.test_client()
    options=dict(model_source='plate',plate=cfg,motion='mode',solo_mode=7,cycles=5,display_cps=5)
    data=dict(id=s['id'],revision=s['revision'],key='field',tap=options)
    response=client.post('/api/tap',json=data)
    assert response.status_code == 200,response.get_json()
    prediction=response.get_json()
    ui=dict(s['ui'],view='tap',tap=prediction['settings'])
    assert client.post('/api/settings',json=dict(id=s['id'],revision=s['revision'],ui=ui)).status_code == 200
    restored=client.get('/api/session').get_json()
    assert restored['ui']['tap']['plate']==cfg and restored['field_key']=='field'
    assert restored['revision']==s['revision']
    query=urlencode(dict(view='tap',key='field',model_key=prediction['model']['key'],tap=json.dumps(options),time=.001))
    assert client.get(f"/api/frame/{s['id']}/0?{query}").status_code==200
    changed=dict(options,plate=dict(cfg,aspect_ratio=2.5))
    other=client.post('/api/tap',json=dict(data,tap=changed)).get_json()
    assert other['model']['key']!=prediction['model']['key']
    assert client.get(f"/api/frame/{s['id']}/0?{query}").status_code==200
    badquery=urlencode(dict(view='tap',key='field',model_key='stale',tap=json.dumps(options),time=.001))
    assert client.get(f"/api/frame/{s['id']}/0?{badquery}").status_code==400
    for kind in ['tap-traces','tap-model']:
        prepared=client.post('/api/export-data',json=dict(data,kind=kind));assert prepared.status_code==200
        download=client.get(prepared.get_json()['url'])
        if kind=='tap-model':
            result=download.get_json();assert result['model']['plate']==cfg and result['settings']['solo_mode']==7
        else:
            rows=list(csv.DictReader(io.StringIO(download.text)))
            assert rows[10]['model_source']=='plate' and 'corners' in rows[10]['geometry_and_mounting_json']
            assert float(rows[10]['A_simulated_source_px'])==prediction['traces'][0]['displacement_source_px'][10]
    prepared=client.post('/api/export-video?prepare=1',json=dict(data,view='tap',modal_gain=8))
    assert prepared.status_code==200,prepared.get_json()
    payload=client.get(prepared.get_json()['url']).data
    assert b'not measured higher modes' in payload and b'aspect_ratio' in payload
    path=tmp_path/'predicted.mp4';path.write_bytes(payload)
    cap=cv2.VideoCapture(str(path));assert cap.get(cv2.CAP_PROP_FRAME_COUNT)==76
    assert cap.get(cv2.CAP_PROP_FPS)==30
    metadata=export_metadata(video,'tap',85,8,0,tap=simulate(model,options))
    for expected in export_frames(video,metadata,tap_maps=maps):
        ok,frame=cap.read();assert ok
        assert np.abs(cv2.cvtColor(frame,cv2.COLOR_BGR2RGB).astype(float)-expected).mean()<4
    cap.release()
    assert client.post('/api/tap',json=dict(data,key='stale')).status_code==400
    assert client.post('/api/tap',json=dict(data,tap=dict(options,enabled_modes=[]))).status_code==400
