"""Target-independent spectra of original, quality-gated displacement tracks."""
import math
import numpy as np
from scipy import signal


def peak_bins(density, frequencies):
    peaks, _ = signal.find_peaks(density)
    peaks = sorted(peaks, key=lambda i: density[i], reverse=True)[:6]
    return [dict(frequency_hz=float(frequencies[i]), density_px2_per_hz=float(density[i]))
            for i in peaks if density[i] > 0]


def validate_highpass(cutoff, video):
    try:
        cutoff = float(cutoff)
    except (TypeError, ValueError):
        raise ValueError('PSD high-pass cutoff must be a finite number.')
    minimum = 2 * video.fps / len(video.frames)
    if not math.isfinite(cutoff) or cutoff < 0:
        raise ValueError('PSD high-pass cutoff must be finite and nonnegative; zero disables it.')
    if cutoff and not minimum <= cutoff < video.fps / 2:
        raise ValueError(f'PSD high-pass cutoff must be at least {minimum:.3f} Hz (two record bins) and below {video.fps/2:.3f} Hz, or zero to disable it.')
    return cutoff


def displacement_spectrum(video, traces, axis='y', spatial=False, reference_last=False, highpass_hz=0):
    if axis not in ('x', 'y'):
        raise ValueError('Axis must be x or y.')
    if reference_last and len(traces) < 2:
        raise ValueError('Camera reference subtraction needs at least two selected points.')
    n = len(video.frames)
    highpass_hz = validate_highpass(highpass_hz, video)
    sos = signal.butter(4, highpass_hz, btype='highpass', fs=video.fps, output='sos') if highpass_hz else None
    frequencies = np.fft.rfftfreq(n, 1 / video.fps)
    curves, densities, amplitudes = [], [], []
    reference = traces[-1]['d'+axis] if reference_last else None
    # The stationary reference is not a response sample in the spatial mean.
    measured = traces[:-1] if reference_last else traces
    for trace in measured:
        values = trace['d'+axis]
        if reference is not None:
            values = [a-b if a is not None and b is not None else None for a, b in zip(values, reference)]
        values = np.asarray([np.nan if value is None else value for value in values], float)
        complete = len(values) == n and np.isfinite(values).all()
        curve = dict(point=trace['point'], label=f"P{trace['point']}", psd_px2_per_hz=None,
                     spectrum_px=None, rms_from_psd_px=None, psd_peaks=[])
        if complete:
            if sos is not None:
                # Detrend before filtering to avoid turning offsets/drift into edge transients.
                # Filtering is confined to complete original tracks; rejected samples stay rejected.
                values = signal.sosfiltfilt(sos, signal.detrend(values), padtype='odd')
            _, density = signal.periodogram(values, fs=video.fps, window='hann', detrend='linear',
                                             return_onesided=True, scaling='density', nfft=n)
            window = np.hanning(n)
            amplitude = 2 * np.abs(np.fft.rfft(signal.detrend(values) * window)) / window.sum()
            amplitude[0] = 0
            if n % 2 == 0:
                amplitude[-1] *= .5
            densities.append(density)
            amplitudes.append(amplitude)
            curve.update(psd_px2_per_hz=density.tolist(), spectrum_px=amplitude.tolist(),
                         psd_peaks=peak_bins(density, frequencies),
                         rms_from_psd_px=float(np.sqrt(density.sum() * video.fps / n)))
        curves.append(curve)
    mean_density = np.mean(densities, axis=0) if densities else np.zeros(len(frequencies))
    mean_amplitude = np.mean(amplitudes, axis=0) if amplitudes else np.zeros(len(frequencies))
    peak_list = peak_bins(mean_density, frequencies)
    if spatial:
        curves = [dict(label='Spatial mean', point=None,
                       psd_px2_per_hz=mean_density.tolist() if densities else None,
                       spectrum_px=mean_amplitude.tolist() if densities else None,
                       rms_from_psd_px=float(np.sqrt(mean_density.sum() * video.fps / n)) if densities else None)]
    strongest = lambda values: float(frequencies[1 + np.argmax(values[1:])]) if densities and np.max(values[1:]) > 0 else None
    return dict(axis=axis, source='spatial_grid' if spatial else 'selected_points', points=curves,
                frequencies=frequencies.tolist(), spectrum_available=bool(densities),
                psd_px2_per_hz=mean_density.tolist(), spectrum_px=mean_amplitude.tolist(),
                psd_peaks=peak_list, psd_peak_frequency_hz=strongest(mean_density),
                peak_frequency_hz=strongest(mean_amplitude), resolution_hz=video.fps/n,
                reference_last=reference_last,
                highpass=dict(enabled=bool(highpass_hz), cutoff_hz=highpass_hz,
                              method='Butterworth SOS, forward-backward, odd reflection padding',
                              order_per_pass=4, phase='zero phase', cutoff_two_pass_gain_db=-6.020599913279624,
                              scope='PSD and amplitude spectrum only; response fits and videos use original motion'),
                psd_metadata=dict(method='One-sided full-record Hann periodogram', window='periodic Hann',
                                  detrend='linear', units='source pixels squared per Hz',
                                  bin_width_hz=video.fps/n, enbw_hz=1.5*video.fps/n, duration_s=n/video.fps,
                                  segments=1, zero_padding=False, timing_basis=video.timing_basis,
                                  accepted_trace_count=len(densities), total_trace_count=len(measured),
                                  aggregation='Arithmetic mean of individual displacement PSDs; no phase cancellation',
                                  gap_policy='Any rejected sample withholds that trace spectrum; no interpolation'))
