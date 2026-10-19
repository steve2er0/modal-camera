"""An assumed, one-mode image-plane sandbox, never modal identification.

Project the observed complex operating response onto a common real axis. The
result is a standing-mode approximation. Its oscillator has chosen unit modal
mass and relative impulse scaling; no force calibration or kg are implied.
"""
import math

import cv2
import numpy as np

from .response import interpolate_field


def validate_tap_settings(data):
    if not isinstance(data, dict):
        raise ValueError('Virtual tap settings must be an object.')
    result = {}
    for key, default, low, high in [('damping_percent', 1., .1, 5.),
                                   ('strength', 1., 0., 5.), ('direction', 1., -1., 1.),
                                   ('cycles', 40., 5., 60.), ('display_cps', 2., 1., 5.),
                                   ('cursor_cycle', 0., 0., 60.)]:
        try:
            value = float(data.get(key, default))
        except (TypeError, ValueError):
            raise ValueError(f'Virtual tap {key} must be a finite number.') from None
        if not math.isfinite(value) or not low <= value <= high:
            raise ValueError(f'Virtual tap {key} must be between {low} and {high}.')
        result[key] = value
    if result['direction'] not in (-1, 1):
        raise ValueError('Virtual tap direction must be +1 or -1 along the selected image axis.')
    result['cursor_cycle'] = min(result['cursor_cycle'], result['cycles'])
    for key in ('tap_node', 'probe_a', 'probe_b'):
        value = data.get(key)
        if value is not None and (isinstance(value, bool) or not isinstance(value, int) or not 0 <= value < 256):
            raise ValueError('Choose a valid virtual tap sample index.')
        result[key] = value
    return result


def build_model(video, field):
    axis = field['axis']
    eligible = [n for n in field['nodes'] if n['fit']['x'] and n['fit']['y']
                and n['fit'][axis]['phase_deg'] is not None]
    if len(eligible) < 4:
        raise ValueError('Virtual tap needs at least four usable displacement patches. Analyze a textured region first.')
    z = np.array([complex(n['fit'][axis]['coefficients_px'][0],
                          -n['fit'][axis]['coefficients_px'][1]) for n in eligible])
    orientation = .5 * np.angle(np.sum(z*z))
    if (z[np.argmax(np.abs(z))] * np.exp(-1j*orientation)).real < 0:
        orientation += math.pi
    projected = (z * np.exp(-1j*orientation)).real
    maximum = float(np.max(np.abs(projected)))
    if maximum < 1e-8:
        raise ValueError('No measurable standing response is available for virtual tap.')
    eligible_ids = {n['index'] for n in eligible}
    nodes, projected_nodes = [], []
    for node in field['nodes']:
        fit, shape = {}, None
        if node['index'] in eligible_ids:
            shape = []
            for component in ('x', 'y'):
                a, b = node['fit'][component]['coefficients_px']
                value = float((a*math.cos(orientation)-b*math.sin(orientation))/maximum)
                shape.append(value)
                fit[component] = dict(coefficients_px=[value, 0.], phase_deg=0.)
        else:
            fit = dict(x=None, y=None)
        nodes.append(dict(index=node['index'], x=node['x'], y=node['y'], shape=shape))
        projected_nodes.append(dict(index=node['index'], fit=fit))
    maps = interpolate_field(video, dict(grid=field['grid'], nodes=projected_nodes))
    if not maps['support'].any():
        raise ValueError('Virtual tap needs a cell with four usable neighboring patches; this map has no supported cells.')
    valid = [n for n in nodes if n['shape'] is not None]
    default = max(valid, key=lambda n: abs(n['shape'][0 if axis == 'x' else 1]))['index']
    reference = max(n['fit'][axis]['amplitude_peak_px'] for n in eligible)
    fraction = float(np.sum(projected**2)/np.sum(np.abs(z)**2))
    model = dict(frequency_hz=field['frequency_hz'], axis=axis, nodes=nodes, default_node=default,
                 reference_amplitude_source_px=reference, standing_phase_fraction=fraction,
                 projection_rotation_deg=float(np.rad2deg(orientation)),
                 interpolated_support_fraction=float(maps['support'].mean()),
                 interpretation='Assumed single standing mode from an observed operating response; not an identified eigenmode or force-calibrated twin',
                 assumptions=[
                     'The selected response frequency is assumed to be a natural frequency.',
                     'A common-phase real projection approximates one standing mode; quadrature motion is omitted.',
                     'Damping is user-assumed, not estimated from this video.',
                     'Modal mass is normalized to 1, with no kilogram or force calibration.',
                     'Relative impulse sets initial modal velocity to strength × direction × tap participation × omega × reference amplitude.',
                     'Small linear motion, unchanged supports, one retained mode and camera-plane projection.',
                     'Unsupported image cells remain unwarped; sample traces describe the model at measured patch centers.',
                     'Playback slowdown and display gain do not change simulation time or trace values.'])
    return model, maps


def configure(model, data):
    settings = validate_tap_settings(data)
    valid = {n['index']: n for n in model['nodes'] if n['shape'] is not None}
    for key in ('tap_node', 'probe_a', 'probe_b'):
        if settings[key] is not None and settings[key] not in valid:
            raise ValueError('This patch has no usable virtual tap shape. Choose a supported sample.')
    settings['tap_node'] = model['default_node'] if settings['tap_node'] is None else settings['tap_node']
    settings['probe_a'] = settings['tap_node'] if settings['probe_a'] is None else settings['probe_a']
    component = 0 if model['axis'] == 'x' else 1
    if settings['probe_b'] is None:
        a = valid[settings['probe_a']]['shape'][component]
        other = [n for n in valid.values() if n['index'] != settings['probe_a']]
        opposite = [n for n in other if n['shape'][component]*a < 0]
        settings['probe_b'] = max(opposite or other, key=lambda n: abs(n['shape'][component]))['index']
    settings['participation'] = valid[settings['tap_node']]['shape'][component]
    return settings


def oscillator(model, settings, time_s):
    """Exact underdamped free response after an instantaneous velocity jump."""
    omega = 2*math.pi*model['frequency_hz']
    zeta = settings['damping_percent']/100
    wd = omega*math.sqrt(1-zeta*zeta)
    velocity = (settings['strength']*settings['direction']*settings['participation']
                *omega*model['reference_amplitude_source_px'])
    t = np.asarray(time_s)
    return velocity/wd*np.exp(-zeta*omega*t)*np.sin(wd*t)


def simulate(model, data):
    settings = configure(model, data)
    f = model['frequency_hz']
    t = np.linspace(0, settings['cycles']/f, math.ceil(settings['cycles']*24)+1)
    q = oscillator(model, settings, t)
    component = 0 if model['axis'] == 'x' else 1
    nodes = {n['index']: n for n in model['nodes']}
    traces = []
    for label, key in [('A', 'probe_a'), ('B', 'probe_b')]:
        node = nodes[settings[key]]
        traces.append(dict(label=label, node=node['index'], x=node['x'], y=node['y'],
                           displacement_source_px=(q*node['shape'][component]).tolist()))
    omega, zeta = 2*math.pi*f, settings['damping_percent']/100
    return dict(model=model, settings=settings, time_s=t.tolist(), traces=traces,
                duration_s=settings['cycles']/f, display_duration_s=settings['cycles']/settings['display_cps'],
                seconds_to_ten_percent=math.log(10)/(zeta*omega),
                normalized_matrices=dict(M=[[1.]], C=[[2*zeta*omega]], K=[[omega**2]],
                                         units='Chosen modal normalization; no kg, N/m or force calibration'),
                units='Simulated source pixels; relative impulse; display gain excluded')


def tap_frame(video, model, maps, settings, time_s, gain=10.):
    if not math.isfinite(time_s) or not 0 <= time_s <= settings['cycles']/model['frequency_hz'] + 1e-9:
        raise ValueError('Virtual tap time is outside the simulation.')
    if not math.isfinite(gain) or not 0 <= gain <= 20:
        raise ValueError('Virtual tap display gain must be between 0 and 20.')
    q = float(oscillator(model, settings, time_s))
    coeff = maps['coefficients']
    dx = coeff[:, :, 0]*q/video.metadata['scale_x']
    dy = coeff[:, :, 2]*q/video.metadata['scale_y']
    return cv2.remap(video.frames[0], (maps['xx']-gain*dx).astype(np.float32),
                     (maps['yy']-gain*dy).astype(np.float32), cv2.INTER_LINEAR,
                     borderMode=cv2.BORDER_REFLECT_101)


def tap_display_frame(video, model, maps, settings, time_s, gain=10.):
    rgb = tap_frame(video,model,maps,settings,time_s,gain)
    for node in model['nodes']:
        if node['shape'] is not None:
            cv2.circle(rgb,(round(node['x']),round(node['y'])),1,(100,133,148),-1)
    nodes = {n['index']:n for n in model['nodes']}
    for label,key,color in [('T','tap_node',(255,201,134)),('A','probe_a',(54,207,238)),('B','probe_b',(255,201,134))]:
        node = nodes[settings[key]]
        p = (round(node['x']),round(node['y']))
        cv2.circle(rgb,p,5 if label=='T' else 3,color,1,cv2.LINE_AA)
        cv2.putText(rgb,label,(p[0]+6,p[1]+(10 if label=='T' else -4)),cv2.FONT_HERSHEY_SIMPLEX,.3,color,1,cv2.LINE_AA)
    return rgb
