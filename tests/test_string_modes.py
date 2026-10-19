"""Analytic string modes, original-patch fitting, projected warps and API lifecycle."""
from copy import deepcopy
import json
import math
from urllib.parse import urlencode

import cv2
import numpy as np
import pytest

import app as server
import modal_camera.string_modes as strings
from modal_camera.processing import Video
from modal_camera.virtual_tap import configure,plate_coordinates,simulate,tap_frame
from modal_camera.video_export import export_metadata,export_frames


def test_analytic_harmonics_support_nodes_and_consistent_mass():
    np.testing.assert_allclose(strings.string_frequencies(80),80*np.arange(1,9))
    np.testing.assert_allclose(strings.string_frequencies(160,2),80*np.arange(1,9))
    n=np.arange(1,9)
    u=np.linspace(0,1,10001);phi=strings.string_shapes(u)
    np.testing.assert_allclose(phi[[0,-1]],0,atol=1e-14)
    mass=np.trapezoid(phi[:,:,None]*phi[:,None,:],u,axis=0)
    np.testing.assert_allclose(mass,np.eye(8)*.5,atol=1e-13)
    for mode in range(1,9):
        np.testing.assert_allclose(strings.string_shapes(np.arange(mode+1)/mode)[:,mode-1],0,atol=1e-14)
    # Pinned stiff-string dispersion, anchored consistently at harmonic 2.
    f=strings.string_frequencies(160,2,.01)
    assert f[1]==160 and f[7]>640
    np.testing.assert_allclose(f,160*n/2*np.sqrt((1+.01*n*n)/(1+.01*4)))


@pytest.fixture
def string_model(monkeypatch):
    h,w=96,180
    image=np.full((h,w,3),180,np.uint8)
    a,b=np.array([24.,30.]),np.array([164.,55.])
    cv2.line(image,tuple(a.astype(int)),tuple(b.astype(int)),(20,20,20),1)
    video=Video(np.repeat(image[None],240,axis=0),600,w,h,'test-string.avi',[],encoded_fps=30)
    cfg=strings.validate_string_settings(dict(endpoints=[a.tolist(),b.tolist()],span_start=.25,span_end=.75,anchor_harmonic=2))
    field=dict(axis='y',frequency_hz=80.,reference_last=False)
    def tracker(v,coords):
        t=np.arange(len(v.frames))/v.fps
        traces=[]
        for i,p in enumerate(coords):
            s=np.dot(np.array(p)-a,b-a)/np.dot(b-a,b-a)
            u=.25+.5*s
            dy=.15*np.sin(2*math.pi*u)*np.cos(2*math.pi*80*t+.3)
            traces.append(dict(x=p[0],y=p[1],dy=dy.tolist(),dx=(-.1*dy).tolist()))
        return traces
    monkeypatch.setattr(strings,'track_locations',tracker)
    model,maps=strings.build_string_model(video,field,cfg)
    return video,field,cfg,model,maps


def test_partial_span_fits_original_patches_and_explicit_harmonic(string_model):
    video,field,cfg,model,maps=string_model
    assert model['anchor_mode']==1 and model['modes'][1]['frequency_hz']==80
    assert model['reference_amplitude_source_px']==pytest.approx(.15,rel=1e-6)
    assert model['fit_mac']==pytest.approx(1,abs=1e-12)
    assert model['fit_samples']>=3
    assert model['nodes'][0]['u']==.25 and model['nodes'][-1]['u']==.75
    # A cropped image endpoint can move: only u=0,1 are fixed supports.
    assert model['nodes'][0]['modes'][0]==pytest.approx(math.sin(math.pi/4))
    assert model['modes'][7]['frequency_hz']>video.fps/2
    assert model['sample_label']=='String point'
    other,_=strings.build_string_model(video,field,dict(cfg,anchor_harmonic=1,amplitude_source_px=.2))
    assert other['reference_amplitude_source_px']==.2 and other['amplitude_basis']=='user-assumed'
    assert other['modes'][7]['frequency_hz']==640


def test_node_tap_suppression_superposition_and_reciprocity(string_model):
    _,_,cfg,model,_=string_model
    options=dict(model_source='string',string=cfg,enabled_modes=[0,1,2],cycles=5,tap_node=12,probe_a=3,probe_b=20)
    settings=configure(model,options);times=np.linspace(0,.025,1001)
    q=plate_coordinates(model,settings,times)
    assert abs(q[1]).max()<1e-15  # u=.5 is a node of harmonic 2
    np.testing.assert_allclose(q,sum(plate_coordinates(model,configure(model,dict(options,enabled_modes=[i])),times) for i in [0,1,2]),atol=1e-15)
    assert not plate_coordinates(model,settings,0).any()
    first=simulate(model,dict(options,tap_node=3,probe_b=20))
    second=simulate(model,dict(options,tap_node=20,probe_b=3))
    np.testing.assert_allclose(first['traces'][1]['displacement_source_px'],second['traces'][1]['displacement_source_px'],atol=1e-13)
    assert first['normalized_matrices']['M'][0][0]==.5
    assert first['settings']['max_frequency_hz']/first['playback_slowdown']<=2
    doubled=simulate(model,dict(options,strength=2))
    single=simulate(model,options)
    np.testing.assert_allclose(doubled['traces'][0]['displacement_source_px'],2*np.array(single['traces'][0]['displacement_source_px']))


def test_actual_string_texture_moves_and_background_is_static(string_model):
    video,_,cfg,model,maps=string_model
    options=dict(model_source='string',string=cfg,motion='mode',solo_mode=2,cycles=5,strength=2)
    settings=configure(model,options);frequency=model['modes'][2]['frequency_hz']
    np.testing.assert_array_equal(tap_frame(video,model,maps,settings,0,10),video.frames[0])
    np.testing.assert_array_equal(tap_frame(video,model,maps,settings,.25/frequency,0),video.frames[0])
    moved=tap_frame(video,model,maps,settings,.25/frequency,10)
    assert np.abs(moved.astype(float)-video.frames[0]).sum()>1000
    # The selected ribbon can travel beyond its old mask, while distant body
    # pixels remain identical. This rejects an overlay-only animation.
    assert np.any(moved[~maps['support']]!=video.frames[0][~maps['support']])
    distant=cv2.dilate(maps['support'].astype(np.uint8),np.ones((21,21),np.uint8))==0
    np.testing.assert_array_equal(moved[distant],video.frames[0][distant])
    tiny=tap_frame(video,model,maps,settings,1e-14,10)
    np.testing.assert_array_equal(tiny,video.frames[0])
    np.testing.assert_array_equal(tap_frame(video,model,maps,dict(settings,strength=0),.25/frequency,10),video.frames[0])
    other=configure(model,dict(options,solo_mode=0))
    assert not np.array_equal(moved,tap_frame(video,model,maps,other,.25/model['modes'][0]['frequency_hz'],10))


@pytest.mark.parametrize('data',[None,dict(endpoints=[[1,2]]),dict(endpoints=[[1,2],[1,3]]),dict(span_start=.8,span_end=.2),dict(span_end='nan'),dict(half_width_px=9),dict(anchor_harmonic=True),dict(anchor_harmonic=9),dict(inharmonicity=-1),dict(amplitude_source_px=0)])
def test_bad_assumptions(data):
    with pytest.raises(ValueError):strings.validate_string_settings(data)


def test_missing_measurements_require_explicit_amplitude(string_model,monkeypatch):
    video,field,cfg,_,_=string_model
    monkeypatch.setattr(strings,'harmonic_fit',lambda *args:None)
    with pytest.raises(ValueError,match='three usable'):strings.build_string_model(video,field,cfg)
    model,_=strings.build_string_model(video,field,dict(cfg,amplitude_source_px=.3))
    assert model['fit_samples']==0 and model['fit_mac'] is None and model['amplitude_basis']=='user-assumed'
    with pytest.raises(ValueError,match='transverse'):strings.build_string_model(video,dict(field,axis='x'),dict(cfg,endpoints=[[25,40],[160,40]]))
    with pytest.raises(ValueError,match='inside'):strings.build_string_model(video,field,dict(cfg,endpoints=[[0,40],[200,40]]))


def test_api_model_identity_session_and_video_export(string_model,tmp_path):
    video,field,cfg,model,maps=string_model
    with server.app.app_context():session=server.install_clip(video).get_json()
    server.state.update(field=field,field_key='field')
    client=server.app.test_client()
    options=dict(model_source='string',string=cfg,motion='mode',solo_mode=2,cycles=5,display_cps=5)
    body=dict(id=session['id'],revision=session['revision'],key='field',tap=options)
    response=client.post('/api/tap',json=body);assert response.status_code==200,response.get_json()
    prediction=response.get_json();key=prediction['model']['key']
    ui=dict(session['ui'],view='tap',tap=prediction['settings'])
    assert client.post('/api/settings',json=dict(id=session['id'],revision=session['revision'],ui=ui)).status_code==200
    assert client.get('/api/session').get_json()['ui']['tap']['string']==cfg
    new=client.post('/api/tap',json=dict(body,tap=dict(options,string=dict(cfg,span_end=.8)))).get_json()
    assert new['model']['key']!=key
    query=urlencode(dict(view='tap',key='field',model_key=key,tap=json.dumps(options),time=.001))
    assert client.get(f"/api/frame/{session['id']}/0?{query}").status_code==200
    for kind in ['tap-model','tap-traces']:
        r=client.post('/api/export-data',json=dict(body,kind=kind));assert r.status_code==200
        output=client.get(r.get_json()['url']);assert b'anchor_harmonic' in output.data
        if kind=='tap-model':assert output.get_json()['model']['string']==cfg
        else:assert b'String point' in output.data
    r=client.post('/api/export-video?prepare=1',json=dict(body,view='tap',modal_gain=10));assert r.status_code==200,r.get_json()
    payload=client.get(r.get_json()['url']).data
    assert b'Predicted fixed-end string modes' in payload and b'not measured higher modes' in payload
    path=tmp_path/'string.mp4';path.write_bytes(payload);cap=cv2.VideoCapture(str(path))
    assert cap.get(cv2.CAP_PROP_FRAME_COUNT)==76 and cap.get(cv2.CAP_PROP_FPS)==30
    meta=export_metadata(video,'tap',85,10,0,tap=simulate(model,options))
    for expected in export_frames(video,meta,tap_maps=maps):
        ok,frame=cap.read();assert ok
        assert np.abs(cv2.cvtColor(frame,cv2.COLOR_BGR2RGB).astype(float)-expected).mean()<3
    cap.release()
    assert client.post('/api/tap',json=dict(body,key='old')).status_code==400
    assert client.post('/api/tap',json=dict(body,revision='old')).status_code==400


def test_optional_guitar_demo_has_explicit_600fps_preset(string_model,tmp_path,monkeypatch):
    video,_,_,_,_=string_model
    monkeypatch.setattr(server,'ROOT',tmp_path)
    client=server.app.test_client()
    assert client.post('/api/demo',json=dict(kind='guitar')).status_code==400
    folder=tmp_path/'data/examples';folder.mkdir(parents=True);(folder/'guitar.mp4').write_bytes(b'test')
    monkeypatch.setattr(server,'decode_video',lambda path:video)
    response=client.post('/api/demo',json=dict(kind='guitar'))
    assert response.status_code==200,response.get_json()
    data=response.get_json()
    assert data['metadata']['fps']==600 and data['metadata']['encoded_fps']==30
    assert data['ui']['timing_confirmed'] and data['ui']['tap']['model_source']=='string'
    assert data['ui']['tap']['string']['span_end']==.5
    assert data['settings']['frequency']==80 and data['settings']['low']==72 and data['settings']['high']==92
