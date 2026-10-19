"""Fixed-end uniform string modes and a narrow image-space string renderer.

phi_n = sin(n*pi*u), f_n/f_a = n/a sqrt((1+B*n²)/(1+B*a²)).
B=0 is the ideal tensioned string. B>0 is a pinned stiff-string assumption.
https://farside.ph.utexas.edu/teaching/315/Waves/node28.html
"""
import math

import cv2
import numpy as np

from .processing import track_locations
from .response import harmonic_fit


def validate_string_settings(data):
    if not isinstance(data, dict):
        raise ValueError('String assumptions must be an object.')
    if 'strings' in data:
        entries = data['strings']
        if not isinstance(entries, list) or not 1 <= len(entries) <= 6:
            raise ValueError('Select between one and six guitar strings.')
        strings = []
        for i, entry in enumerate(entries):
            if not isinstance(entry, dict) or 'strings' in entry:
                raise ValueError('Each string must contain its own geometry and assumptions.')
            cfg = validate_string_settings(entry)
            name = entry.get('name', f'String {i+1}')
            if not isinstance(name, str) or not 1 <= len(name.strip()) <= 32:
                raise ValueError('Give each string a name of 1–32 characters.')
            enabled = entry.get('enabled', True)
            if type(enabled) is not bool:
                raise ValueError('String enabled must be true or false.')
            frequency = entry.get('anchor_hz')
            if frequency is not None:
                if isinstance(frequency, bool):
                    raise ValueError('String anchor frequency must be a number, not a checkbox value.')
                try:
                    frequency = float(frequency)
                except (ValueError, TypeError):
                    raise ValueError('String anchor frequency must be a finite number, or blank for the selected response.') from None
                if not math.isfinite(frequency) or not 1 <= frequency <= 2000:
                    raise ValueError('String anchor frequency must be between 1 and 2000 Hz.')
            strings.append(dict(cfg, name=name.strip(), enabled=enabled, anchor_hz=frequency))
        if not any(s['enabled'] for s in strings):
            raise ValueError('Enable at least one string for the combined tap.')
        return dict(strings=strings)
    result = {}
    for key, default, low, high in [('span_start', 0., 0., .95), ('span_end', 1., .05, 1.),
                                   ('half_width_px', 3., 1., 8.), ('inharmonicity', 0., 0., .05)]:
        try:
            value = float(data.get(key, default))
        except (ValueError, TypeError):
            raise ValueError(f'String {key} must be a finite number.') from None
        if not math.isfinite(value) or not low <= value <= high:
            raise ValueError(f'String {key} must be between {low} and {high}.')
        result[key] = value
    if result['span_end']-result['span_start'] < .05:
        raise ValueError('The visible string span must cover at least 5% of its full length, with A before B.')
    anchor = data.get('anchor_harmonic', 1)
    if type(anchor) is not int or not 1 <= anchor <= 8:
        raise ValueError('The anchor harmonic must be an integer from 1 to 8.')
    result['anchor_harmonic'] = anchor
    points = data.get('endpoints')
    if points is None:
        result['endpoints'] = None
    else:
        try:
            points = np.asarray(points, float)
        except (ValueError, TypeError):
            raise ValueError('Select two finite endpoints along one visible string.') from None
        if points.shape != (2, 2) or not np.isfinite(points).all() or np.linalg.norm(points[1]-points[0]) < 24:
            raise ValueError('String endpoints must be finite and at least 24 analysis pixels apart.')
        result['endpoints'] = points.tolist()
    amplitude = data.get('amplitude_source_px')
    if amplitude is not None:
        try:
            amplitude = float(amplitude)
        except (ValueError, TypeError):
            raise ValueError('Assumed string amplitude must be a finite number, or blank for a measured patch fit.') from None
        if not math.isfinite(amplitude) or not .001 <= amplitude <= 5:
            raise ValueError('Assumed string amplitude must be 0.001–5 source pixels, or blank for a measured patch fit.')
    result['amplitude_source_px'] = amplitude
    return result


def string_shapes(u):
    return np.sin(np.asarray(u)[..., None]*math.pi*np.arange(1, 9))


def string_frequencies(anchor_hz, anchor_harmonic=1, inharmonicity=0.):
    n = np.arange(1, 9)
    a = anchor_harmonic
    return anchor_hz*n/a*np.sqrt((1+inharmonicity*n*n)/(1+inharmonicity*a*a))


def build_string_model(video, field, data, measurement_settings=None):
    cfg = validate_string_settings(data)
    if 'strings' in cfg:
        return build_string_ensemble(video, field, cfg, measurement_settings)
    if cfg['endpoints'] is None:
        raise ValueError('Mark a visible string segment under Advanced before generating string modes.')
    h, w = video.frames.shape[1:3]
    a,b = np.asarray(cfg['endpoints'], float)
    if np.any(np.asarray([a,b]) < 0) or max(a[0],b[0]) >= w or max(a[1],b[1]) >= h:
        raise ValueError('String endpoints must lie inside the analysis image.')
    if not 0 < field['frequency_hz'] or (field['frequency_hz'] >= video.fps/2 and cfg['amplitude_source_px'] is None):
        raise ValueError('An anchor at or above camera Nyquist needs an explicit assumed amplitude; it cannot be fitted from this video.')
    tangent = (b-a)/np.linalg.norm(b-a)
    direction = np.array([-tangent[1], tangent[0]])
    component = 0 if field['axis'] == 'x' else 1
    if abs(direction[component]) < .15:
        raise ValueError('Select a displacement axis transverse to the string: Y for a horizontal string, X for a vertical string.')
    direction /= direction[component]
    anchor = cfg['anchor_harmonic']-1
    positions = np.linspace(a,b,25)
    fractions = np.linspace(cfg['span_start'],cfg['span_end'],25)
    shapes = string_shapes(fractions)
    track_mask = ((positions[:,0] >= 16) & (positions[:,0] < w-16)
                  & (positions[:,1] >= 16) & (positions[:,1] < h-16))
    coords = positions[track_mask].tolist()
    stationary = bool(field.get('reference_last'))
    if stationary:
        points = (measurement_settings or {}).get('points') or []
        if len(points) < 2:
            raise ValueError('String fitting needs the same stationary reference as the measured field.')
        coords.append(points[-1])
    # Never fit an aliased anchor, even when an explicit amplitude is supplied.
    if field['frequency_hz'] >= video.fps/2:
        coords = []
    traces = track_locations(video,coords) if coords else []
    reference_trace = traces.pop() if stationary and traces else None
    eligible = []
    for index, trace in zip(np.flatnonzero(track_mask),traces):
        values = trace['d'+field['axis']]
        if reference_trace is not None:
            values = [v-r if v is not None and r is not None else None
                      for v,r in zip(values,reference_trace['d'+field['axis']])]
        fit = harmonic_fit(values,video.fps,field['frequency_hz'])
        if fit and fit['phase_deg'] is not None:
            eligible.append(dict(index=int(index),x=trace['x'],y=trace['y'],u=float(fractions[index]),fit=fit))
    z = np.array([complex(e['fit']['coefficients_px'][0],-e['fit']['coefficients_px'][1]) for e in eligible])
    phi = np.array([shapes[e['index'],anchor] for e in eligible])
    enough = len(eligible) >= 3 and np.sum(phi**2) > .01
    fitted = np.vdot(phi,z)/np.sum(phi**2) if enough else 0j
    score = float(abs(np.vdot(phi,z))**2/max(1e-30,np.sum(phi**2)*np.sum(abs(z)**2))) if enough else None
    amplitude = cfg['amplitude_source_px']
    if amplitude is None:
        if not enough or abs(fitted) < 1e-6:
            raise ValueError('Fewer than three usable string patches support this anchor. Adjust the line/axis or enter an explicit assumed amplitude under Advanced.')
        amplitude = float(abs(fitted))
    # Unit total string mass, peak-normalized sine modes: each modal mass is 1/2.
    frequencies = string_frequencies(field['frequency_hz'],anchor+1,cfg['inharmonicity'])
    modes = [dict(index=i, frequency_hz=float(f), frequency_ratio=float(f/field['frequency_hz']),
                  anchor=i==anchor, modal_mass=.5,
                  thumbnail=np.tile(string_shapes(np.linspace(0,1,25))[:,i],(13,1)).round(4).tolist())
             for i,f in enumerate(frequencies)]
    nodes = [dict(index=i,x=float(p[0]),y=float(p[1]),u=float(fractions[i]),
                  shape=(shapes[i,anchor]*direction).tolist(),modes=shapes[i].tolist()) for i,p in enumerate(positions)]
    xx,yy = np.meshgrid(np.arange(w,dtype=np.float32),np.arange(h,dtype=np.float32))
    s = ((xx-a[0])*tangent[0]+(yy-a[1])*tangent[1])/np.linalg.norm(b-a)
    distance = abs((xx-a[0])*(-tangent[1])+(yy-a[1])*tangent[0])
    alpha = np.clip(cfg['half_width_px']+.5-distance,0,1)*((s>=0)&(s<=1))
    # Reconstruct a static background under only the selected narrow ribbon;
    # compositing its warped alpha lets the string move beyond its old position.
    mask = (alpha>0).astype(np.uint8)*255
    background = cv2.inpaint(video.frames[0],mask,3,cv2.INPAINT_TELEA)
    texture = (video.frames[0].astype(np.float32)-background)*alpha[...,None]
    maps = dict(xx=xx,yy=yy,support=alpha>0,alpha=alpha,
                texture=texture,background=video.frames[0].astype(np.float32)-texture,
                tangent=tangent,length=float(np.linalg.norm(b-a)),projection=direction)
    # A tap near one fifth of the string excites several low harmonics. Avoid
    # starting at an anchor node when only a different cropped span is visible.
    defaults = [n for n in nodes if abs(n['modes'][anchor]) > .1] or nodes
    default_node = min(defaults,key=lambda n:abs(n['u']-.2))['index']
    model = dict(kind='string',frequency_hz=field['frequency_hz'],axis=field['axis'],nodes=nodes,modes=modes,
                 anchor_mode=anchor,default_node=default_node,
                 reference_amplitude_source_px=amplitude, amplitude_basis='user-assumed' if cfg['amplitude_source_px'] is not None else 'complex least-squares fit to original tracked patches',
                 fit_mac=score,fit_samples=len(eligible),measured_samples=eligible,
                 standing_phase_fraction=float(np.sum((z*np.exp(-1j*np.angle(fitted))).real**2)/np.sum(abs(z)**2)) if enough else None,
                 interpolated_support_fraction=float((alpha>0).mean()),string=cfg,projection=direction.tolist(),
                 sample_label='String point',pick_radius_px=max(8,float(np.linalg.norm(b-a))/24),
                 interpretation='Predicted fixed-end string modes anchored to one assumed harmonic; not measured higher modes or a force-calibrated guitar model',
                 assumptions=[
                     'One uniform string under constant tension, small transverse linear motion, immovable transverse supports at u=0 and u=1.',
                     'Anchor harmonic is user-assumed; a single cropped response cannot identify the fundamental or unseen support locations.',
                     'The selected segment maps linearly to its assumed fractions of the full vibrating string; strong perspective is omitted.',
                     'Ideal string frequencies are integer multiples of the fundamental. Optional B adds pinned stiff-string dispersion; it is assumed, not fitted.',
                     'Tension, linear density and physical length are not independently identified; the observed anchor sets the common frequency scale.',
                     'Peak sine shapes have modal mass 0.5 with chosen total mass 1; there is no kg, newton or force calibration.',
                     'Original 31-pixel LK patches overlap and can include neighboring strings or body texture. Patch fits are not isolated-string displacement measurements.',
                     'Amplitude is '+('explicitly user-assumed.' if cfg['amplitude_source_px'] is not None else 'a complex least-squares anchor fit, extrapolated to the full-string antinode.'),
                     'Every retained mode receives the same relative point impulse through its local sine shape; all selected modes share one physical clock.',
                     'Damping is user-assumed and equal in every mode; higher harmonics above camera Nyquist are predictions, never recovered video content.',
                     'Only the selected string ribbon is warped and composited over a locally inpainted static background; occlusion and large display motion can create visual artifacts.',
                     'The guitar body, other strings, fret contact, longitudinal motion and coupling through the bridge are omitted. Eight modes are retained.'])
    return model,maps


def string_frame(video,model,maps,q,gain):
    """Warp actual selected-string texture with an iterated inverse mapping."""
    if gain == 0 or not np.any(q):
        return video.frames[0].copy()
    if 'strings' in model:
        output = maps['background'].copy()
        for child_model, child_maps, indices in maps['strings']:
            output += warped_string_texture(video, child_model, child_maps, q[indices], gain)
        return np.rint(np.clip(output,0,255)).astype(np.uint8)
    foreground = warped_string_texture(video,model,maps,q,gain)
    return np.rint(np.clip(maps['background']+foreground,0,255)).astype(np.uint8)


def warped_string_texture(video,model,maps,q,gain):
    if gain == 0 or not np.any(q):
        return maps['texture']
    cfg = model['string'];a = np.array(cfg['endpoints'][0]);tangent = maps['tangent']
    sx,sy = maps['xx'].copy(),maps['yy'].copy()
    for _ in range(4):
        s = ((sx-a[0])*tangent[0]+(sy-a[1])*tangent[1])/maps['length']
        u = cfg['span_start']+s*(cfg['span_end']-cfg['span_start'])
        displacement = np.sum(string_shapes(u)*q,axis=-1)*gain
        # Continue the analytic shape just beyond the marked crop so inverse
        # mapping stays continuous; the warped source alpha bounds the ribbon.
        sx = (maps['xx']-displacement*maps['projection'][0]/video.metadata['scale_x']).astype(np.float32)
        sy = (maps['yy']-displacement*maps['projection'][1]/video.metadata['scale_y']).astype(np.float32)
    return cv2.remap(maps['texture'],sx,sy,cv2.INTER_LINEAR,borderMode=cv2.BORDER_CONSTANT)


def build_string_ensemble(video, field, cfg, measurement_settings=None):
    """Independent strings, block-diagonal modes, simultaneous relative taps.

    Each string keeps its own fitted/assumed scale. A shared fractional pluck
    position does not imply one calibrated physical impulse or bridge coupling.
    """
    children = []
    for i, entry in enumerate(cfg['strings']):
        if not entry['enabled']:
            continue
        try:
            child, maps = build_string_model(video, dict(field,frequency_hz=entry['anchor_hz'] or field['frequency_hz']), entry, measurement_settings)
        except ValueError as exc:
            raise ValueError(f"{entry['name']}: {exc}") from None
        children.append((i, entry, child, maps))
    count = 8*len(children)
    modes, nodes, summaries, renderers = [], [], [], []
    for ordinal, (index, entry, child, maps) in enumerate(children):
        offset = ordinal*8
        indices = list(range(offset, offset+8))
        for mode in child['modes']:
            modes.append(dict(mode,index=offset+mode['index'],string_index=index,string_name=entry['name'],
                              harmonic=mode['index']+1,reference_amplitude_source_px=child['reference_amplitude_source_px'],
                              anchor_frequency_hz=child['frequency_hz']))
        for node in child['nodes']:
            basis = [0.]*count
            basis[offset:offset+8] = node['modes']
            nodes.append(dict(node,index=index*25+node['index'],local_index=node['index'],string_index=index,
                              label=f"{entry['name']} · point {node['index']+1}",modes=basis))
        summaries.append(dict(index=index,name=entry['name'],mode_indices=indices,
                              anchor_mode=offset+child['anchor_mode'],frequency_hz=child['frequency_hz'],
                              reference_amplitude_source_px=child['reference_amplitude_source_px'],
                              amplitude_basis=child['amplitude_basis'],fit_samples=child['fit_samples'],fit_mac=child['fit_mac'],
                              measured_samples=child['measured_samples'],
                              geometry=child['string'],projection=child['projection']))
        renderers.append((child,maps,indices))
    # Allocate overlapping ribbon residuals once, independent of draw order.
    # Disabled strings never enter the background reconstruction or the warp.
    alpha_sum = sum(maps['alpha'] for _,_,_,maps in children)
    mask = (alpha_sum > 0).astype(np.uint8)*255
    original = video.frames[0].astype(np.float32)
    residual = original-cv2.inpaint(video.frames[0],mask,3,cv2.INPAINT_TELEA)
    background = original.copy()
    for _,maps,_ in renderers:
        maps['texture'] = residual*maps['alpha'][...,None]/np.maximum(1,alpha_sum)[...,None]
        background -= maps['texture']
    first = children[0][2]
    model = dict(first, string=cfg, strings=summaries, modes=modes, nodes=nodes,
                 frequency_hz=min(s['frequency_hz'] for s in summaries),
                 default_node=children[0][0]*25+first['default_node'],
                 sample_label='String point',
                 interpretation='Predicted independent string ensemble with simultaneous relative plucks; not measured higher modes or a coupled guitar model',
                 assumptions=[
                     'Each selected string has independent fixed-end sine modes and chosen total mass 1; the combined matrices are block diagonal.',
                     'Every enabled string is plucked simultaneously at the same full-string fraction, including when that position is outside its visible crop.',
                     'The shared strength scales separately fitted or user-assumed amplitudes and anchor frequencies; equal relative taps do not imply equal calibrated forces.',
                     'Per-string anchor frequency and harmonic index are user choices. Blank frequency follows the selected measured response; no guitar tuning is inferred.',
                     'Anchors at or above camera Nyquist require an explicit assumed amplitude and are never fitted to aliased video samples.',
                     'All active harmonics share simulation time, damping ratio and playback slowdown; mode animation isolates the selected string harmonic.',
                     'Bridge/body coupling, energy transfer between strings, strum delay and collisions are omitted.',
                     'Eight harmonics are retained per enabled string; each string has its own fitted or explicit assumed amplitude scale.',
                     'Overlapping ribbons share the reconstructed texture residual; close or crossing strings and large gains can produce compositing artifacts.',
                 ]+[first['assumptions'][i] for i in (0,1,2,3,4,5,6,9)])
    return model,dict(strings=renderers,background=background,support=alpha_sum>0)
