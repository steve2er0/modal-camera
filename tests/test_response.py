from dataclasses import replace
import json

import cv2
import numpy as np
import pytest

import app as server
from modal_camera.processing import magnify, Video
from modal_camera.response import harmonic_fit, measure_field, modal_frame, interpolate_field


@pytest.fixture(scope='module')
def field(clean):
    return measure_field(clean,3,points=[[90,94],[230,94]])


def closest(result,x,y):
    return min(result['nodes'],key=lambda p:(p['x']-x)**2+(p['y']-y)**2)


def test_response_uses_original_band_and_is_gain_independent(clean):
    zero,info0,response0=magnify(clean,2.5,3.5,0,return_response=True)
    amplified,info4,response4=magnify(clean,2.5,3.5,4,return_response=True)
    assert np.array_equal(zero,clean.frames)
    assert not np.array_equal(amplified,zero)
    np.testing.assert_array_equal(response0,response4)
    assert info0['response']==info4['response']
    _,_,seven=magnify(clean,6.5,7.5,0,return_response=True)
    assert response0[70:115,65:115].mean()>2*seven[70:115,65:115].mean()
    assert response0[160:185,145:175].mean()<.05
    _,_,limited=magnify(clean,2.5,3.5,0,[40,38,100,112],return_response=True)
    assert np.max(limited[:,140:])==0


def test_local_amplitudes_phase_and_missing_texture(field):
    result,_,_=field
    first,second,blank=[closest(result,x,88) for x in (88,232,160)]
    assert first['fit']['y']['amplitude_peak_px']==pytest.approx(.4,abs=.04)
    assert second['fit']['y']['amplitude_peak_px']==pytest.approx(.6,abs=.04)
    assert first['fit']['x']['amplitude_peak_px']==pytest.approx(.18,abs=.03)
    assert second['fit']['x']['amplitude_peak_px']==pytest.approx(.28,abs=.03)
    assert first['relative_phase_deg']==pytest.approx(0,abs=3)
    assert second['relative_phase_deg']==pytest.approx(60,abs=4)
    assert result['reference']['label']=='P1'
    assert blank['amplitude_peak_px'] is None and blank['relative_phase_deg'] is None
    assert 0<result['interpolated_support_fraction']<1


def test_frequency_axis_source_scaling_and_timebase(clean,field):
    _,cache,_=field
    seven,_,_=measure_field(clean,7,axis='x',cached=cache)
    assert closest(seven,88,88)['amplitude_peak_px']<.02
    scaled=replace(clean,source_width=640,source_height=400,fps=600,
                   encoded_fps=60,timing_basis='user-assumed capture time')
    result,_,_=measure_field(scaled,30,points=[[90,94]],cached=cache)
    assert closest(result,88,88)['amplitude_peak_px']==pytest.approx(.8,abs=.08)
    assert closest(result,232,88)['relative_phase_deg']==pytest.approx(60,abs=4)
    assert result['timing_basis']=='user-assumed capture time'


def test_dropout_withholds_spatial_fits(demos):
    from modal_camera.processing import decode_video
    video=decode_video(demos/'tracking_dropout.avi')
    result,_,maps=measure_field(video,3)
    assert closest(result,88,88)['amplitude_peak_px']==pytest.approx(.4,abs=.04)
    assert closest(result,232,88)['amplitude_peak_px'] is None
    assert not maps['support'][88,232]


def test_relative_phase_reference_and_translation_subtraction(clean,field):
    _,cache,_=field
    result,_,_=measure_field(clean,3,points=[[90,94],[230,94]],reference_last=True,cached=cache)
    # P1 minus P2: 0.4*cos(theta)-0.6*cos(theta+60°).
    expected=np.hypot(.4-.6*np.cos(np.pi/3),.6*np.sin(np.pi/3))
    assert closest(result,88,88)['amplitude_peak_px']==pytest.approx(expected,abs=.05)
    strongest,_,_=measure_field(clean,3,reference='strongest',cached=cache)
    ref=strongest['reference']['location']
    assert closest(strongest,ref['x'],ref['y'])['relative_phase_deg']==pytest.approx(0)
    with pytest.raises(ValueError,match='Select P1'):measure_field(clean,3,reference='p1',cached=cache)
    with pytest.raises(ValueError,match='stationary'):measure_field(clean,3,reference_last=True,cached=cache)


@pytest.mark.parametrize('phase',[0,60,90,180,-90])
def test_harmonic_phase_convention_with_gaps_and_drift(phase):
    t=np.arange(360)/60
    values=1+.1*t+.4*np.cos(2*np.pi*3*t+np.deg2rad(phase))
    values[80:95]=np.nan
    fit=harmonic_fit(values,60,3)
    assert fit['amplitude_peak_px']==pytest.approx(.4,abs=1e-12)
    assert abs((fit['phase_deg']-phase+180)%360-180)<1e-9
    assert fit['rms_residual_px']<1e-12
    assert fit['samples']<360 and fit['accepted_fit_fraction']>.8


def test_weak_or_insufficient_response_has_no_phase():
    fit=harmonic_fit(np.zeros(360),60,3)
    assert fit['amplitude_peak_px']==0 and fit['phase_deg'] is None
    values=np.ones(360);values[50:200]=np.nan
    assert harmonic_fit(values,60,3) is None
    assert harmonic_fit(np.zeros(32),60,3) is None


def test_modal_warp_sign_gain_and_no_interpolation_across_gaps():
    # Analytic 1 source-pixel X motion on a 2× source image: compare exact
    # half-analysis-pixel translations at opposite phases, including a hole.
    texture=np.tile(np.arange(96,dtype=np.uint8)[None,:,None]*2,(96,1,3))
    video=Video(np.repeat(texture[None],120,axis=0),60,192,192,'analytic warp',[])
    grid=dict(rows=3,columns=3,step=24,x0=16,y0=16)
    xfit=dict(phase_deg=0,coefficients_px=[1.,0.])
    yfit=dict(phase_deg=None,coefficients_px=[0.,0.])
    nodes=[dict(index=i,fit=dict(x=xfit,y=yfit)) for i in range(9)]
    result=dict(grid=grid,nodes=nodes,reference=dict(phase_deg=0))
    maps=interpolate_field(video,result)
    positive=modal_frame(video,result,maps,0,2)
    negative=modal_frame(video,result,maps,180,2)
    assert positive[30,30,0]==texture[30,29,0]
    assert negative[30,30,0]==texture[30,31,0]
    assert np.array_equal(modal_frame(video,result,maps,0,0),texture)
    result['nodes'][4]['fit']=dict(x=None,y=None)
    holes=interpolate_field(video,result)
    assert not holes['support'][30,30]
    assert not holes['support'][16,16]  # Even the cell corner requires all four neighbors.
    assert np.array_equal(modal_frame(video,result,holes,0,2)[30,30],texture[30,30])
    assert np.array_equal(positive[5,5],texture[5,5])
    with pytest.raises(ValueError):modal_frame(video,result,maps,0,21)


def test_spatial_api_exports_and_stale_keys(clean):
    server.app.config.update(TESTING=True)
    server.state.clear()
    with server.app.test_client() as client:
        with server.app.app_context():cid=server.install_clip(clean).get_json()['id']
        render=client.post('/api/render',json=dict(id=cid,low=2.5,high=3.5,gain=0)).get_json()
        assert client.get(f"/api/response/{cid}?key={render['key']}").mimetype=='image/png'
        assert client.get(f'/api/response/{cid}?key=stale').status_code==400
        field=client.post('/api/field',json=dict(id=cid,frequency=3,points=[[90,94]])).get_json()
        assert field['accepted_nodes']>0
        assert client.get(f"/api/frame/{cid}/0?view=modal&key={field['key']}&phase=90&gain=5").mimetype=='image/jpeg'
        assert client.get(f'/api/frame/{cid}/0?view=modal&key=stale').status_code==400
        exported=client.get(f'/api/export/{cid}?sensitivity=80&modal_gain=5').get_json()
        assert exported['measurement'] is None and exported['spatial_response']['frequency_hz']==3
        assert exported['display']['sensitivity']==80
        csv=client.get(f'/api/field-csv/{cid}').data.decode()
        assert 'relative_phase_deg' in csv and 'x_cos_source_px' in csv
        assert len(csv.splitlines())==len(field['nodes'])+1
        assert client.post('/api/field',json=dict(id=cid,frequency=30)).status_code==400
        assert client.post('/api/field',json=dict(id=cid,frequency=3,roi=[-1,0,50,50])).status_code==400
        assert client.post('/api/timebase',json=dict(id=cid,capture_fps=600,one_frame_per_sample=True)).status_code==200
        assert client.get(f"/api/response/{cid}?key={render['key']}").status_code==400
        assert client.get(f"/api/frame/{cid}/0?view=modal&key={field['key']}").status_code==400
        with server.app.app_context():server.install_clip(clean)
        assert client.get(f'/api/field-csv/{cid}').status_code==400
