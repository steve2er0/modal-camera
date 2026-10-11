"""Scientific core. Measurements always use decoded original frames.

Magnification is linear Eulerian luminance processing, not tracked-point warping
and not a phase-based steerable pyramid. See README for validity boundaries.
"""
from dataclasses import dataclass
from pathlib import Path
import math

import cv2
import numpy as np
from scipy import signal
from scipy.fft import rfft, irfft, rfftfreq

MAX_FRAMES = 600
MAX_PIXELS = 24_000_000  # temporal pixel budget; RGB originals ~72 MB
MAX_WIDTH = 640
cv2.setNumThreads(2)


@dataclass
class Video:
    frames: np.ndarray  # RGB uint8, N,H,W,3
    fps: float
    source_width: int
    source_height: int
    name: str
    warnings: list
    encoded_fps: float = None
    timing_basis: str = 'encoded video time'

    @property
    def metadata(self):
        n, h, w, _ = self.frames.shape
        return dict(name=self.name, fps=self.fps, encoded_fps=self.encoded_fps or self.fps, timing_basis=self.timing_basis, frames=n, width=w, height=h,
                    source_width=self.source_width, source_height=self.source_height,
                    scale_x=self.source_width / w, scale_y=self.source_height / h,
                    duration=n / self.fps, nyquist=self.fps / 2,
                    resolution_hz=self.fps / n, warnings=self.warnings)


def decode_video(path, name=None):
    """Bounded decode; reject unsupported, oversized, irregular or incomplete clips."""
    cap = cv2.VideoCapture(str(path))
    try:
        if not cap.isOpened():
            raise ValueError('Cannot decode this video. Try a constant-frame-rate MP4, MOV or AVI.')
        fps = float(cap.get(cv2.CAP_PROP_FPS))
        if not math.isfinite(fps) or not 1 <= fps <= 1000:
            raise ValueError('Missing or invalid frame rate; convert to a known constant frame rate.')
        count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if count > MAX_FRAMES:
            raise ValueError(f'Clip has {count} frames. Trim to at most {MAX_FRAMES} frames; no frames are silently dropped.')
        sw, sh = int(cap.get(3)), int(cap.get(4))
        if sw < 16 or sh < 16 or sw * sh > 40_000_000:
            raise ValueError('Invalid or unsupported video dimensions.')
        factor = min(1., MAX_WIDTH / sw, math.sqrt(MAX_PIXELS / max(count, MAX_FRAMES if count <= 0 else count) / sw / sh))
        w, h = max(16, int(sw * factor)), max(16, int(sh * factor))
        frames, times = [], []
        for i in range(MAX_FRAMES + 1):
            ok, frame = cap.read()
            if not ok:
                break
            if i == MAX_FRAMES:
                raise ValueError(f'Clip exceeds {MAX_FRAMES} frames. Trim before importing.')
            if frame.shape[:2] != (sh, sw):
                raise ValueError('Video changes dimensions partway through; convert it first.')
            if (i + 1) * w * h > MAX_PIXELS:
                raise ValueError('Decoded clip exceeds the memory budget. Trim it first.')
            times.append(float(cap.get(cv2.CAP_PROP_POS_MSEC)) / 1000)
            frame = cv2.resize(frame, (w, h), interpolation=cv2.INTER_AREA) if (w,h) != (sw,sh) else frame
            frames.append(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        if len(frames) < 32:
            raise ValueError('At least 32 decodable frames are required.')
        if count > 0 and len(frames) < count - 1:
            raise ValueError('Video ended before its declared frame count; it may be damaged.')
        warnings = ['Frame rate does not prove absence of aliasing; motion above Nyquist cannot be recovered.',
                    'Camera motion, lighting flicker, rolling shutter and changing texture can contaminate results.']
        dt = np.diff(times)
        if np.isfinite(dt).all() and (dt > 0).all():
            if np.max(np.abs(dt - 1 / fps)) > .08 / fps:
                raise ValueError('Irregular/variable frame timing detected. Convert to constant frame rate before analysis.')
        else:
            warnings.append('Decoder timestamps unavailable: constant frame timing is assumed from metadata; verify capture timing.')
        if (w,h) != (sw,sh):
            warnings.append(f'Analysis resized to {w}×{h}. Reported displacement is rescaled to source pixels; subpixel detail is reduced.')
        duplicate_count = sum(np.array_equal(frames[i],frames[i-1]) for i in range(1,len(frames)))
        if duplicate_count:
            warnings.append(f'{duplicate_count} exactly repeated adjacent frames detected. Duplicated frames can bias timing and motion; verify the original capture rate.')
        warnings.append('Frequencies use encoded video time. Slow motion, archival transfers and interpolated frames may differ from physical time; original capture timing is not inferred.')
        return Video(np.stack(frames), fps, sw, sh, name or Path(path).name, warnings)
    finally:
        cap.release()


def validate_band(fps, n, low, high):
    if not all(math.isfinite(v) for v in (low, high)) or not 0 < low < high < fps / 2:
        raise ValueError('Band must satisfy 0 < low < high < Nyquist (fps/2).')
    if high - low < fps / n:
        raise ValueError('Band is narrower than the clip frequency resolution. Use a longer clip or widen the band.')
    if low < 2 * fps / n:
        raise ValueError('At least two cycles of the lowest band frequency are required. Use a longer clip.')


def temporal_bandpass(values, fps, low, high):
    """Zero-phase FFT bandpass with reflection padding and cosine shoulders.

    Unit response in [low, high]; shoulders one original-record bin wide.
    Padding reduces wrap discontinuities but does not improve true resolution.
    """
    n = len(values)
    validate_band(fps, n, low, high)
    pad = n // 2
    data = np.pad(np.asarray(values, np.float32), [(pad,pad)] + [(0,0)] * (values.ndim - 1), mode='reflect')
    freq = rfftfreq(len(data), 1 / fps)
    shoulder = fps / n
    response = np.zeros_like(freq)
    response[(freq >= low) & (freq <= high)] = 1
    lower = (freq > max(0,low - shoulder)) & (freq < low)
    upper = (freq > high) & (freq < high + shoulder)
    response[lower] = .5 * (1 + np.cos(np.pi * (low - freq[lower]) / shoulder))
    response[upper] = .5 * (1 + np.cos(np.pi * (freq[upper] - high) / shoulder))
    response[0] = 0
    transformed = rfft(data, axis=0, workers=2)
    transformed *= response.reshape((-1,) + (1,) * (values.ndim - 1))
    return irfft(transformed, n=len(data), axis=0, workers=2)[pad:pad+n].astype(np.float32)


def magnify(video, low, high, gain, roi=None, return_response=False):
    """Add bandpassed Laplacian luminance levels to every original frame."""
    frames, fps = video.frames, video.fps
    validate_band(fps, len(frames), low, high)
    if not math.isfinite(gain) or not 0 <= gain <= 20:
        raise ValueError('Added gain α must be between 0 and 20; start at 2–4.')
    n,h,w,_ = frames.shape
    if roi is not None:
        x,y,rw,rh = [int(v) for v in roi]
        if rw < 8 or rh < 8 or x < 0 or y < 0 or x+rw > w or y+rh > h:
            raise ValueError('ROI must lie inside the image and be at least 8×8 pixels.')
    ycc = np.stack([cv2.cvtColor(f, cv2.COLOR_RGB2YCrCb) for f in frames])
    gray = ycc[:,:,:,0].astype(np.float32)
    levels = []
    sizes = [(w,h)]
    current = gray
    for _ in range(4):
        down = np.stack([cv2.pyrDown(f) for f in current])
        up = np.stack([cv2.pyrUp(f, dstsize=(current.shape[2],current.shape[1])) for f in down])
        levels.append(current - up)
        current = down
        sizes.append((current.shape[2],current.shape[1]))
        if min(current.shape[1:]) < 8:
            break
    # Coarsest Gaussian residual is deliberately excluded (broad color changes).
    delta = np.zeros_like(current)
    for lev in reversed(range(len(levels))):
        if delta.shape[1:] != levels[lev].shape[1:]:
            delta = np.stack([cv2.pyrUp(f, dstsize=sizes[lev]) for f in delta])
        delta += temporal_bandpass(levels[lev], fps, low, high)
    if roi is not None:
        mask = np.zeros((h,w), np.float32)
        mask[y:y+rh,x:x+rw] = 1
        # Feather inside the selection, never amplify outside it.
        mask = cv2.GaussianBlur(mask, (0,0), 3) * mask
        delta *= mask
    guard = min(n//3, max(1, int(math.ceil(fps / low))))
    # Measure the unamplified band signal, before clipping or color conversion.
    response = np.sqrt(np.mean(delta[guard:n-guard] ** 2, axis=0))
    luminance = gray + gain * delta
    clipping = float(np.mean((luminance < 0) | (luminance > 255)))
    ycc[:,:,:,0] = np.clip(luminance,0,255).astype(np.uint8)
    result = np.stack([cv2.cvtColor(f, cv2.COLOR_YCrCb2RGB) for f in ycc])
    if gain == 0:
        result = frames.copy()
    warnings = [f'Linear Eulerian luminance magnification; α={gain:g} is added gain. Ideal small-motion factor ≈1+α, spatial-scale dependent.',
                f'Temporal edge caution: first/last {guard / fps:.2f} s. Offline, zero-phase filter; one-bin cosine shoulders.',
                'Magnified frames are visualization only. Large amplified displacement creates halos/ghosting; lighting variations are also amplified.']
    if gain > 4:
        warnings.append('High gain: inspect halos and saturation; reliable displacement is not guaranteed by this gain setting.')
    if clipping > .001:
        warnings.append(f'{100*clipping:.2f}% of luminance samples clipped. Lower gain or narrow the band.')
    info = dict(low=low,high=high,gain=gain,roi=roi,clipping_fraction=clipping,edge_guard_frames=guard,warnings=warnings)
    if return_response:
        reference = float(np.percentile(response,99))
        info['response'] = dict(method='RMS of unamplified reconstructed bandpassed Laplacian luminance',
                                units='luminance gray levels RMS',display_reference_rms=reference,
                                edge_guard_frames=guard,normalization='99th percentile; display saturates above it',
                                caveat='Image variation, not displacement. Texture and illumination affect sensitivity; dark does not prove stationary.')
        return result, info, response
    return result, info


def _finite_list(values):
    return [float(x) if math.isfinite(float(x)) else None for x in values]


def track_points(video, points):
    """Pyramidal LK from fixed original reference; FB and patch metrics per frame.

    Fixed-reference registration avoids accumulating pairwise drift, and supports
    reacquisition after dropout. Intended for small bounded vibrations only.
    """
    if not isinstance(points,list) or not 1 <= len(points) <= 8:
        raise ValueError('Select one to eight points.')
    return track_locations(video, points)


def track_locations(video, points):
    """Internal bounded batch tracker shared by point and spatial measurements."""
    if not isinstance(points,list) or not 1 <= len(points) <= 256:
        raise ValueError('Spatial tracking requires one to 256 locations.')
    n,h,w,_ = video.frames.shape
    coords = np.array(points, np.float32)
    if coords.shape != (len(points),2) or not np.isfinite(coords).all():
        raise ValueError('Point coordinates must be finite x,y pairs.')
    if (coords[:,0] < 16).any() or (coords[:,0] >= w-16).any() or (coords[:,1] < 16).any() or (coords[:,1] >= h-16).any():
        raise ValueError('Place points at least 16 analysis pixels from image edges.')
    gray = [cv2.cvtColor(f,cv2.COLOR_RGB2GRAY) for f in video.frames]
    p0 = coords.reshape(-1,1,2)
    k = len(points)
    position = np.full((n,k,2),np.nan)
    valid = np.zeros((n,k),bool)
    fb_error = np.full((n,k),np.inf)
    ncc = np.zeros((n,k))
    residual = np.full((n,k),np.inf)
    texture = np.zeros((n,k))
    templates = [cv2.getRectSubPix(gray[0],(25,25),tuple(p)).astype(np.float32) for p in coords]
    eig = cv2.cornerMinEigenVal(gray[0],blockSize=7,ksize=3)
    reference_eig = [float(cv2.getRectSubPix(eig,(15,15),tuple(p)).mean()) for p in coords]
    params = dict(winSize=(31,31), maxLevel=2, criteria=(cv2.TERM_CRITERIA_EPS|cv2.TERM_CRITERIA_COUNT,40,.001),minEigThreshold=1e-5)
    for i,frame in enumerate(gray):
        q,st,_ = cv2.calcOpticalFlowPyrLK(gray[0],frame,p0,None,**params)
        back,bst,_ = cv2.calcOpticalFlowPyrLK(frame,gray[0],q,None,**params)
        frame_eig = cv2.cornerMinEigenVal(frame,blockSize=7,ksize=3)
        for j in range(k):
            x,y = q[j,0]
            fb_error[i,j] = np.linalg.norm(back[j,0] - coords[j])
            patch = cv2.getRectSubPix(frame,(25,25),(float(x),float(y))).astype(np.float32)
            a,b = templates[j]-templates[j].mean(),patch-patch.mean()
            ncc[i,j] = float(np.sum(a*b) / max(1e-6,np.linalg.norm(a)*np.linalg.norm(b)))
            residual[i,j] = float(np.sqrt(np.mean((patch-templates[j])**2)))
            texture[i,j] = float(cv2.getRectSubPix(frame_eig,(15,15),(float(x),float(y))).mean())
            inside = 13 <= x < w-13 and 13 <= y < h-13
            valid[i,j] = bool(st[j,0] and bst[j,0] and inside and fb_error[i,j] < .35 and ncc[i,j] > .85 and residual[i,j] < 22 and reference_eig[j] > .0001 and texture[i,j] > .0001)
            if valid[i,j]:
                position[i,j] = q[j,0]
    traces = []
    for j in range(k):
        disp = (position[:,j] - coords[j]) * [video.source_width/w,video.source_height/h]
        failed = int((~valid[:,j]).sum())
        warning = []
        if reference_eig[j] <= .0001:
            warning.append('Low texture / aperture ambiguity at the reference point. Select a textured corner.')
        if failed:
            warning.append(f'Tracking quality dropped in {failed}/{n} frames. Rejected samples are gaps; fits never interpolate them.')
        traces.append(dict(point=j+1,x=float(coords[j,0]),y=float(coords[j,1]),dx=_finite_list(disp[:,0]),dy=_finite_list(disp[:,1]),valid=valid[:,j].tolist(),
                           quality=dict(fb_error_px=_finite_list(fb_error[:,j]),ncc=_finite_list(ncc[:,j]),residual_gray=_finite_list(residual[:,j]),texture=_finite_list(texture[:,j]),reference_texture=reference_eig[j]),
                           valid_fraction=float(valid[:,j].mean()),warnings=warning))
    return traces


def analyze_tracks(video, traces, axis='y', frequency=None, reference_last=False):
    if axis not in ('x','y'):
        raise ValueError('Axis must be x or y.')
    n = len(video.frames)
    if reference_last:
        if len(traces) < 2:
            raise ValueError('Camera reference subtraction needs at least two points. Place the last point on stationary structure.')
        reference = traces[-1]
        corrected = []
        for trace in traces:
            copy = dict(trace,raw_dx=trace['dx'],raw_dy=trace['dy'])
            for key in ('dx','dy'):
                copy[key] = [a-b if a is not None and b is not None else None for a,b in zip(trace[key],reference[key])]
            copy['valid'] = [a and b for a,b in zip(trace['valid'],reference['valid'])]
            copy['valid_fraction'] = sum(copy['valid'])/n
            copy['warnings'] = trace['warnings'] + [f"Translation of P{len(traces)} subtracted. This reference must be stationary; rotation/perspective are not corrected."]
            corrected.append(copy)
        traces = corrected
    t = np.arange(n) / video.fps
    freq = rfftfreq(n,1/video.fps)
    spectra, densities, spectral_stats, results = [], [], [], []
    for trace in traces:
        values = np.array([np.nan if x is None else x for x in trace['d'+axis]])
        good = np.isfinite(values)
        if good.all():
            detrended = signal.detrend(values)
            window = np.hanning(n)
            amplitude = 2 * np.abs(rfft(detrended*window)) / window.sum()
            amplitude[0] = 0
            if n % 2 == 0:
                amplitude[-1] *= .5  # Nyquist has no separate negative-frequency partner.
            spectra.append(amplitude)
            psd_freq, density = signal.periodogram(values, fs=video.fps, window='hann',
                                                   detrend='linear', return_onesided=True,
                                                   scaling='density', nfft=n)
            densities.append(density)
            peaks, _ = signal.find_peaks(density)
            peaks = sorted(peaks, key=lambda i: density[i], reverse=True)[:3]
            spectral_stats.append(dict(rms_from_psd_px=float(np.sqrt(np.sum(density)*video.fps/n)),
                                       psd_peaks=[dict(frequency_hz=float(psd_freq[i]),density_px2_per_hz=float(density[i])) for i in peaks]))
        else:
            spectra.append(None)  # no misleading FFT of filled dropout data
            densities.append(None)
            spectral_stats.append(dict(rms_from_psd_px=None,psd_peaks=[]))
    valid_spectra = [s for s in spectra if s is not None]
    mean_spectrum = np.mean(valid_spectra,axis=0) if valid_spectra else np.zeros(len(freq))
    peak = float(freq[np.argmax(mean_spectrum)]) if valid_spectra else None
    valid_densities = [d for d in densities if d is not None]
    mean_density = np.mean(valid_densities, axis=0) if valid_densities else np.zeros(len(freq))
    psd_peak = float(freq[1+np.argmax(mean_density[1:])]) if valid_densities and np.max(mean_density[1:]) > 0 else None
    f = float(frequency) if frequency is not None else peak
    if f is None:
        f = 3. if video.fps > 6 else video.fps/4
    if not math.isfinite(f) or not 0 < f < video.fps/2:
        raise ValueError('Measurement frequency must be strictly below Nyquist and above zero.')
    edge = min(n//3,int(math.ceil(video.fps/f)))
    reference_phase = None
    for j,trace in enumerate(traces):
        values = np.array([np.nan if x is None else x for x in trace['d'+axis]])
        good = np.isfinite(values)
        good[:edge] = False
        good[-edge:] = False
        fraction = float(good.sum()/max(1,n-2*edge))
        fit = None
        if fraction >= .8 and good.sum() >= 24 and f * (t[good][-1]-t[good][0]) >= 3:
            # cos convention: x(t)=A cos(2πft + φ), plus offset and linear drift.
            matrix = np.column_stack([np.cos(2*np.pi*f*t[good]),np.sin(2*np.pi*f*t[good]),np.ones(good.sum()),t[good]-t[good].mean()])
            coeff,_,_,_ = np.linalg.lstsq(matrix,values[good],rcond=None)
            amplitude = float(np.hypot(coeff[0],coeff[1]))
            phase = float(np.rad2deg(np.arctan2(-coeff[1],coeff[0])))
            rms = float(np.sqrt(np.mean((matrix@coeff-values[good])**2)))
            identifiable = amplitude > max(.01, 2*rms/np.sqrt(good.sum()))
            if j == 0 and identifiable:
                reference_phase = phase
            relative = (phase-reference_phase+180)%360-180 if identifiable and reference_phase is not None else None
            fit = dict(amplitude_peak_px=amplitude,phase_deg=phase if identifiable else None,relative_phase_deg=relative,rms_residual_px=rms,accepted_fit_fraction=fraction,samples=int(good.sum()))
        warnings = list(trace['warnings'])
        if fit is None:
            warnings.append('Amplitude/phase withheld: insufficient accepted data or fewer than three cycles after edge exclusion.')
        elif fit['relative_phase_deg'] is None:
            warnings.append('Relative phase unavailable: P1 or this point has insufficient motion signal.')
        results.append(dict(trace,fit=fit,warnings=warnings,spectrum_px=spectra[j].tolist() if spectra[j] is not None else None,
                            psd_px2_per_hz=densities[j].tolist() if densities[j] is not None else None,**spectral_stats[j]))
    return dict(points=results,frequency_hz=f,peak_frequency_hz=peak,axis=axis,time=t.tolist(),frequencies=freq.tolist(),spectrum_px=mean_spectrum.tolist(),
                spectrum_available=bool(valid_spectra),resolution_hz=video.fps/n,phase_reference='P1; positive means leads P1; cos(2πft+φ); video t=0',
                units='source pixels (camera-plane projection)',fit_edge_excluded_s=edge/video.fps,reference_last=reference_last,
                psd_px2_per_hz=mean_density.tolist(),psd_peak_frequency_hz=psd_peak,
                psd_metadata=dict(method='One-sided full-record Hann periodogram',window='periodic Hann',detrend='linear',
                                  units='source pixels squared per Hz',bin_width_hz=video.fps/n,enbw_hz=1.5*video.fps/n,
                                  duration_s=n/video.fps,segments=1,zero_padding=False,timing_basis=video.timing_basis,
                                  accepted_trace_count=len(valid_densities),total_trace_count=len(traces),
                                  gap_policy='Any rejected sample withholds that trace spectrum; no interpolation'))
