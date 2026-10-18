"""Validated clip settings and the dependencies of each computed result."""
import math


def number(value, name):
    try:
        result = float(value)
    except (TypeError, ValueError):
        raise ValueError(f'{name} must be a finite number.')
    if not math.isfinite(result):
        raise ValueError(f'{name} must be a finite number.')
    return result


def defaults(demo=False):
    return dict(frequency=3. if demo else 95., bandwidth=1. if demo else 4., linked=True,
                low=2.5 if demo else 93., high=3.5 if demo else 97., gain=4., axis='y',
                points=[[90,94],[230,94]] if demo else [], roi=None, reference='auto',
                reference_last=False, calibration=None)


def validate_settings(settings, video):
    result = dict(settings)
    for key in ('frequency','bandwidth','low','high','gain'):
        result[key] = number(result.get(key),key.capitalize())
    if result['frequency'] <= 0 or result['bandwidth'] <= 0:
        raise ValueError('Target frequency and bandwidth must be above zero.')
    if not 0 <= result['gain'] <= 20:
        raise ValueError('Added motion gain must be between 0 and 20.')
    if result.get('axis') not in ('x','y') or result.get('reference') not in ('auto','p1','strongest'):
        raise ValueError('Choose a valid displacement axis and phase reference.')
    for key in ('linked','reference_last'):
        if not isinstance(result.get(key),bool):
            raise ValueError(f'{key} must be true or false.')
    if result['linked']:
        result['low'] = result['frequency']-result['bandwidth']/2
        result['high'] = result['frequency']+result['bandwidth']/2
    calibration = result.get('calibration')
    result['calibration'] = None if calibration in (None,'') else number(calibration,'Calibration')
    if result['calibration'] is not None and result['calibration'] <= 0:
        raise ValueError('Calibration must be positive, or blank for source pixels.')
    points = result.get('points')
    if not isinstance(points,list) or len(points)>8:
        raise ValueError('Select up to eight points.')
    width,height = video.metadata['width'],video.metadata['height']
    checked = []
    for point in points:
        if not isinstance(point,list) or len(point)!=2:
            raise ValueError('Each point must contain x and y coordinates.')
        x,y = [number(v,'Point coordinate') for v in point]
        if not 16 <= x < width-16 or not 16 <= y < height-16:
            raise ValueError('Points must be at least 16 analysis pixels from the image edges.')
        checked.append([x,y])
    result['points'] = checked
    roi = result.get('roi')
    if roi is not None:
        if not isinstance(roi,list) or len(roi)!=4:
            raise ValueError('ROI must have x, y, width and height.')
        x,y,w,h = [number(v,'ROI coordinate') for v in roi]
        if min(x,y)<0 or min(w,h)<8 or x+w>width or y+h>height:
            raise ValueError('ROI must be inside the image and at least 8 by 8 analysis pixels.')
        result['roi'] = [x,y,w,h]
    return {key:result[key] for key in defaults()}


def signature(settings, kind):
    keys = dict(analysis=('frequency','axis','points','reference_last'),
                field=('frequency','axis','points','reference_last','roi','reference'),
                render=('low','high','gain','roi'))[kind]
    return {key:settings[key] for key in keys}


def validate_ui(data, frame_count):
    if not isinstance(data,dict):
        raise ValueError('Display settings must be an object.')
    result = dict(data)
    if result.get('view','heatmap') not in ('amplified','heatmap','isolated','amplitude','phase','modal'):
        raise ValueError('Choose a valid response view.')
    for key,default,lower,upper in [('sensitivity',85,0,100),('modal_gain',10,0,20),
                                   ('phase',0,0,360),('frame',0,0,frame_count-1)]:
        result[key] = number(result.get(key,default),key)
        if not lower <= result[key] <= upper:
            raise ValueError(f'{key} must be between {lower} and {upper}.')
    if result.get('timing_mode','') not in ('','encoded','capture'):
        raise ValueError('Choose encoded playback timing or a capture-rate assumption.')
    return dict(view=result.get('view','heatmap'),timing_mode=result.get('timing_mode',''),
                timing_confirmed=result.get('timing_confirmed') is True,
                sensitivity=result['sensitivity'],modal_gain=result['modal_gain'],
                phase=result['phase'],frame=int(result['frame']))
