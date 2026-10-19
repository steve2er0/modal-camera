"""PSD selection geometry and quality labels for reference-frame sample centers."""
import math
from .response import sample_grid


def sampling_plan(video, settings):
    source = settings.get('spectrum_source', 'auto')
    region = None
    if source == 'point':
        coordinates = [settings['spectrum_point']]
        candidates, _ = sample_grid(video)
        if coordinates[0] not in candidates:
            candidates.append(coordinates[0])
        mode, label, spatial = 'point', 'One point', False
    elif source == 'auto' and settings['points']:
        coordinates = candidates = settings['points']
        mode, label, spatial = 'points', 'Advanced measurement points', False
    else:
        region = settings['spectrum_region'] if source == 'region' else settings['roi'] if source == 'auto' else None
        coordinates, _ = sample_grid(video, region, contained=source == 'region')
        candidates = coordinates
        mode, label, spatial = ('region', 'Selected region', True) if region else ('frame', 'Whole-frame grid', True)
    return dict(mode=mode, label=label, coordinates=coordinates, candidates=candidates,
                region=region, spatial=spatial)


def sampling_payload(video, settings, plan, traces):
    active = {tuple(p) for p in plan['coordinates']}
    reference = tuple(settings['points'][-1]) if settings['reference_last'] and len(settings['points']) >= 2 else None
    stationary = traces.get(reference) if reference else None
    candidates = list(plan['candidates'])
    if reference and list(reference) not in candidates:
        candidates.append(list(reference))
    samples = []
    for i, position in enumerate(candidates):
        key = tuple(position)
        trace = traces.get(key)
        is_reference = key == reference
        selected = key in active and not (is_reference and plan['mode'] == 'points')
        eligible = None
        if trace is not None and (reference is None or stationary is not None):
            values = trace['d'+settings['axis']]
            other = stationary['d'+settings['axis']] if stationary is not None else values
            eligible = len(values) == len(video.frames) and all(
                a is not None and b is not None and math.isfinite(a) and math.isfinite(b)
                for a, b in zip(values, other))
        label = 'Camera reference' if is_reference else f'P{i+1}' if plan['mode'] == 'points' else f'Sample {i+1}'
        samples.append(dict(index=i, label=label, x=position[0], y=position[1],
                            selected=selected, eligible=eligible, used=selected and eligible is True,
                            reference=is_reference))
    return dict(mode=plan['mode'], label=plan['label'], region=plan['region'], samples=samples,
                reference_frame=0, patch_width_analysis_px=31,
                accepted_count=sum(s['used'] for s in samples), selected_count=sum(s['selected'] for s in samples),
                note='Dots show reference-frame patch centers. PSD requires complete quality-accepted tracks. Region selection contains the reference tracking windows; it is not object segmentation.')
