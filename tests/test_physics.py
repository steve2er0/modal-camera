import numpy as np
import pytest
from modal_camera.processing import (Video,analyze_tracks,track_points,decode_video,
                                     magnify,temporal_bandpass,validate_band)


def test_known_frequency_amplitude_relative_phase(clean,clean_traces):
    result = analyze_tracks(clean,clean_traces,'y',3)
    assert result['peak_frequency_hz'] == pytest.approx(3,abs=.17)
    for p,amplitude in zip(result['points'],[.4,.6]):
        assert p['valid_fraction'] > .98
        assert p['fit']['amplitude_peak_px'] == pytest.approx(amplitude,abs=.045)
    assert result['points'][1]['fit']['relative_phase_deg'] == pytest.approx(60,abs=5)


def test_x_axis_and_second_frequency(clean,clean_traces):
    x = analyze_tracks(clean,clean_traces,'x',3)
    for p,expected in zip(x['points'],[.18,.28]):
        assert p['fit']['amplitude_peak_px'] == pytest.approx(expected,abs=.04)
    y = analyze_tracks(clean,clean_traces,'y',7)
    for p,expected in zip(y['points'],[.12,.10]):
        assert p['fit']['amplitude_peak_px'] == pytest.approx(expected,abs=.035)


def test_dropout_warns_and_withholds_fit(demos):
    video = decode_video(demos/'tracking_dropout.avi')
    traces = track_points(video,[[90,94],[230,94]])
    result = analyze_tracks(video,traces,'y',3)
    p1,p2 = result['points']
    assert p1['fit']['amplitude_peak_px'] == pytest.approx(.4,abs=.045)
    assert p2['valid_fraction'] < .82
    assert p2['fit'] is None
    assert p2['spectrum_px'] is None
    assert p2['psd_px2_per_hz'] is None
    assert result['psd_metadata']['accepted_trace_count'] == 1
    np.testing.assert_allclose(result['psd_px2_per_hz'],p1['psd_px2_per_hz'])
    assert sum(not x for x in p2['valid'][120:192]) >= 69
    assert p2['warnings']
    assert max(p2['quality']['residual_gray'][120:192]) > 22 or min(p2['quality']['ncc'][120:192]) < .85
    # Fixed reference can reacquire the original patch after occlusion.
    assert sum(p2['valid'][205:]) > 140


def test_low_texture_warns_and_has_no_phase(clean):
    traces = track_points(clean,[[160,170]])
    result = analyze_tracks(clean,traces,'y',3)
    assert result['points'][0]['valid_fraction'] == 0
    assert result['points'][0]['fit'] is None
    assert any('Low texture' in w for w in result['points'][0]['warnings'])
    assert not result['spectrum_available']
    assert result['points'][0]['psd_px2_per_hz'] is None
    assert result['psd_peak_frequency_hz'] is None


def test_temporal_band_response():
    fps=60;n=600;t=np.arange(n)/fps
    raw=.4*np.cos(2*np.pi*3*t)+.12*np.cos(2*np.pi*7*t)
    filtered=temporal_bandpass(raw,fps,2.5,3.5)
    selection=slice(120,-120)
    matrix=np.column_stack([np.cos(2*np.pi*3*t[selection]),np.sin(2*np.pi*3*t[selection]),np.cos(2*np.pi*7*t[selection]),np.sin(2*np.pi*7*t[selection])])
    coeff=np.linalg.lstsq(matrix,filtered[selection],rcond=None)[0]
    assert np.hypot(*coeff[:2])==pytest.approx(.4,abs=.005)
    assert np.hypot(*coeff[2:])<.002


def test_eulerian_display_response_and_band_change(clean):
    amplified,info = magnify(clean,2.5,3.5,1)
    traces=track_points(Video(amplified,60,320,200,'render QA',[]),[[90,94]])
    result3=analyze_tracks(clean,traces,'y',3)
    result7=analyze_tracks(clean,traces,'y',7)
    assert result3['points'][0]['fit']['amplitude_peak_px']==pytest.approx(.8,abs=.09)
    assert result7['points'][0]['fit']['amplitude_peak_px']==pytest.approx(.12,abs=.035)
    other,_=magnify(clean,6.5,7.5,1)
    other_traces=track_points(Video(other,60,320,200,'render QA',[]),[[90,94]])
    assert analyze_tracks(clean,other_traces,'y',3)['points'][0]['fit']['amplitude_peak_px']==pytest.approx(.4,abs=.05)
    assert analyze_tracks(clean,other_traces,'y',7)['points'][0]['fit']['amplitude_peak_px']==pytest.approx(.24,abs=.04)
    assert not np.array_equal(amplified,other)
    assert info['clipping_fraction'] < .02


def test_gain_zero_roi_and_stationary_background(clean):
    zero,_=magnify(clean,2.5,3.5,0)
    assert np.array_equal(zero,clean.frames)
    region,_=magnify(clean,2.5,3.5,2,[40,38,100,112])
    # YCrCb round trip alone can differ by one gray level outside ROI.
    assert np.abs(region[:,:,180:].astype(int)-clean.frames[:,:,180:].astype(int)).max() <= 1
    full,_=magnify(clean,2.5,3.5,2)
    assert np.mean(np.abs(full[:,160:185,145:175].astype(float)-clean.frames[:,160:185,145:175])) < 1
    assert np.mean(np.abs(region[:,65:120,60:125].astype(float)-clean.frames[:,65:120,60:125])) > .2


@pytest.mark.parametrize('band',[(0,4),(4,3),(2,30),(float('nan'),4),(.1,1),(3,3.01)])
def test_invalid_frequency_band(clean,band):
    with pytest.raises(ValueError):validate_band(clean.fps,len(clean.frames),*band)


@pytest.mark.parametrize('gain',[-1,21,float('nan')])
def test_invalid_gain(clean,gain):
    with pytest.raises(ValueError):magnify(clean,2.5,3.5,gain)


def test_translation_reference_subtraction(clean,clean_traces):
    # Same accepted trace assigned to a second stationary reference: identical
    # apparent motion must cancel exactly, with original raw samples retained.
    reference=dict(clean_traces[0],point=2)
    result=analyze_tracks(clean,[clean_traces[0],reference],'y',3,reference_last=True)
    assert result['reference_last']
    assert max(abs(x) for x in result['points'][0]['dy'] if x is not None)==0
    assert result['points'][0]['raw_dy']==clean_traces[0]['dy']
    assert result['points'][0]['fit']['relative_phase_deg'] is None


def test_measurements_rescale_to_source_pixels(clean):
    source=Video(clean.frames,60,640,400,'2x source',[])
    points=analyze_tracks(source,track_points(source,[[90,94]]),'y',3)['points']
    assert points[0]['fit']['amplitude_peak_px']==pytest.approx(.8,abs=.09)


def analytic_trace(values):
    n=len(values)
    return dict(point=1,x=90.,y=94.,dx=[0.]*n,dy=values.tolist(),valid=[True]*n,
                quality={},valid_fraction=1.,warnings=[])


def test_psd_density_power_and_two_known_tones():
    # Validate density scaling by integrated physical sinusoidal power, including
    # an arbitrary offset/drift that detrending must remove.
    n=600;fps=60.;t=np.arange(n)/fps
    values=2.3+.02*t+.4*np.cos(2*np.pi*3*t)+.12*np.cos(2*np.pi*7*t)
    video=Video(np.zeros((n,16,16,3),np.uint8),fps,16,16,'analytic trace',[])
    result=analyze_tracks(video,[analytic_trace(values)],'y',3)
    frequency=np.array(result['frequencies']);density=np.array(result['points'][0]['psd_px2_per_hz'])
    assert result['psd_peak_frequency_hz']==pytest.approx(3)
    assert np.sum(density)*.1==pytest.approx((.4**2+.12**2)/2,abs=2e-5)
    assert np.sum(density[(frequency>=2.8)&(frequency<=3.2)])*.1==pytest.approx(.4**2/2,abs=2e-5)
    assert np.sum(density[(frequency>=6.8)&(frequency<=7.2)])*.1==pytest.approx(.12**2/2,abs=2e-5)
    assert result['points'][0]['rms_from_psd_px']==pytest.approx(np.sqrt(.0872),abs=5e-5)
    assert result['psd_metadata']['enbw_hz']==pytest.approx(.15)
    assert result['psd_metadata']['segments']==1
    assert not result['psd_metadata']['zero_padding']


def test_psd_nyquist_is_not_doubled():
    n=600;values=.4*(-1.)**np.arange(n)
    video=Video(np.zeros((n,16,16,3),np.uint8),60.,16,16,'Nyquist analytic',[])
    result=analyze_tracks(video,[analytic_trace(values)],'y',3)
    assert np.sum(result['psd_px2_per_hz'])*.1==pytest.approx(.4**2,abs=2e-5)
    assert result['psd_peak_frequency_hz']==pytest.approx(30.)
    assert result['points'][0]['spectrum_px'][-1]==pytest.approx(.4,abs=1e-5)


def test_psd_source_units_and_timebase_scaling(clean,clean_traces):
    first=analyze_tracks(clean,clean_traces,'y',3)
    doubled_traces=[dict(p,dx=[None if x is None else 2*x for x in p['dx']],dy=[None if x is None else 2*x for x in p['dy']]) for p in clean_traces]
    doubled=analyze_tracks(clean,doubled_traces,'y',3)
    np.testing.assert_allclose(doubled['psd_px2_per_hz'],np.array(first['psd_px2_per_hz'])*4,rtol=1e-12)
    fast=Video(clean.frames,600.,320,200,'assumed faster capture',[],encoded_fps=60.,timing_basis='user-assumed capture time')
    scaled=analyze_tracks(fast,clean_traces,'y',30)
    np.testing.assert_allclose(scaled['frequencies'],np.array(first['frequencies'])*10,rtol=1e-12)
    np.testing.assert_allclose(scaled['psd_px2_per_hz'],np.array(first['psd_px2_per_hz'])/10,rtol=1e-12)
    assert scaled['points'][0]['rms_from_psd_px']==pytest.approx(first['points'][0]['rms_from_psd_px'])


def test_stationary_trace_has_zero_psd_and_no_arbitrary_peak():
    n=120;video=Video(np.zeros((n,16,16,3),np.uint8),60.,16,16,'stationary',[])
    result=analyze_tracks(video,[analytic_trace(np.zeros(n))],'y',3)
    assert result['psd_peak_frequency_hz'] is None
    assert max(result['psd_px2_per_hz'])==0.
