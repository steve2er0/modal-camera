import pytest
import app as server
from modal_camera.response import sample_grid


@pytest.fixture
def session(clean):
    server.app.config.update(TESTING=True)
    with server.app.app_context():
        data=server.install_clip(clean,demo=True).get_json()
    return server.app.test_client(),data


def save(client,data,**changes):
    response=client.post('/api/settings',json=dict(id=data['id'],revision=data['revision'],settings=dict(data['settings'],**changes)))
    assert response.status_code==200,response.get_json()
    return dict(client.get('/api/session').get_json(),id=data['id'])


def spectrum(client,data):
    response=client.post('/api/spectrum',json=dict(id=data['id'],revision=data['revision']))
    assert response.status_code==200,response.get_json()
    return response.get_json()


@pytest.mark.parametrize('box',[[45,45,100,100],[45.8,45.2,100.6,100.3]])
def test_region_keeps_reference_windows_inside_selection(clean,box):
    coords,_=sample_grid(clean,box,contained=True)
    assert coords
    for x,y in coords:
        assert box[0]<=x-15 and x+15<=box[0]+box[2]
        assert box[1]<=y-15 and y+15<=box[1]+box[3]


def test_sampling_preview_becomes_quality_gated_and_point_reuses_grid_trace(session,monkeypatch):
    client,data=session
    data=save(client,data,spectrum_source='frame')
    preview=client.get(f"/api/sampling/{data['id']}?revision={data['revision']}").get_json()
    assert preview['mode']=='frame' and all(p['eligible'] is None for p in preview['samples'])
    grid=spectrum(client,data)
    assert grid['sampling']['accepted_count']==grid['psd_metadata']['accepted_trace_count']
    assert any(p['eligible'] is False for p in grid['sampling']['samples'])
    chosen=next(p for p in grid['sampling']['samples'] if p['x']==88 and p['y']==88)
    assert chosen['used']
    data=save(client,data,spectrum_source='point',spectrum_point=[88,88])
    monkeypatch.setattr(server,'track_points',lambda *a:pytest.fail('Previously tracked grid point must be reused'))
    point=spectrum(client,data)
    assert point['sampling']['mode']=='point' and point['psd_metadata']['total_trace_count']==1
    assert point['sampling']['accepted_count']==1
    assert point['psd_peak_frequency_hz']==pytest.approx(3,abs=.17)
    assert sum(p['selected'] for p in point['sampling']['samples'])==1
    assert point['sampling']['samples'][chosen['index']]['used']


def test_point_and_region_change_only_psd_and_export_exact_membership(session):
    client,data=session
    s=data['settings'];common=dict(id=data['id'],revision=data['revision'])
    for route,keys in [('render',('low','high','gain','roi')),('field',('frequency','axis','points','roi','reference','reference_last'))]:
        result=client.post('/api/'+route,json=dict(common,**{k:s[k] for k in keys}))
        assert result.status_code==200,result.get_json()
    before=client.get('/api/session').get_json()
    for change in [dict(spectrum_source='point',spectrum_point=[90,94]),
                   dict(spectrum_source='region',spectrum_region=[45,45,100,100]),dict(spectrum_source='frame')]:
        data=save(client,data,**change)
        assert data['spectrum'] is None
        assert data['field_key']==before['field_key'] and data['field']==before['field']
        assert data['render_key']==before['render_key'] and data['render_info']==before['render_info']
        assert data['settings']['roi'] is None and data['settings']['points']==s['points']
        result=spectrum(client,data)
        export=client.get(f"/api/export/{data['id']}").get_json()['displacement_spectrum']
        assert export['sampling']==result['sampling']
        assert result['sampling']['accepted_count']==result['psd_metadata']['accepted_trace_count']
        if change['spectrum_source']=='region':
            assert all(60<=p['x']<=130 and 60<=p['y']<=130 for p in result['sampling']['samples'])
    snapshot=client.get('/api/session').get_json()
    assert snapshot['sampling']==result['sampling']


def test_incomplete_point_is_marked_and_withheld(session):
    client,data=session
    data=save(client,data,spectrum_source='point',spectrum_point=[160,170])
    result=spectrum(client,data)
    assert not result['spectrum_available']
    selected=[p for p in result['sampling']['samples'] if p['selected']]
    assert len(selected)==1 and selected[0]['eligible'] is False and not selected[0]['used']


def test_fractional_point_reports_the_same_trace_that_the_psd_uses(session):
    client,data=session
    data=save(client,data,spectrum_source='point',spectrum_point=[90.2,94.3])
    result=spectrum(client,data)
    assert result['sampling']['accepted_count']==result['psd_metadata']['accepted_trace_count']==1


def test_psd_frame_selection_ignores_measurement_points_and_roi(session):
    client,data=session
    data=save(client,data,spectrum_source='frame')
    first=spectrum(client,data)
    old_revision=data['revision']
    data=save(client,data,points=[[90,94]],roi=[40,38,100,112])
    second=spectrum(client,data)
    assert first['key']==second['key']
    assert client.get(f"/api/sampling/{data['id']}?revision={old_revision}").status_code==400


@pytest.mark.parametrize('change',[
    dict(spectrum_source='invalid'),dict(spectrum_source='point'),dict(spectrum_source='region'),
    dict(spectrum_point=[1,1]),dict(spectrum_point=['nan',40]),dict(spectrum_region=[0,0,20,20]),
    dict(spectrum_region=[0,0,999,50]),dict(spectrum_region=[0,0,50,float('inf')]),
])
def test_invalid_selection_preserves_session(session,change):
    client,data=session
    before=client.get('/api/session').get_json()
    response=client.post('/api/settings',json=dict(id=data['id'],revision=data['revision'],settings=dict(data['settings'],**change)))
    assert response.status_code==400
    assert client.get('/api/session').get_json()==before


def test_small_legacy_roi_does_not_break_session_recovery(session):
    client,data=session
    data=save(client,data,points=[],roi=[0,0,8,8])
    assert data['sampling']['samples']==[]
    assert data['sampling']['label']=='No usable sample centers'


def test_completed_psd_keeps_its_sampling_membership_when_other_tracking_caches_change(session):
    client,data=session
    data=save(client,data,spectrum_source='frame')
    result=spectrum(client,data)
    server.state['field_cache']=None
    snapshot=client.get('/api/session').get_json()
    assert snapshot['sampling']==result['sampling']
    assert snapshot['sampling']['accepted_count']==result['psd_metadata']['accepted_trace_count']
