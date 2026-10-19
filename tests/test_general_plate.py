"""Physical-planform Hessians, cantilever truth and camera-independent mapping."""
from copy import deepcopy
import json
import math

import cv2
import numpy as np
from numpy.polynomial.legendre import leggauss
import pytest

import app as server
from modal_camera.plate_modes import (validate_plate_settings,solve_plate,evaluate,planform_xy,
                                      planform_uv,planform_basis,build_plate_model)
from modal_camera.processing import Video
from modal_camera.virtual_tap import configure,simulate,tap_frame
from modal_camera.video_export import export_metadata,export_frames


def test_cantilever_matches_exact_poisson_zero_beam_family_and_fixed_root():
    # For nu=0, a v-independent solution exactly satisfies the free side edges.
    # cosh(beta)cos(beta)=-1 gives three independent beam-family benchmarks.
    cfg=validate_plate_settings(dict(mounting='cantilever',aspect_ratio=5,poisson=0))
    s=solve_plate(cfg,order=15)
    beta=np.array([1.875104068711961,4.694091132974175,7.854757438237613])
    actual=np.sqrt(s['eigenvalues'])
    for expected in beta**2/25:
        assert min(abs(actual-expected))<expected*2e-6
    root=evaluate(s,np.column_stack([np.zeros(11),np.linspace(0,1,11)]))
    np.testing.assert_allclose(root,0,atol=1e-14)
    # w and its root-normal derivative tend to zero; free tip remains mobile.
    eps=1e-7
    near=evaluate(s,[[eps,.25],[eps,.75]])/eps/5
    np.testing.assert_allclose(near,0,atol=2e-5)
    assert abs(evaluate(s,[[1,.5]])[0,0])>.9
    assert s['rigid_modes_removed']==0


def test_physical_hessian_matches_independent_cartesian_finite_differences():
    cfg=validate_plate_settings(dict(aspect_ratio=3,taper_ratio=.45,sweep_offset=.7,mounting='cantilever'))
    uv=np.array([[.37,.43]])
    xy=planform_xy(cfg,uv)[0]
    b,bxx,byy,bxy=planform_basis(cfg,uv,4)
    # Basis index (2,2): u² P2(2u-1)P2(2v-1), inverted independently in x,y.
    def f(x,y):
        u=x/3;v=(y-.7*u)/(1-.55*u)
        return u*u*(6*u*u-6*u+1)*(6*v*v-6*v+1)
    x,y=xy;h=1e-4
    expected=[(f(x+h,y)-2*f(x,y)+f(x-h,y))/h**2,
              (f(x,y+h)-2*f(x,y)+f(x,y-h))/h**2,
              (f(x+h,y+h)-f(x+h,y-h)-f(x-h,y+h)+f(x-h,y-h))/(4*h*h)]
    np.testing.assert_allclose([bxx[0,10],byy[0,10],bxy[0,10]],expected,rtol=1e-6,atol=1e-6)
    assert b[0,10]==pytest.approx(f(x,y))
    np.testing.assert_allclose(planform_uv(cfg,planform_xy(cfg,uv)),uv,atol=1e-14)


def test_tapered_mass_uses_physical_area_and_planform_reflection_is_invariant():
    cfg=validate_plate_settings(dict(aspect_ratio=3,taper_ratio=.5,sweep_offset=.5,mounting='cantilever'))
    s=solve_plate(cfg,order=15)
    g,w=leggauss(24);u,v=np.meshgrid((g+1)/2,(g+1)/2)
    uv=np.column_stack([u.ravel(),v.ravel()]);phi=evaluate(s,uv)
    # Average over the physical area, not a uniform average over reference uv.
    weights=np.outer(w,w).ravel()/4*(1-.5*uv[:,0])/.75
    mass=phi.T@(weights[:,None]*phi)
    np.testing.assert_allclose(mass,np.diag(s['modal_mass']),atol=2e-9)
    reflected=solve_plate(dict(cfg,sweep_offset=1-cfg['sweep_offset']-cfg['taper_ratio']),order=15)
    # A changed polynomial coordinate basis has slightly different conditioning.
    np.testing.assert_allclose(s['eigenvalues'],reflected['eigenvalues'],rtol=1e-6)
    coarse=solve_plate(cfg,order=13)
    ratios=np.sqrt(s['eigenvalues']/s['eigenvalues'][0]);low=np.sqrt(coarse['eigenvalues']/coarse['eigenvalues'][0])
    assert max(abs(low/ratios-1))<.001
    rect=solve_plate(dict(cfg,taper_ratio=1,sweep_offset=0),order=15)
    assert not np.allclose(ratios,np.sqrt(rect['eigenvalues']/rect['eigenvalues'][0]),rtol=.01)


@pytest.fixture
def wing():
    rng=np.random.default_rng(25)
    image=np.repeat(rng.integers(30,220,(160,240,1),dtype=np.uint8),3,axis=2)
    video=Video(np.repeat(image[None],120,axis=0),240,240,160,'synthetic-wing.avi',[],encoded_fps=30)
    cfg=validate_plate_settings(dict(aspect_ratio=3,taper_ratio=.5,sweep_offset=.5,mounting='cantilever'))
    camera=np.array([[45,9,30],[3,60,20],[.05,.02,1]],float)
    def image_xy(uv):
        xy=planform_xy(cfg,uv)
        z=np.column_stack([xy,np.ones(len(xy))])@camera.T
        return z[:,:2]/z[:,2,None]
    cfg['corners']=image_xy([[0,0],[1,0],[1,1],[0,1]]).tolist()
    solution=solve_plate(cfg,order=15)
    u,v=np.meshgrid(np.linspace(.08,.92,7),np.linspace(.05,.95,5))
    uv=np.column_stack([u.ravel(),v.ravel()]);uv=np.vstack([uv,[0,.5]])
    xy=image_xy(uv);truth=evaluate(solution,uv)[:,0]
    nodes=[]
    for i,(point,value) in enumerate(zip(xy,truth)):
        z=.2*value*np.exp(.4j)
        fit=dict(coefficients_px=[z.real,-z.imag],phase_deg=float(np.angle(z,deg=True)),amplitude_peak_px=float(abs(z)))
        nodes.append(dict(index=i,x=float(point[0]),y=float(point[1]),fit=dict(x=deepcopy(fit),y=deepcopy(fit))))
    nodes.append(dict(index=len(nodes),x=220.,y=140.,fit=deepcopy(nodes[0]['fit'])))
    field=dict(axis='y',frequency_hz=17.,nodes=nodes,grid=dict(x0=30,y0=20,step=15,columns=7,rows=6))
    model,maps=build_plate_model(video,field,cfg)
    return video,field,cfg,model,maps


def test_perspective_maps_physical_wing_instead_of_warping_a_rectangle(wing):
    video,field,cfg,model,maps=wing
    assert model['anchor_mode']==0 and model['fit_mac']==pytest.approx(1,abs=1e-10)
    assert model['basis_order']==15 and model['max_basis_change_percent']<.1
    assert model['modes'][0]['frequency_hz']==17
    assert model['nodes'][-1]['shape'] is None
    np.testing.assert_allclose(model['nodes'][-2]['modes'],0,atol=1e-12)
    assert '17.000 Hz' in model['interpretation'] and '95 Hz' not in model['interpretation']
    assert any('spars' in text and 'aeroelastic' in text for text in model['assumptions'])
    options=dict(model_source='plate',plate=cfg,enabled_modes=[0,1,2],cycles=5)
    config=configure(model,options)
    moved=tap_frame(video,model,maps,config,.25/17,10)
    assert np.any(moved[maps['support']]!=video.frames[0][maps['support']])
    np.testing.assert_array_equal(moved[~maps['support']],video.frames[0][~maps['support']])


@pytest.mark.parametrize('bad',[dict(taper_ratio=0),dict(taper_ratio=2.1),dict(sweep_offset=float('inf')),dict(sweep_offset=3),dict(aspect_ratio=13)])
def test_general_planform_bounds(bad):
    with pytest.raises(ValueError):validate_plate_settings(bad)


def test_wing_api_session_cache_and_full_mp4_export(wing,tmp_path):
    video,field,cfg,model,maps=wing
    with server.app.app_context():s=server.install_clip(video).get_json()
    server.state.update(field=field,field_key='wing-field')
    client=server.app.test_client()
    options=dict(model_source='plate',plate=cfg,motion='mode',solo_mode=1,cycles=5)
    body=dict(id=s['id'],revision=s['revision'],key='wing-field',tap=options)
    r=client.post('/api/tap',json=body);assert r.status_code==200,r.get_json()
    p=r.get_json();key=p['model']['key']
    assert client.post('/api/settings',json=dict(body,ui=dict(s['ui'],view='tap',tap=p['settings']))).status_code==200
    assert client.get('/api/session').get_json()['ui']['tap']['plate']==cfg
    changed=client.post('/api/tap',json=dict(body,tap=dict(options,plate=dict(cfg,sweep_offset=.6))))
    assert changed.status_code==200 and changed.get_json()['model']['key']!=key
    for kind in ['tap-model','tap-traces']:
        e=client.post('/api/export-data',json=dict(body,kind=kind));assert e.status_code==200
        content=client.get(e.get_json()['url']).data
        assert b'taper_ratio' in content and b'cantilever' in content
    e=client.post('/api/export-video?prepare=1',json=dict(body,view='tap',modal_gain=10));assert e.status_code==200,e.get_json()
    payload=client.get(e.get_json()['url']).data
    assert b'sweep_offset' in payload and b'cantilever' in payload
    path=tmp_path/'wing.mp4';path.write_bytes(payload)
    cap=cv2.VideoCapture(str(path));assert cap.isOpened() and cap.get(cv2.CAP_PROP_FPS)==30
    meta=export_metadata(video,'tap',85,10,0,tap=simulate(model,options))
    count=0
    for expected in export_frames(video,meta,tap_maps=maps):
        ok,frame=cap.read();assert ok
        error=np.abs(cv2.cvtColor(frame,cv2.COLOR_BGR2RGB).astype(float)-expected).mean()
        assert error<4
        count+=1
    assert count==meta['export_frames'] and not cap.read()[0]
    cap.release()
