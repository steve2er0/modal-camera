from dataclasses import replace

import numpy as np
import pytest

import app as server
from modal_camera.processing import Video, analyze_tracks
from modal_camera.spectrum import displacement_spectrum


def trace(values, point=1):
    return dict(point=point, x=90., y=94., dx=[0.]*len(values), dy=list(values),
                valid=[v is not None for v in values], quality={}, valid_fraction=1., warnings=[])


@pytest.fixture
def analytic():
    n, fps = 600, 60.
    video = Video(np.zeros((n,32,32,3),np.uint8),fps,32,32,'analytic',[])
    t = np.arange(n)/fps
    values = 2.3+.02*t+.4*np.cos(2*np.pi*3*t)+.12*np.cos(2*np.pi*7*t)
    return video, values


def test_original_psd_resolves_tones_and_integrates_power(analytic):
    video, values = analytic
    result = displacement_spectrum(video,[trace(values)])
    assert [p['frequency_hz'] for p in result['psd_peaks'][:2]] == pytest.approx([3,7])
    assert np.sum(result['psd_px2_per_hz'])*result['resolution_hz'] == pytest.approx((.4**2+.12**2)/2,abs=2e-5)
    old = analyze_tracks(video,[trace(values)],frequency=3)
    np.testing.assert_allclose(result['psd_px2_per_hz'],old['psd_px2_per_hz'])
    np.testing.assert_allclose(result['spectrum_px'],old['spectrum_px'])


def test_spatial_power_mean_does_not_cancel_opposite_phase(analytic):
    video, values = analytic
    result = displacement_spectrum(video,[trace(values),trace(-values,2)],spatial=True)
    single = displacement_spectrum(video,[trace(values)])
    np.testing.assert_allclose(result['psd_px2_per_hz'],single['psd_px2_per_hz'])
    assert result['psd_metadata']['accepted_trace_count']==2
    assert len(result['points'])==1 and result['points'][0]['label']=='Spatial mean'


def test_gaps_are_withheld_and_camera_reference_is_excluded(analytic):
    video, values = analytic
    broken = list(values);broken[40]=None
    result = displacement_spectrum(video,[trace(values),trace(broken,2)])
    assert result['psd_metadata']['accepted_trace_count']==1
    assert result['points'][1]['psd_px2_per_hz'] is None
    missing = displacement_spectrum(video,[trace(broken)],spatial=True)
    assert not missing['spectrum_available'] and missing['psd_peak_frequency_hz'] is None
    cancelled = displacement_spectrum(video,[trace(values),trace(values,2)],reference_last=True)
    assert max(cancelled['psd_px2_per_hz'])==0
    assert cancelled['psd_peaks']==[] and cancelled['psd_peak_frequency_hz'] is None
    assert cancelled['psd_metadata']['total_trace_count']==1


def test_timebase_changes_hz_and_density_but_preserves_integrated_power(analytic):
    video, values = analytic
    original = displacement_spectrum(video,[trace(values)])
    faster = displacement_spectrum(replace(video,fps=240),[trace(values)])
    assert faster['psd_peak_frequency_hz']==pytest.approx(12)
    np.testing.assert_allclose(np.array(faster['psd_px2_per_hz'])*4,original['psd_px2_per_hz'])
    assert faster['points'][0]['rms_from_psd_px']==pytest.approx(original['points'][0]['rms_from_psd_px'])


def test_highpass_suppresses_slow_jitter_and_preserves_95hz_without_mutating_tracks(analytic):
    video, _ = analytic
    video=replace(video,fps=240)
    t=np.arange(len(video.frames))/video.fps
    values=2*np.cos(2*np.pi*1.2*t)+.4*np.cos(2*np.pi*95.2*t)
    tracks=[trace(values)]
    raw=displacement_spectrum(video,tracks)
    filtered=displacement_spectrum(video,tracks,highpass_hz=5)
    f=np.array(raw['frequencies'])
    original=np.array(raw['psd_px2_per_hz']);hp=np.array(filtered['psd_px2_per_hz'])
    slow=(f>=.4)&(f<=3);response=(f>=93)&(f<=97)
    assert hp[slow].sum()/original[slow].sum()<1e-4
    assert hp[response].sum()/original[response].sum()==pytest.approx(1,abs=.001)
    assert filtered['psd_peak_frequency_hz']==pytest.approx(95.2)
    assert tracks[0]['dy']==list(values)
    assert filtered['highpass']['order_per_pass']==4
    assert filtered['highpass']['cutoff_hz']==5
    assert filtered['highpass']['cutoff_two_pass_gain_db']==pytest.approx(-6.0206,abs=1e-4)
    restored=displacement_spectrum(video,tracks,highpass_hz=0)
    assert restored['psd_px2_per_hz']==raw['psd_px2_per_hz']
    broken=list(values);broken[50]=None
    withheld=displacement_spectrum(video,[trace(broken)],highpass_hz=5)
    assert not withheld['spectrum_available']
    assert withheld['points'][0]['psd_px2_per_hz'] is None


def test_forward_backward_cutoff_attenuation_is_disclosed_correctly(analytic):
    video, _ = analytic
    video=replace(video,fps=240)
    t=np.arange(len(video.frames))/video.fps
    tracks=[trace(.4*np.cos(2*np.pi*4.8*t))]
    raw=displacement_spectrum(video,tracks)
    filtered=displacement_spectrum(video,tracks,highpass_hz=4.8)
    i=np.argmax(raw['psd_px2_per_hz'])
    assert filtered['psd_px2_per_hz'][i]/raw['psd_px2_per_hz'][i]==pytest.approx(.25,abs=.01)


@pytest.fixture
def session(clean):
    server.app.config.update(TESTING=True)
    with server.app.app_context():
        data=server.install_clip(clean,demo=True).get_json()
    return server.app.test_client(),data


def update(client, data, **changes):
    response=client.post('/api/settings',json=dict(id=data['id'],revision=data['revision'],
        settings=dict(data['settings'],**changes),invalidate=True))
    assert response.status_code==200,response.get_json()
    return client.get('/api/session').get_json() | {'id':data['id']}


def test_target_and_gain_edits_preserve_spectrum_and_export_without_fits(session):
    client,data=session
    first=client.post('/api/spectrum',json=dict(id=data['id'],revision=data['revision'])).get_json()
    assert first['psd_peak_frequency_hz']==pytest.approx(3,abs=.17)
    old_revision=data['revision']
    data=update(client,data,frequency=7,gain=9,bandwidth=2)
    second=client.post('/api/spectrum',json=dict(id=data['id'],revision=data['revision'])).get_json()
    assert second['key']==first['key'] and second['psd_px2_per_hz']==first['psd_px2_per_hz']
    assert client.post('/api/spectrum',json=dict(id=data['id'],revision=old_revision)).status_code==400
    payload=client.get(f"/api/export/{data['id']}").get_json()
    assert payload['measurement'] is None and payload['spatial_response'] is None
    assert payload['displacement_spectrum']['psd_px2_per_hz']==first['psd_px2_per_hz']


@pytest.mark.parametrize('change',[dict(axis='x'),dict(points=[[90,94]]),dict(roi=[40,38,100,112]),dict(reference_last=True)])
def test_sampling_changes_invalidate_spectrum(session,change):
    client,data=session
    assert client.post('/api/spectrum',json=dict(id=data['id'],revision=data['revision'])).status_code==200
    data=update(client,data,**change)
    assert data['spectrum'] is None and data['spectrum_key'] is None


def test_automatic_grid_spectrum_needs_no_target_fit_and_reuses_spatial_tracks(session,monkeypatch):
    client,data=session
    data=update(client,data,points=[],frequency=95)
    result=client.post('/api/spectrum',json=dict(id=data['id'],revision=data['revision']))
    assert result.status_code==200,result.get_json()
    assert result.get_json()['source']=='spatial_grid'
    assert result.get_json()['psd_metadata']['accepted_trace_count']>0
    # Target 95 is outside this demo's Nyquist. Spectrum selection still works.
    assert result.get_json()['psd_peak_frequency_hz']==pytest.approx(3,abs=.17)
    cached=server.state['field_cache']
    import modal_camera.response as response
    monkeypatch.setattr(response,'track_locations',lambda *args:pytest.fail('Grid tracks should be reused'))
    data=update(client,data,frequency=3)
    field=client.post('/api/field',json=dict(id=data['id'],revision=data['revision'],frequency=3,axis='y',points=[],roi=None,reference='auto',reference_last=False))
    assert field.status_code==200,field.get_json()
    assert server.state['field_cache']['traces'] is cached['traces']
    changed=client.post('/api/timebase',json=dict(id=data['id'],revision=data['revision'],capture_fps=240,one_frame_per_sample=True))
    assert changed.status_code==200
    assert client.get('/api/session').get_json()['spectrum'] is None
    timed=client.post('/api/spectrum',json=dict(id=data['id'],revision=changed.get_json()['revision'])).get_json()
    assert timed['psd_peak_frequency_hz']==pytest.approx(12,abs=.67)
    assert server.state['field_cache']['traces'] is cached['traces']


def test_filter_changes_only_psd_and_recovers_in_export_and_session(session):
    client,data=session
    s=data['settings'];common=dict(id=data['id'],revision=data['revision'])
    for route,keys in [('render',('low','high','gain','roi')),('field',('frequency','axis','points','roi','reference','reference_last'))]:
        result=client.post('/api/'+route,json=dict(common,**{k:s[k] for k in keys}))
        assert result.status_code==200,result.get_json()
    raw=client.post('/api/spectrum',json=common).get_json()
    before=client.get('/api/session').get_json()
    result=client.post('/api/settings',json=dict(common,settings=dict(s,spectrum_highpass_hz=5)))
    assert result.status_code==200,result.get_json()
    snapshot=client.get('/api/session').get_json()
    assert snapshot['spectrum'] is None
    assert snapshot['field_key']==before['field_key'] and snapshot['field']==before['field']
    assert snapshot['render_key']==before['render_key'] and snapshot['render_info']==before['render_info']
    filtered=client.post('/api/spectrum',json=dict(common,revision=snapshot['revision'])).get_json()
    assert filtered['key']!=raw['key']
    assert filtered['highpass']['enabled'] and filtered['highpass']['cutoff_hz']==5
    export=client.get(f"/api/export/{data['id']}").get_json()
    assert export['displacement_spectrum']['highpass']['cutoff_hz']==5
    assert export['spatial_response']==before['field']
    assert client.get('/api/session').get_json()['spectrum']=={k:v for k,v in filtered.items() if k not in ('key','revision')}
    # If a new timebase makes the cutoff impossible, disable it and disclose the reset.
    result=client.post('/api/timebase',json=dict(common,revision=snapshot['revision'],capture_fps=8,one_frame_per_sample=True))
    assert result.status_code==200
    assert result.get_json()['spectrum_highpass_hz']==0
    assert client.get('/api/session').get_json()['settings']['spectrum_highpass_hz']==0


@pytest.mark.parametrize('cutoff',[-1,'nan',float('inf'),.01,30])
def test_invalid_highpass_cannot_change_saved_state(session,cutoff):
    client,data=session
    before=client.get('/api/session').get_json()
    response=client.post('/api/settings',json=dict(id=data['id'],revision=data['revision'],
        settings=dict(data['settings'],spectrum_highpass_hz=cutoff)))
    assert response.status_code==400
    assert 'cutoff' in response.get_json()['error']
    assert client.get('/api/session').get_json()==before
