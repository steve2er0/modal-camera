"""Observed standing shapes and predicted modal image-plane sandboxes.

Project the observed complex operating response onto a common real axis. The
result is a standing-mode approximation. Predicted plate and string bases use
consistent modal masses and a shared impulse; no force calibration or kg implied.
"""
import math

import cv2
import numpy as np

from .response import interpolate_field
from .plate_modes import validate_plate_settings
from .string_modes import validate_string_settings, string_frame


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
    if 'model_source' in data or 'plate' in data or 'string' in data:
        result['model_source'] = data.get('model_source', 'observed')
        if result['model_source'] not in ('observed', 'plate', 'string'):
            raise ValueError('Choose an observed response, predicted plate, or tensioned string.')
        result['plate'] = validate_plate_settings(data.get('plate', {}))
        if 'string' in data or result['model_source'] == 'string':
            result['string'] = validate_string_settings(data.get('string', {}))
        result['motion'] = data.get('motion', 'tap')
        if result['motion'] not in ('tap', 'mode'):
            raise ValueError('Choose a combined tap or a single mode animation.')
        result['enabled_modes'] = data.get('enabled_modes')
        mode_limit = 48 if result['model_source'] == 'string' else 8
        if result['enabled_modes'] is not None:
            modes = result['enabled_modes']
            if (not isinstance(modes, list) or not 1 <= len(modes) <= mode_limit
                    or any(type(i) is not int or not 0 <= i < mode_limit for i in modes) or len(set(modes)) != len(modes)):
                raise ValueError('Enable at least one valid predicted mode.')
        result['solo_mode'] = data.get('solo_mode')
        if result['solo_mode'] is not None and (type(result['solo_mode']) is not int or not 0 <= result['solo_mode'] < mode_limit):
            raise ValueError('Choose a valid predicted mode to animate.')
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
        if model.get('strings'):
            a_node = valid[settings['probe_a']]
            other_strings = [n for n in other if n['string_index'] != a_node['string_index']]
            if other_strings:
                settings['probe_b'] = min(other_strings,key=lambda n:abs(n['u']-a_node['u']))['index']
        elif model.get('kind') == 'string' and not opposite:
            target = model['string']['span_start']+.25*(model['string']['span_end']-model['string']['span_start'])
            settings['probe_b'] = min(other,key=lambda n:abs(n['u']-target))['index']
    settings['participation'] = valid[settings['tap_node']]['shape'][component]
    if model.get('kind') in ('plate','string'):
        kind = model['kind']
        settings.update(model_source=kind, **{kind:model[kind]})
        settings.setdefault('motion', 'tap')
        defaults = ([i for s in model['strings'] for i in range(s['anchor_mode'],min(s['mode_indices'][-1]+1,s['anchor_mode']+3))]
                    if model.get('strings') else list(range(model['anchor_mode'], min(8, model['anchor_mode']+4))))
        settings['enabled_modes'] = settings.get('enabled_modes') or defaults
        settings['solo_mode'] = model['anchor_mode'] if settings.get('solo_mode') is None else settings['solo_mode']
        if any(i >= len(model['modes']) for i in settings['enabled_modes']+[settings['solo_mode']]):
            raise ValueError('These mode selections belong to a different string model. Regenerate the modes.')
        if model.get('strings'):
            settings['tap_fraction'] = valid[settings['tap_node']]['u']
        settings['active_modes'] = [settings['solo_mode']] if settings['motion'] == 'mode' else settings['enabled_modes']
        settings['clock_hz'] = model['modes'][settings['solo_mode']]['frequency_hz'] if settings['motion'] == 'mode' else model['frequency_hz']
        settings['max_frequency_hz'] = max(model['modes'][i]['frequency_hz'] for i in settings['active_modes'])
        # At least 15 exported frames per cycle of the highest selected mode;
        # all modes slow down together, preserving their physical frequency ratios.
        settings['effective_display_cps'] = min(settings['display_cps'], 2*settings['clock_hz']/settings['max_frequency_hz'])
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
    if model.get('kind') in ('plate','string'):
        return simulate_plate(model, settings)
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
    if not math.isfinite(time_s) or not 0 <= time_s <= settings['cycles']/settings.get('clock_hz', model['frequency_hz']) + 1e-9:
        raise ValueError('Virtual tap time is outside the simulation.')
    if not math.isfinite(gain) or not 0 <= gain <= 20:
        raise ValueError('Virtual tap display gain must be between 0 and 20.')
    if model.get('kind') == 'string':
        return string_frame(video,model,maps,plate_coordinates(model,settings,time_s),gain)
    if model.get('kind') == 'plate':
        q = plate_coordinates(model, settings, time_s)
        displacement = np.sum(maps['modes']*q[None, None, :], axis=2)
        dx = displacement*maps['projection'][0]/video.metadata['scale_x']
        dy = displacement*maps['projection'][1]/video.metadata['scale_y']
    else:
        q = float(oscillator(model, settings, time_s))
        coeff = maps['coefficients']
        dx = coeff[:, :, 0]*q/video.metadata['scale_x']
        dy = coeff[:, :, 2]*q/video.metadata['scale_y']
    return cv2.remap(video.frames[0], (maps['xx']-gain*dx).astype(np.float32),
                     (maps['yy']-gain*dy).astype(np.float32), cv2.INTER_LINEAR,
                     borderMode=cv2.BORDER_REFLECT_101)


def tap_display_frame(video, model, maps, settings, time_s, gain=10.):
    rgb = tap_frame(video,model,maps,settings,time_s,gain)
    if model.get('kind') == 'string':
        q = plate_coordinates(model,settings,time_s)
        groups = model.get('strings') or [dict(index=None,projection=maps['projection'])]
        for group in groups:
            points = []
            for node in model['nodes']:
                if node.get('string_index') != group['index']:
                    continue
                displacement = float(np.dot(node['modes'],q))*gain
                points.append((round(node['x']+displacement*group['projection'][0]/video.metadata['scale_x']),
                               round(node['y']+displacement*group['projection'][1]/video.metadata['scale_y'])))
            cv2.polylines(rgb,[np.array(points,np.int32)],False,(54,207,238),1,cv2.LINE_AA)
            if model.get('strings') and settings['motion'] == 'tap':
                cfg = group['geometry']; u = settings['tap_fraction']
                if cfg['span_start'] <= u <= cfg['span_end']:
                    s = (u-cfg['span_start'])/(cfg['span_end']-cfg['span_start'])
                    a,b = np.array(cfg['endpoints'])
                    point = tuple(np.rint(a+s*(b-a)).astype(int))
                    cv2.putText(rgb,'T',point,cv2.FONT_HERSHEY_SIMPLEX,.35,(255,201,134),1,cv2.LINE_AA)
    if model.get('kind') == 'plate':
        # A light signed overlay makes nodes/lobes readable while the actual
        # grid texture moves under it. Zero displacement leaves the texture alone.
        q = plate_coordinates(model, settings, time_s)
        displacement = np.sum(maps['modes']*q[None, None, :], axis=2)
        alpha = np.clip(abs(displacement)/max(model['reference_amplitude_source_px'], 1e-8), 0, 1)*.18
        colors = np.where((displacement >= 0)[..., None], [255, 201, 134], [54, 160, 238])
        rgb = np.rint(rgb*(1-alpha[..., None])+colors*alpha[..., None]).astype(np.uint8)
        cv2.polylines(rgb, [np.array(model['plate']['corners'], np.int32)], True, (54,207,238), 1, cv2.LINE_AA)
    for node in model['nodes']:
        if node['shape'] is not None:
            cv2.circle(rgb,(round(node['x']),round(node['y'])),1,(100,133,148),-1)
    nodes = {n['index']:n for n in model['nodes']}
    for label,key,color in [('T','tap_node',(255,201,134)),('A','probe_a',(54,207,238)),('B','probe_b',(255,201,134))]:
        if label == 'T' and model.get('kind') in ('plate','string') and settings['motion'] == 'mode':
            continue
        node = nodes[settings[key]]
        p = (round(node['x']),round(node['y']))
        cv2.circle(rgb,p,5 if label=='T' else 3,color,1,cv2.LINE_AA)
        cv2.putText(rgb,label,(p[0]+6,p[1]+(10 if label=='T' else -4)),cv2.FONT_HERSHEY_SIMPLEX,.3,color,1,cv2.LINE_AA)
    return rgb


def plate_coordinates(model, settings, time_s):
    """Shared modal impulse for plate and string; peak-normalized masses."""
    t = np.asarray(time_s)
    result = np.zeros((len(model['modes']),)+t.shape)
    reference = model['reference_amplitude_source_px']
    nodes = {n['index']: n for n in model['nodes']}
    anchor = model['modes'][model['anchor_mode']]
    impulse = (settings['strength']*settings['direction']*2*math.pi*model['frequency_hz']
               *reference*anchor['modal_mass'])
    zeta = settings['damping_percent']/100
    for i in settings['active_modes']:
        mode = model['modes'][i]
        reference = mode.get('reference_amplitude_source_px',model['reference_amplitude_source_px'])
        omega = 2*math.pi*mode['frequency_hz']
        if settings['motion'] == 'mode':
            result[i] = settings['strength']*settings['direction']*reference*np.sin(omega*t)
        else:
            wd = omega*math.sqrt(1-zeta*zeta)
            if model.get('strings'):
                local_impulse = settings['strength']*settings['direction']*2*math.pi*mode['anchor_frequency_hz']*reference*.5
                participation = math.sin(mode['harmonic']*math.pi*settings['tap_fraction'])
            else:
                local_impulse = impulse
                participation = nodes[settings['tap_node']]['modes'][i]
            velocity = local_impulse*participation/mode['modal_mass']
            result[i] = velocity/wd*np.exp(-zeta*omega*t)*np.sin(wd*t)
    return result


def simulate_plate(model, settings):
    clock = settings['clock_hz']
    duration = settings['cycles']/clock
    samples = math.ceil(duration*settings['max_frequency_hz']*24)+1
    if samples > 60000:
        raise ValueError('This mode range needs too many trace samples. Shorten the simulation or enable fewer higher modes.')
    t = np.linspace(0, duration, samples)
    q = plate_coordinates(model, settings, t)
    nodes = {n['index']: n for n in model['nodes']}
    component = 0 if model['axis'] == 'x' else 1
    traces = []
    for label, key in [('A', 'probe_a'), ('B', 'probe_b')]:
        node = nodes[settings[key]]
        contributions = q*np.array(node['modes'])[:, None]*model['projection'][component]
        traces.append(dict(label=label, node=node['index'], x=node['x'], y=node['y'],
                           sample=node.get('label',f"{model.get('sample_label','Grid')} {node['index']+1}"),
                           string_index=node.get('string_index'),
                           displacement_source_px=contributions.sum(axis=0).tolist()))
    masses = np.array([m['modal_mass'] for m in model['modes']])
    omega = 2*math.pi*np.array([m['frequency_hz'] for m in model['modes']])
    zeta = settings['damping_percent']/100
    return dict(model=model, settings=settings, time_s=t.tolist(), traces=traces,
                clock_hz=clock, duration_s=duration,
                display_duration_s=settings['cycles']/settings['effective_display_cps'],
                playback_slowdown=clock/settings['effective_display_cps'],
                seconds_to_ten_percent=math.log(10)/(zeta*2*math.pi*min(model['modes'][i]['frequency_hz'] for i in settings['active_modes'])),
                normalized_matrices=dict(M=np.diag(masses).tolist(), C=np.diag(2*zeta*omega*masses).tolist(),
                                         K=np.diag(omega**2*masses).tolist(), units=('Chosen total mass = 1 per independent string; ' if model.get('kind') == 'string' else 'Chosen total plate mass = 1; uniform areal density; ')+'peak-normalized shapes; no kg, N/m or force calibration'),
                units='Model-predicted source-pixel projection; relative impulse; display gain excluded')
