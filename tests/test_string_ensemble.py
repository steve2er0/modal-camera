"""Independent-string mechanics, shared plucks, texture composition and exports."""
from copy import deepcopy
import csv
import io
import json
import math

import cv2
import numpy as np
import pytest

import app as server
import modal_camera.string_modes as strings
from modal_camera.processing import Video
from modal_camera.virtual_tap import configure, plate_coordinates, simulate, tap_frame
from modal_camera.video_export import export_metadata, export_frames


@pytest.fixture
def ensemble(monkeypatch):
    h,w=120,180
    image=np.full((h,w,3),180,np.uint8)
    entries=[]
    for i,(y,f,amplitude) in enumerate([(30,80,.15),(78,108,.1)]):
        a,b=[24,y],[164,y+5]
        cv2.line(image,tuple(a),tuple(b),(20,20,20),1)
        entries.append(dict(name=['Bass','Treble'][i],endpoints=[a,b],anchor_hz=f,span_start=0,span_end=1))
    video=Video(np.repeat(image[None],300,axis=0),600,w,h,'two-strings.avi',[],encoded_fps=30)
    cfg=strings.validate_string_settings(dict(strings=entries))
    field=dict(axis='y',frequency_hz=80.,reference_last=False)
    def tracker(v,coords):
        t=np.arange(len(v.frames))/v.fps
        traces=[]
        for p in coords:
            i=int(p[1]>55);entry=entries[i];a,b=np.array(entry['endpoints'],float)
            u=np.dot(np.array(p)-a,b-a)/np.dot(b-a,b-a)
            dy=[.15,.1][i]*np.sin(math.pi*u)*np.cos(2*math.pi*entry['anchor_hz']*t+.3)
            traces.append(dict(x=p[0],y=p[1],dy=dy.tolist(),dx=(dy*0).tolist()))
        return traces
    monkeypatch.setattr(strings,'track_locations',tracker)
    model,maps=strings.build_string_model(video,field,cfg)
    return video,field,cfg,model,maps


def test_separate_anchors_fits_and_block_diagonal_matrices(ensemble):
    _,_,cfg,model,_=ensemble
    assert [s['reference_amplitude_source_px'] for s in model['strings']]==pytest.approx([.15,.1],rel=1e-6)
    np.testing.assert_allclose([m['frequency_hz'] for m in model['modes']],np.r_[80*np.arange(1,9),108*np.arange(1,9)])
    prediction=simulate(model,dict(model_source='string',string=cfg))
    assert prediction['settings']['active_modes']==[0,1,2,8,9,10]
    assert prediction['traces'][0]['string_index']==0 and prediction['traces'][1]['string_index']==1
    for matrix in prediction['normalized_matrices'].values():
        if isinstance(matrix,list):
            a=np.array(matrix)
            assert a.shape==(16,16)
            np.testing.assert_array_equal(a,np.diag(np.diag(a)))
    assert 'per independent string' in prediction['normalized_matrices']['units']


def test_shared_fraction_simultaneity_nodal_suppression_and_analytic_response(ensemble):
    _,_,cfg,model,_=ensemble
    options=dict(model_source='string',string=cfg,enabled_modes=[0,1,2,8,9,10],tap_node=6,strength=2)
    settings=configure(model,options);assert settings['tap_fraction']==.25
    t=np.linspace(0,.04,1001)
    q=plate_coordinates(model,settings,t)
    assert not q[:,0].any()
    for i in settings['active_modes']:
        mode=model['modes'][i];w=2*math.pi*mode['frequency_hz'];wd=w*math.sqrt(1-.01**2)
        amplitude=[.15,.1][mode['string_index']]
        velocity=2*2*math.pi*[80,108][mode['string_index']]*amplitude*math.sin(mode['harmonic']*math.pi*.25)
        expected=velocity/wd*np.exp(-.01*w*t)*np.sin(wd*t)
        np.testing.assert_allclose(q[i],expected,atol=1e-8)
    # Selecting the same u on the other string drives the identical shared pluck.
    other=configure(model,dict(options,tap_node=31))
    np.testing.assert_allclose(plate_coordinates(model,other,t),q)
    at_node=configure(model,dict(options,tap_node=12))
    nodal_q=plate_coordinates(model,at_node,t)
    assert abs(nodal_q[[1,9]]).max()<1e-15
    assert abs(nodal_q[0]).max()>.1 and abs(nodal_q[8]).max()>.1
    # Equal relative strength preserves each string's chosen frequency/scale,
    # rather than pretending to impose one force-calibrated guitar impulse.
    assert q[0,1]!=q[8,1]


def test_superposition_common_slowdown_and_cross_string_traces(ensemble):
    _,_,cfg,model,_=ensemble
    options=dict(model_source='string',string=cfg,enabled_modes=[0,2,8,9],tap_node=6,probe_a=6,probe_b=31,cycles=5)
    settings=configure(model,options);t=np.linspace(0,.02,1001)
    q=plate_coordinates(model,settings,t)
    summed=sum(plate_coordinates(model,configure(model,dict(options,enabled_modes=[i])),t) for i in options['enabled_modes'])
    np.testing.assert_allclose(q,summed,atol=1e-14)
    p=simulate(model,options)
    assert p['playback_slowdown']>=max(model['modes'][i]['frequency_hz'] for i in options['enabled_modes'])/2
    assert p['traces'][0]['sample']=='Bass · point 7' and p['traces'][1]['sample']=='Treble · point 7'
    for j,indices in enumerate([[0,2],[8,9]]):
        coords=plate_coordinates(model,p['settings'],np.array(p['time_s']))
        node=model['nodes'][[6,31][j]]
        expected=sum(coords[i]*node['modes'][i] for i in indices)
        np.testing.assert_allclose(p['traces'][j]['displacement_source_px'],expected)
    doubled=plate_coordinates(model,configure(model,dict(options,strength=2)),t)
    np.testing.assert_allclose(doubled,2*q)


def test_both_real_string_textures_move_zero_response_and_disabled_string(ensemble):
    video,field,cfg,model,maps=ensemble
    options=dict(model_source='string',string=cfg,enabled_modes=[0,8],tap_node=6,strength=3)
    settings=configure(model,options);original=video.frames[0].copy()
    for t,gain,options_ in [(0,20,settings),(.002,0,settings),(.002,20,configure(model,dict(options,strength=0)))]:
        np.testing.assert_array_equal(tap_frame(video,model,maps,options_,t,gain),original)
    moved=tap_frame(video,model,maps,settings,.002,20)
    assert np.abs(moved[15:45].astype(float)-original[15:45]).sum()>1000
    assert np.abs(moved[63:95].astype(float)-original[63:95]).sum()>1000
    assert np.any(moved[~maps['support']]!=original[~maps['support']])
    far=cv2.dilate(maps['support'].astype(np.uint8),np.ones((41,41),np.uint8))==0
    np.testing.assert_array_equal(moved[far],original[far])
    np.testing.assert_array_equal(video.frames[0],original)
    disabled=deepcopy(cfg);disabled['strings'][1]['enabled']=False
    single,one_map=strings.build_string_model(video,field,disabled)
    settings=configure(single,dict(model_source='string',string=disabled,enabled_modes=[0],tap_node=6,strength=3))
    only=tap_frame(video,single,one_map,settings,.002,20)
    np.testing.assert_array_equal(only[63:95],original[63:95])
    assert len(single['modes'])==8 and len(single['string']['strings'])==2


def test_overlapping_ribbons_reconstruct_once_and_are_order_independent(ensemble):
    video,field,cfg,_,_=ensemble
    overlap=deepcopy(cfg)
    overlap['strings'][1].update(endpoints=[[24,28],[164,42]],amplitude_source_px=.1)
    model,maps=strings.build_string_model(video,field,overlap)
    q=np.zeros(16);q[0]=.1;q[8]=-.08
    forward=strings.string_frame(video,model,maps,q,10)
    reverse=deepcopy(overlap);reverse['strings'].reverse()
    other,other_maps=strings.build_string_model(video,field,reverse)
    backward=strings.string_frame(video,other,other_maps,np.r_[q[8:],q[:8]],10)
    assert np.abs(forward.astype(int)-backward.astype(int)).max()<=1
    np.testing.assert_array_equal(strings.string_frame(video,model,maps,q*0,10),video.frames[0])


def test_six_strings_48_modes_and_assumed_above_nyquist_anchor(ensemble,monkeypatch):
    video,field,cfg,_,_=ensemble
    six=dict(strings=[dict(cfg['strings'][i%2],name=f'String {i+1}',amplitude_source_px=.1,anchor_hz=330 if i==5 else 80+i*10) for i in range(6)])
    model,_=strings.build_string_model(video,field,six)
    options=dict(model_source='string',string=six,enabled_modes=list(range(48)),solo_mode=47,cycles=5)
    assert len(model['modes'])==48
    settings=configure(model,options)
    assert len(settings['active_modes'])==48 and settings['max_frequency_hz']==2640
    last=model['strings'][-1];assert last['fit_samples']==0 and last['amplitude_basis']=='user-assumed'
    bad=deepcopy(six);bad['strings'][-1]['amplitude_source_px']=None
    with pytest.raises(ValueError,match='Nyquist'):strings.build_string_model(video,field,bad)
    with pytest.raises(ValueError,match='different string model'):
        one,_=strings.build_string_model(video,field,dict(strings=[cfg['strings'][0]]))
        configure(one,options)


@pytest.mark.parametrize('data',[
    dict(strings=[]),dict(strings=[{}]*7),dict(strings=[dict(strings=[])]),
    dict(strings=[dict(enabled=False)]),dict(strings=[dict(name='')]),
    dict(strings=[dict(enabled=1)]),dict(strings=[dict(anchor_hz='nan')]),
    dict(strings=[dict(anchor_hz=True)]),
    dict(strings=[dict(anchor_hz=0)]),dict(strings=[dict(anchor_hz=2001)]),
])
def test_bad_ensemble_assumptions(data):
    with pytest.raises(ValueError):strings.validate_string_settings(data)


def test_api_session_cache_names_geometry_and_mp4_export(ensemble,tmp_path):
    video,field,cfg,model,maps=ensemble
    with server.app.app_context():session=server.install_clip(video).get_json()
    server.state.update(field=field,field_key='multi-field')
    client=server.app.test_client()
    options=dict(model_source='string',string=cfg,enabled_modes=[0,1,8,9],tap_node=6,probe_a=6,probe_b=31,cycles=5)
    body=dict(id=session['id'],revision=session['revision'],key='multi-field',tap=options)
    r=client.post('/api/tap',json=body);assert r.status_code==200,r.get_json()
    p=r.get_json();key=p['model']['key']
    ui=dict(session['ui'],view='tap',tap=p['settings'])
    assert client.post('/api/settings',json=dict(body,ui=ui)).status_code==200
    saved=client.get('/api/session').get_json()['ui']['tap']
    assert saved['string']==cfg and saved['enabled_modes']==[0,1,8,9] and saved['probe_b']==31
    changed=deepcopy(options);changed['string']['strings'][1].update(anchor_hz=110,amplitude_source_px=.1)
    r=client.post('/api/tap',json=dict(body,tap=changed));assert r.status_code==200,r.get_json()
    modified=r.get_json()
    assert modified['model']['key']!=key
    invalid=deepcopy(changed);invalid['string']['strings'][1]['endpoints']=None
    assert client.post('/api/tap',json=dict(body,tap=invalid)).status_code==400
    assert server.state['tap_model_key']==modified['model']['key']
    for kind in ['tap-model','tap-traces']:
        r=client.post('/api/export-data',json=dict(body,kind=kind));assert r.status_code==200,r.get_json()
        export=client.get(r.get_json()['url'])
        if kind=='tap-model':
            assert export.get_json()['model']['string']==cfg
            assert len(export.get_json()['normalized_matrices']['M'])==16
        else:
            row=next(csv.DictReader(io.StringIO(export.text)))
            assert row['probe_A_sample']=='Bass · point 7' and row['probe_B_sample']=='Treble · point 7'
            assert float(row['shared_string_pluck_fraction'])==.25
            assert len(json.loads(row['geometry_and_mounting_json'])['strings'])==2
    r=client.post('/api/export-video?prepare=1',json=dict(body,view='tap',modal_gain=10))
    assert r.status_code==200,r.get_json()
    payload=client.get(r.get_json()['url']).data
    assert b'independent string ensemble' in payload and b'anchor_hz' in payload
    path=tmp_path/'two-strings.mp4';path.write_bytes(payload)
    cap=cv2.VideoCapture(str(path));assert cap.isOpened() and cap.get(cv2.CAP_PROP_FPS)==30
    prediction=simulate(model,options);meta=export_metadata(video,'tap',85,10,0,tap=prediction)
    decoded=0
    for expected in export_frames(video,meta,tap_maps=maps):
        ok,frame=cap.read();assert ok
        assert np.abs(cv2.cvtColor(frame,cv2.COLOR_BGR2RGB).astype(float)-expected).mean()<3
        decoded+=1
    assert decoded==meta['export_frames']
    assert not cap.read()[0];cap.release()
