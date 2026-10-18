from copy import deepcopy
import json

import pytest
import app as server


@pytest.fixture
def workflow(clean):
    server.app.config.update(TESTING=True)
    with server.app.app_context():
        installed=server.install_clip(clean,demo=True).get_json()
    return server.app.test_client(),installed


def saved(client,session,**changes):
    settings=dict(session['settings'],**changes)
    response=client.post('/api/settings',json=dict(id=session['id'],revision=session['revision'],settings=settings))
    assert response.status_code==200,response.get_json()
    return dict(session,settings=settings,revision=response.get_json()['revision'])


def results(client,session):
    common=dict(id=session['id'],revision=session['revision'])
    s=session['settings']
    for route,params in [('/api/render',{k:s[k] for k in ('low','high','gain','roi')}),
                         ('/api/analyze',{k:s[k] for k in ('frequency','axis','points','reference_last')}),
                         ('/api/field',{k:s[k] for k in ('frequency','axis','points','roi','reference','reference_last')})]:
        response=client.post(route,json=dict(common,**params))
        assert response.status_code==200,response.get_json()


def test_clip_calibration_is_owned_by_clip_and_resets_on_replacement(workflow,clean):
    client,session=workflow
    session=saved(client,session,calibration=2)
    assert client.get('/api/session').get_json()['settings']['calibration']==2
    with server.app.app_context():
        replacement=server.install_clip(clean).get_json()
    assert replacement['settings']['calibration'] is None
    assert replacement['settings']['points']==[]
    assert replacement['settings']['frequency']==95
    assert replacement['settings']['bandwidth']==4
    assert replacement['ui']['timing_confirmed'] is False


def test_changed_target_invalidates_point_field_and_linked_band_exports(workflow):
    client,session=workflow
    results(client,session)
    old_revision=session['revision']
    session=saved(client,session,frequency=7)
    snapshot=client.get('/api/session').get_json()
    assert snapshot['settings']['low']==6.5 and snapshot['settings']['high']==7.5
    assert snapshot['analysis'] is None and snapshot['field'] is None and snapshot['render_key'] is None
    for path in ('api/export','api/field-csv','api/csv'):
        assert client.get(f"/{path}/{session['id']}").status_code==400
    response=client.post('/api/export-data',json=dict(id=session['id'],revision=old_revision,kind='analysis'))
    assert response.status_code==400


def test_legacy_point_analysis_discards_incompatible_spatial_map(workflow):
    client,session=workflow
    results(client,session)
    changed=client.post('/api/analyze',json=dict(id=session['id'],frequency=7,axis='y',points=session['settings']['points']))
    assert changed.status_code==200
    export=client.get(f"/api/export/{session['id']}").get_json()
    assert export['measurement']['frequency_hz']==7
    assert export['spatial_response'] is None
    assert client.get(f"/api/field-csv/{session['id']}").status_code==400


def test_stale_tabs_cannot_process_or_overwrite_current_settings(workflow):
    client,session=workflow
    current=saved(client,session,axis='x')
    assert current['revision']!=session['revision']
    for route,data in [('/api/settings',dict(settings=session['settings'])),
                       ('/api/analyze',dict(points=session['settings']['points'],frequency=3)),
                       ('/api/timebase',dict(capture_fps=240,one_frame_per_sample=True)),
                       ('/api/export-video',dict(view='heatmap',key='old'))]:
        response=client.post(route,json=dict(id=session['id'],revision=session['revision'],**data))
        assert response.status_code==400
        assert 'changed' in response.get_json()['error']
    assert client.get('/api/session').get_json()['settings']['axis']=='x'


def test_refresh_snapshot_recovers_results_calibration_and_display(workflow):
    client,session=workflow
    session=saved(client,session,calibration=.125)
    results(client,session)
    ui=dict(view='phase',sensitivity=76,modal_gain=8,phase=90,frame=100,timing_mode='encoded',timing_confirmed=True)
    response=client.post('/api/settings',json=dict(id=session['id'],revision=session['revision'],ui=ui))
    assert response.status_code==200
    snapshot=client.get('/api/session').get_json()
    assert snapshot['clip']['id']==session['id']
    assert snapshot['ui']==ui
    assert snapshot['settings']['calibration']==.125
    assert snapshot['analysis']['frequency_hz']==snapshot['field']['frequency_hz']==3
    assert all(snapshot[k] for k in ('analysis_key','field_key','render_key'))
    assert client.get(f"/api/frame/{session['id']}/100?view=amplified&key={snapshot['render_key']}").status_code==200


def test_data_export_preparation_errors_stay_json_and_snapshot_survives_later_edits(workflow):
    client,session=workflow
    missing=client.post('/api/export-data',json=dict(id=session['id'],revision=session['revision'],kind='samples'))
    assert missing.status_code==400 and missing.is_json
    results(client,session)
    prepared=client.post('/api/export-data',json=dict(id=session['id'],revision=session['revision'],kind='analysis'))
    assert prepared.status_code==200
    link=prepared.get_json()
    session=saved(client,session,frequency=7)
    download=client.get(link['url'])
    assert download.status_code==200
    assert 'attachment' in download.headers['Content-Disposition']
    payload=json.loads(download.data)
    assert payload['measurement']['frequency_hz']==payload['spatial_response']['frequency_hz']==3
    assert client.post('/api/export-data',json=dict(id=session['id'],revision=session['revision'],kind='samples')).status_code==400


def test_completed_data_links_expire_on_new_clip(workflow,clean):
    client,session=workflow
    results(client,session)
    link=client.post('/api/export-data',json=dict(id=session['id'],revision=session['revision'],kind='samples')).get_json()['url']
    with server.app.app_context():server.install_clip(clean)
    assert client.get(link).status_code==400


def test_stopping_analysis_clears_partial_outputs_and_rejects_inflight_revision(workflow):
    client,session=workflow
    s=session['settings']
    render=client.post('/api/render',json=dict(id=session['id'],revision=session['revision'],**{k:s[k] for k in ('low','high','gain','roi')}))
    assert render.status_code==200
    stopped=client.post('/api/settings',json=dict(id=session['id'],revision=session['revision'],invalidate=True))
    assert stopped.status_code==200
    assert client.get('/api/session').get_json()['render_key'] is None
    stale=client.post('/api/field',json=dict(id=session['id'],revision=session['revision'],frequency=3,points=s['points']))
    assert stale.status_code==400


def test_legacy_default_axis_and_reference_match_actual_result_and_discard_old_field(workflow):
    client,session=workflow
    session=saved(client,session,axis='x',reference_last=True)
    results(client,session)
    response=client.post('/api/analyze',json=dict(id=session['id'],frequency=3,points=session['settings']['points']))
    assert response.status_code==200
    snapshot=client.get('/api/session').get_json()
    assert snapshot['settings']['axis']=='y'
    assert snapshot['settings']['reference_last'] is False
    assert snapshot['analysis']['axis']=='y'
    assert snapshot['field'] is None


def test_prepared_json_preserves_saved_display_and_calibration(workflow):
    client,session=workflow
    session=saved(client,session,calibration=.25)
    results(client,session)
    response=client.post('/api/settings',json=dict(id=session['id'],revision=session['revision'],ui=dict(
        view='modal',sensitivity=76,modal_gain=8,timing_mode='encoded',timing_confirmed=True)))
    assert response.status_code==200
    prepared=client.post('/api/export-data',json=dict(id=session['id'],revision=session['revision'],kind='analysis')).get_json()
    payload=json.loads(client.get(prepared['url']).data)
    assert payload['display']==dict(view='modal',sensitivity=76,modal_gain=8,calibration_mm_per_source_px=.25)


@pytest.mark.parametrize('route,params',[
    ('/api/render',dict(low=4,high=3,gain=4)),
    ('/api/field',dict(frequency=30)),
    ('/api/analyze',dict(frequency=30,points=[[90,94],[230,94]])),
])
def test_failed_processing_does_not_replace_or_invalidate_the_previous_valid_session(workflow,route,params):
    client,session=workflow
    results(client,session)
    before=client.get('/api/session').get_json()
    response=client.post(route,json=dict(id=session['id'],**params))
    assert response.status_code==400
    assert client.get('/api/session').get_json()==before


@pytest.mark.parametrize('change',[dict(frequency='nan'),dict(gain=21),dict(calibration=-1),dict(points=[[1,1]]),dict(roi=[0,0,900,900])])
def test_invalid_settings_do_not_change_saved_revision_or_calibration(workflow,change):
    client,session=workflow
    before=deepcopy(client.get('/api/session').get_json())
    response=client.post('/api/settings',json=dict(id=session['id'],revision=session['revision'],settings=dict(session['settings'],**change)))
    assert response.status_code==400
    assert client.get('/api/session').get_json()==before
