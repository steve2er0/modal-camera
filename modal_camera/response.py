"""Spatial harmonic response from quality-gated ORIGINAL displacement traces.

Samples are patch measurements, not independent per-pixel displacements. Image
warping interpolates only cells whose four neighboring samples support a fit.
"""
import math

import cv2
import numpy as np

from .processing import track_locations, track_points


def harmonic_fit(values, fps, frequency):
    """Fit cos/sin, offset and drift without filling rejected samples."""
    values = np.asarray([np.nan if v is None else v for v in values], float)
    n = len(values)
    t = np.arange(n) / fps
    edge = min(n // 3, int(math.ceil(fps / frequency)))
    good = np.isfinite(values)
    good[:edge] = False
    good[-edge:] = False
    coverage = float(good.sum() / max(1, n - 2 * edge))
    if coverage < .8 or good.sum() < 24 or frequency * np.ptp(t[good]) < 3:
        return None
    matrix = np.column_stack([np.cos(2 * np.pi * frequency * t[good]),
                              np.sin(2 * np.pi * frequency * t[good]),
                              np.ones(good.sum()), t[good] - t[good].mean()])
    coeff, _, _, _ = np.linalg.lstsq(matrix, values[good], rcond=None)
    amplitude = float(np.hypot(*coeff[:2]))
    residual = float(np.sqrt(np.mean((matrix @ coeff - values[good]) ** 2)))
    identifiable = amplitude > max(.01, 2 * residual / np.sqrt(good.sum()))
    phase = float(np.rad2deg(np.arctan2(-coeff[1], coeff[0]))) if identifiable else None
    # A descriptive signal-to-residual ratio, not statistical coherence.
    fraction = amplitude ** 2 / (amplitude ** 2 + 2 * residual ** 2) if amplitude or residual else 0.
    return dict(amplitude_peak_px=amplitude,phase_deg=phase,coefficients_px=coeff[:2].tolist(),
                rms_residual_px=residual,accepted_fit_fraction=coverage,samples=int(good.sum()),
                harmonic_power_fraction=float(fraction))


def sample_grid(video, roi=None):
    _, h, w, _ = video.frames.shape
    x0, y0, x1, y1 = 16, 16, w - 16, h - 16
    if roi is not None:
        if len(roi) != 4 or not all(math.isfinite(v) for v in roi):
            raise ValueError('ROI must be four finite coordinates.')
        x, y, rw, rh = map(int, roi)
        if rw < 8 or rh < 8 or x < 0 or y < 0 or x + rw > w or y + rh > h:
            raise ValueError('ROI must lie inside the image and be at least 8×8 pixels.')
        x0, y0, x1, y1 = max(x0,x), max(y0,y), min(x1,x+rw), min(y1,y+rh)
    if x1 <= x0 or y1 <= y0:
        raise ValueError('Spatial analysis needs a region away from the 16 px image border.')
    step = max(24, int(math.ceil(math.sqrt((x1-x0)*(y1-y0)/196))))
    xs, ys = np.arange(x0,x1,step), np.arange(y0,y1,step)
    while len(xs) * len(ys) > 256:
        step += 1
        xs, ys = np.arange(x0,x1,step), np.arange(y0,y1,step)
    return [[float(x),float(y)] for y in ys for x in xs], dict(x0=x0,y0=y0,step=step,columns=len(xs),rows=len(ys))


def measure_field(video, frequency, axis='y', roi=None, points=None, reference='auto',
                  reference_last=False, cached=None):
    if axis not in ('x','y'):
        raise ValueError('Axis must be x or y.')
    if not math.isfinite(frequency) or not 0 < frequency < video.fps/2:
        raise ValueError('Spatial fit frequency must be above zero and strictly below Nyquist.')
    if reference not in ('auto','strongest','p1'):
        raise ValueError('Phase reference must be auto, strongest or p1.')
    points = points or []
    if reference == 'p1' and not points:
        raise ValueError('Select P1 in the original image before using it as phase reference.')
    if reference_last and len(points) < 2:
        raise ValueError('Camera subtraction needs a last stationary point and at least two selected points.')
    coords, grid = sample_grid(video,roi)
    identity = (id(video.frames),video.source_width,video.source_height)
    if cached is not None and cached['coordinates'] == coords and cached.get('identity') == identity:
        traces = cached['traces']
    else:
        traces = track_locations(video,coords)
    cache = dict(coordinates=coords,traces=traces,identity=identity)
    selected = track_points(video,points) if points else []
    stationary = selected[-1] if reference_last else None

    def fits(trace):
        result = {}
        for component in ('x','y'):
            values = trace['d'+component]
            if stationary is not None:
                values = [a-b if a is not None and b is not None else None
                          for a,b in zip(values,stationary['d'+component])]
            result[component] = harmonic_fit(values,video.fps,frequency)
        return result

    nodes = []
    for trace in traces:
        fit = fits(trace)
        chosen = fit[axis]
        nodes.append(dict(index=trace['point']-1,x=trace['x'],y=trace['y'],fit=fit,
                          amplitude_peak_px=chosen['amplitude_peak_px'] if chosen else None,
                          phase_deg=chosen['phase_deg'] if chosen else None,relative_phase_deg=None,
                          valid_fraction=trace['valid_fraction'],warnings=trace['warnings']))
    p1 = fits(selected[0])[axis] if selected else None
    reference_node = None
    if reference in ('auto','p1') and p1 and p1['phase_deg'] is not None:
        ref_phase, label = p1['phase_deg'], 'P1'
        reference_location = dict(x=points[0][0],y=points[0][1])
    elif reference == 'p1':
        ref_phase, label, reference_location = None, 'P1 unavailable: weak signal or rejected tracking', None
    else:
        eligible = [p for p in nodes if p['phase_deg'] is not None]
        reference_node = max(eligible,key=lambda p:p['amplitude_peak_px']) if eligible else None
        ref_phase = reference_node['phase_deg'] if reference_node else None
        label = f"Grid {reference_node['index']+1} (strongest accepted {axis.upper()} response)" if reference_node else 'No usable phase reference'
        reference_location = dict(x=reference_node['x'],y=reference_node['y']) if reference_node else None
    if ref_phase is not None:
        for node in nodes:
            if node['phase_deg'] is not None:
                node['relative_phase_deg'] = (node['phase_deg']-ref_phase+180)%360-180
    accepted = [p for p in nodes if p['amplitude_peak_px'] is not None]
    maximum = max((p['amplitude_peak_px'] for p in accepted),default=0.)
    warnings = ['Local estimates use overlapping 31 analysis-pixel tracking windows on original frames; this is a sampled field, not independent per-pixel displacement.',
                'A dark or rejected patch does not establish a node: missing texture, occlusion and camera projection can hide motion.',
                'The animation is a fitted single-frequency operating deflection pattern, not an identified structural eigenmode. Offset, drift and other frequencies are omitted.',
                'Warping uses bilinear interpolation only inside cells with four accepted, measurable neighboring fits. Arrows show the actual sample locations.']
    if stationary is not None:
        warnings.append(f'P{len(points)} translation subtracted from both displacement components; this reference must be stationary. Images are not camera-stabilized.')
    if ref_phase is None:
        warnings.append('Relative phase and modal animation unavailable until the selected axis has a usable phase reference.')
    result = dict(frequency_hz=frequency,axis=axis,roi=roi,timing_basis=video.timing_basis,
                  units='source pixels peak; camera-plane X/Y displacement',grid=grid,nodes=nodes,
                  accepted_nodes=len(accepted),phase_nodes=sum(p['relative_phase_deg'] is not None for p in nodes),
                  amplitude_display_max_px=maximum,reference=dict(label=label,phase_deg=ref_phase,location=reference_location),
                  reference_last=reference_last,phase_convention='cos(2πft+φ); positive relative phase leads reference',
                  method='Fixed-reference pyramidal LK with forward/backward, texture, correlation and brightness gates; accepted-sample harmonic least squares',
                  fit_edge_excluded_s=min(len(video.frames)//3,int(math.ceil(video.fps/frequency)))/video.fps,
                  warnings=warnings)
    maps = interpolate_field(video,result)
    result['interpolated_support_fraction'] = float(maps['support'].mean())
    return result, cache, maps


def interpolate_field(video, result):
    """No extrapolation, no interpolation across failed/weak samples."""
    _, h, w, _ = video.frames.shape
    g = result['grid']
    valid = np.zeros((g['rows'],g['columns']),np.float32)
    coeff = np.zeros((g['rows'],g['columns'],4),np.float32)
    for node in result['nodes']:
        xfit, yfit = node['fit']['x'], node['fit']['y']
        # Directional phase can be absent for a zero component; the orthogonal
        # component may still carry a measurable harmonic motion vector.
        if xfit and yfit and (xfit['phase_deg'] is not None or yfit['phase_deg'] is not None):
            row, col = divmod(node['index'],g['columns'])
            valid[row,col] = 1
            coeff[row,col] = xfit['coefficients_px'] + yfit['coefficients_px']
    yy, xx = np.mgrid[:h,:w].astype(np.float32)
    mx, my = (xx-g['x0'])/g['step'], (yy-g['y0'])/g['step']
    support = np.zeros((h,w),bool)
    if g['rows']>1 and g['columns']>1:
        cells = (valid[:-1,:-1]>0)&(valid[1:,:-1]>0)&(valid[:-1,1:]>0)&(valid[1:,1:]>0)
        inside = (mx>=0)&(my>=0)&(mx<g['columns']-1)&(my<g['rows']-1)
        row = np.clip(np.floor(my).astype(int),0,g['rows']-2)
        col = np.clip(np.floor(mx).astype(int),0,g['columns']-2)
        support = inside & cells[row,col]
    interpolated = cv2.remap(coeff,mx,my,cv2.INTER_LINEAR,borderMode=cv2.BORDER_CONSTANT)
    interpolated[~support] = 0
    # Feather only inside supported cells to soften the visualization boundary.
    feather = cv2.GaussianBlur(support.astype(np.float32),(0,0),1.25)*support
    interpolated *= feather[:,:,None]
    return dict(coefficients=interpolated,support=support,xx=xx,yy=yy)


def modal_frame(video, result, maps, phase_deg, gain, threshold=0.):
    if not math.isfinite(phase_deg) or not math.isfinite(gain) or not 0 <= gain <= 20:
        raise ValueError('Modal phase must be finite and display gain must be between 0 and 20.')
    if result['reference']['phase_deg'] is None:
        raise ValueError('Modal animation needs a usable phase reference on the selected axis.')
    if not math.isfinite(threshold) or not 0 <= threshold <= 1:
        raise ValueError('Modal response threshold must be between 0 and 1.')
    theta = np.deg2rad(phase_deg-result['reference']['phase_deg'])
    c = maps['coefficients']
    dx = (c[:,:,0]*np.cos(theta)+c[:,:,1]*np.sin(theta)) / video.metadata['scale_x']
    dy = (c[:,:,2]*np.cos(theta)+c[:,:,3]*np.sin(theta)) / video.metadata['scale_y']
    if threshold > 0:
        component = 0 if result['axis']=='x' else 2
        amplitude = np.hypot(c[:,:,component],c[:,:,component+1]) / max(result['amplitude_display_max_px'],1e-9)
        blend = np.clip((amplitude-threshold)/.12,0,1)
        blend = blend*blend*(3-2*blend)
        dx *= blend
        dy *= blend
    # A first-order inverse displacement warp of frame 0's texture. This creates
    # a visualization; it never supplies input to any measurement.
    rgb = cv2.remap(video.frames[0],(maps['xx']-gain*dx).astype(np.float32),(maps['yy']-gain*dy).astype(np.float32),
                    cv2.INTER_LINEAR,borderMode=cv2.BORDER_REFLECT_101)
    return rgb
