"""A preset changes assumptions and invalidates results, never the recording."""
from dataclasses import replace

import numpy as np
import pytest

import app as server
from modal_camera.presets import plate_demo_settings
from modal_camera.processing import Video


def recording(width=301,height=169,count=120):
    image=np.zeros((1,height,width,3),dtype=np.uint8)
    return Video(np.broadcast_to(image,(count,height,width,3)),30.,1280,720,
                 'my-loaded-recording.avi',['Keep this input warning.'],encoded_fps=30.)


@pytest.fixture
def loaded():
    video=recording()
    with server.app.app_context():installed=server.install_clip(video).get_json()
    return server.app.test_client(),installed,video


def apply(client,installed,**overrides):
    return client.post('/api/preset',json=dict(kind='plate',id=installed['id'],
                                             revision=installed['revision'],**overrides))


def test_plate_preset_keeps_recording_and_restores_complete_experiment(loaded,monkeypatch):
    client,installed,video=loaded
    def forbidden(*args,**kwargs):
        pytest.fail('Applying settings must never decode or load a recording.')
    monkeypatch.setattr(server,'decode_video',forbidden)
    # Mimic a different model, calibrated measurements, and stale computed views.
    server.state['settings'].update(axis='x',calibration=.1,points=[[30,30]],reference_last=True)
    server.state['ui']['tap']=dict(model_source='string')
    cleared=('spectrum','spectrum_key','analysis','analysis_key','field','field_key',
             'field_maps','tap_model','tap_maps','tap_field_key','render','render_key',
             'render_info','response_display')
    for key in cleared:server.state[key]='stale'
    response=apply(client,installed)
    assert response.status_code==200,response.get_json()
    data=response.get_json();assumed=server.state['video']
    assert data['clip']['id']==installed['id']
    assert data['revision']!=installed['revision']
    assert assumed.frames is video.frames
    assert (assumed.name,assumed.source_width,assumed.source_height,assumed.encoded_fps)==(video.name,1280,720,30.)
    assert video.fps==30. and assumed.fps==240.
    assert assumed.warnings[0]=='Keep this input warning.'
    assert 'unverified' in assumed.warnings[-1]
    assert all(server.state[key] is None for key in cleared)
    s=data['settings'];ui=data['ui'];tap=ui['tap'];plate=tap['plate']
    assert [s[k] for k in ('frequency','low','high','gain','axis','linked')]==[94.872,91.883,97.092,4.,'y',False]
    assert s['spectrum_highpass_hz']==10. and s['spectrum_source']=='point'
    assert s['spectrum_point']==[112.,64.] and s['spectrum_region']==[35.,50.,235.,55.]
    assert s['points']==[] and s['calibration'] is None and s['roi'] is None and not s['reference_last']
    assert ui['view']=='tap' and ui['timing_mode']=='capture' and ui['timing_confirmed']
    assert ui['modal_gain']==8 and ui['sensitivity']==76 and ui['frame']==0
    assert tap['model_source']=='plate' and tap['motion']=='tap' and tap['enabled_modes']==[0,1,2,3]
    assert tap['damping_percent']==1 and tap['strength']==1 and tap['cycles']==40 and tap['display_cps']==2
    assert plate['corners']==[[45.,55.],[236.,52.],[269.,96.],[20.,99.]]
    assert plate['aspect_ratio']==2 and plate['mounting']=='free' and plate['poisson']==.33
    assert plate['taper_ratio']==1 and plate['sweep_offset']==0 and plate['projection_angle_deg']==90
    recovered=client.get('/api/session').get_json()
    assert recovered['ui']==ui and recovered['settings']==s
    # Existing stale frame/field URLs cannot serve previous computed results.
    assert client.get(f"/api/frame/{installed['id']}/0?view=original").status_code==200
    assert client.get(f"/api/frame/{installed['id']}/0?view=amplified&key=stale").status_code==400


def test_plate_preset_scales_image_locations_and_preserves_source_units():
    video=recording(width=602,height=338)
    assumed,s,ui=plate_demo_settings(video)
    assert assumed.frames is video.frames and assumed.source_width==1280
    assert s['spectrum_point']==[224.,128.] and s['spectrum_region']==[70.,100.,470.,110.]
    assert ui['tap']['plate']['corners']==[[90.,110.],[472.,104.],[538.,192.],[40.,198.]]


def test_reapplying_invalidates_results_even_when_only_analysis_time_changed(loaded):
    client,installed,video=loaded
    first=apply(client,installed).get_json()
    # A timebase change can leave the numerical settings identical to the preset.
    server.state['video']=replace(server.state['video'],fps=120.)
    server.state.update(spectrum={'old':True},spectrum_key='old',field={'old':True},field_key='old')
    second=apply(client,dict(id=first['clip']['id'],revision=first['revision']))
    assert second.status_code==200,second.get_json()
    data=second.get_json()
    assert data['revision']!=first['revision'] and data['spectrum'] is None and data['field'] is None
    assert server.state['video'].frames is video.frames
    assert sum('plate preset' in warning for warning in server.state['video'].warnings)==1


@pytest.mark.parametrize('changes',[dict(kind='unknown'),dict(id='old-clip'),dict(revision='old-revision')])
def test_invalid_or_stale_preset_does_not_mutate_active_session(loaded,changes):
    client,installed,_=loaded
    before=dict(server.state)
    payload=dict(kind='plate',id=installed['id'],revision=installed['revision']);payload.update(changes)
    response=client.post('/api/preset',json=payload)
    assert response.status_code==400
    assert server.state.keys()==before.keys()
    assert all(server.state[key] is value for key,value in before.items())


@pytest.mark.parametrize('video',[recording(count=32),recording(width=80,height=48)])
def test_incompatible_recording_rejects_preset_atomically(video):
    with server.app.app_context():installed=server.install_clip(video).get_json()
    before=dict(server.state)
    response=apply(server.app.test_client(),installed)
    assert response.status_code==400,response.get_json()
    assert all(server.state[key] is value for key,value in before.items())


def test_plate_preset_requires_loaded_video():
    server.state.clear()
    response=server.app.test_client().post('/api/preset',json=dict(kind='plate'))
    assert response.status_code==400
    assert 'Open your plate recording' in response.get_json()['error']
    assert not server.state
