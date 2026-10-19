"""Local, annotated H.264 exports of the displayed frequency response.

Recorded views keep every encoded frame at the encoded playback rate. Modal
exports synthesize four 1 Hz display cycles; they are not real-time motion.
"""
import json
import math
from pathlib import Path
import subprocess
from tempfile import TemporaryFile
from threading import Timer

import cv2
import numpy as np

from .response import modal_frame
from .virtual_tap import tap_display_frame

VIEWS = {'heatmap', 'isolated', 'modal', 'tap'}
BACKGROUND = np.array([8, 13, 19], dtype=np.float32)
MODAL_FPS = 30
MODAL_CYCLES = 4


def visibility(value, sensitivity):
    threshold = (1 - sensitivity / 100) * .75
    blend = np.clip((np.asarray(value) - threshold) / .12, 0, 1)
    return blend * blend * (3 - 2 * blend)


def response_layers(response_display, sensitivity):
    """Match the browser's quantized response map, colors and soft threshold."""
    value = response_display.astype(np.float32) / 255
    alpha = np.rint(visibility(value, sensitivity) * 255)
    low, middle, high = [np.array(c) for c in ([36, 73, 123], [69, 204, 186], [255, 191, 102])]
    color = np.where((value < .5)[..., None],
                     low + (middle - low) * (value * 2)[..., None],
                     middle + (high - middle) * ((value - .5) * 2)[..., None])
    return np.floor(color + .5), np.rint(alpha * .85)[..., None] / 255, alpha[..., None] / 255


def band_frame(original, amplified, layers, view):
    color, heat_alpha, mask_alpha = layers
    if view == 'heatmap':
        base = original.astype(np.float32) * .5 + BACKGROUND * .5
        rgb = base * (1 - heat_alpha) + color * heat_alpha
    else:
        rgb = amplified.astype(np.float32) * mask_alpha + BACKGROUND * (1 - mask_alpha)
    return np.rint(np.clip(rgb, 0, 255)).astype(np.uint8)


def modal_display_frame(video, field, maps, phase, gain, sensitivity):
    threshold = (1 - sensitivity / 100) * .75
    rgb = modal_frame(video, field, maps, phase, gain, threshold)
    rgb = np.rint(rgb.astype(np.float32) * .85 + BACKGROUND * .15).astype(np.uint8)
    theta = math.radians(phase - field['reference']['phase_deg'])
    maximum = max(field['amplitude_display_max_px'], 1e-9)
    for node in field['nodes']:
        x, y = int(round(node['x'])), int(round(node['y']))
        amplitude = node['amplitude_peak_px']
        if amplitude is None:
            cv2.line(rgb, (x-3, y-3), (x+3, y+3), (135, 151, 163), 1, cv2.LINE_AA)
            cv2.line(rgb, (x+3, y-3), (x-3, y+3), (135, 151, 163), 1, cv2.LINE_AA)
            continue
        alpha = float(visibility(amplitude / maximum, sensitivity))
        if alpha <= 0:
            continue
        xf, yf = node['fit']['x'], node['fit']['y']
        if not xf or not yf or (xf['phase_deg'] is None and yf['phase_deg'] is None):
            cv2.rectangle(rgb, (x-2, y-2), (x+2, y+2), (135, 151, 163), 1)
            continue
        motion = lambda fit: fit['coefficients_px'][0]*math.cos(theta) + fit['coefficients_px'][1]*math.sin(theta)
        end = (int(round(x + motion(xf)/video.metadata['scale_x']*gain)),
               int(round(y + motion(yf)/video.metadata['scale_y']*gain)))
        color = (255, 189, 126) if motion(node['fit'][field['axis']]) >= 0 else (130, 182, 244)
        overlay = rgb.copy()
        cv2.arrowedLine(overlay, (x, y), end, color, 1, cv2.LINE_AA, tipLength=.25)
        cv2.circle(overlay, end, 2, color, -1, cv2.LINE_AA)
        cv2.addWeighted(overlay, max(.25, alpha), rgb, 1-max(.25, alpha), 0, dst=rgb)
    return rgb


def export_metadata(video, view, sensitivity, modal_gain, phase_start, render_info=None, field=None, tap=None):
    if view not in VIEWS:
        raise ValueError('Choose heatmap, isolated, modal or virtual tap video export.')
    if not math.isfinite(sensitivity) or not 0 <= sensitivity <= 100:
        raise ValueError('Sensitivity must be between 0 and 100.')
    if not math.isfinite(modal_gain) or not 0 <= modal_gain <= 20:
        raise ValueError('Modal gain must be between 0 and 20.')
    if not math.isfinite(phase_start):
        raise ValueError('Start phase must be finite.')
    modal = view == 'modal'
    if modal and (field is None or field['reference']['phase_deg'] is None):
        raise ValueError('Build a displacement map with a usable phase reference before exporting modal animation.')
    if view == 'tap' and tap is None:
        raise ValueError('Prepare a virtual tap simulation before exporting it.')
    if not modal and view != 'tap' and render_info is None:
        raise ValueError('Apply the selected band before exporting heatmap or isolated video.')
    fps = MODAL_FPS if modal or view == 'tap' else video.encoded_fps or video.fps
    count = MODAL_FPS * MODAL_CYCLES if modal else len(video.frames)
    result = dict(view=view, sensitivity=sensitivity, analysis_fps=video.fps,
                  encoded_fps=video.encoded_fps or video.fps, timing_basis=video.timing_basis,
                  export_fps=fps, export_frames=count, export_duration_s=count/fps,
                  codec='H.264 / yuv420p', audio=False,
                  resolution='Analysis image scaled to fit 640 x 480, with separate annotations')
    if view == 'tap':
        config, model = tap['settings'], tap['model']
        count = math.ceil(tap['display_duration_s']*fps)+1
        if count > 5401:
            raise ValueError('This slowed export exceeds three minutes. Shorten the simulation under Advanced or enable fewer high modes.')
        # Keep the MP4 comment compact; dense shapes and thumbnails are not
        # required to reproduce the model from its complete assumptions.
        export_model = model
        if model.get('kind') == 'plate':
            export_model = {k:v for k,v in model.items() if k != 'nodes'}
            export_model['modes'] = [{k:v for k,v in mode.items() if k != 'thumbnail'} for mode in model['modes']]
        result.update(frequency_hz=model['frequency_hz'], axis=model['axis'], modal_gain=modal_gain,
                      export_frames=count, export_duration_s=count/fps,
                      simulation_duration_s=tap['duration_s'], display_cycles_per_second=config.get('effective_display_cps', config['display_cps']),
                      requested_display_cycles_per_second=config['display_cps'],
                      playback_slowdown=tap.get('playback_slowdown', model['frequency_hz']/config['display_cps']),
                      interpretation=model['interpretation'], tap_settings=config, tap_model=export_model,
                      normalized_matrices=tap['normalized_matrices'], _tap_traces=tap, _tap_model=model)
    elif modal:
        result.update(frequency_hz=field['frequency_hz'], axis=field['axis'], modal_gain=modal_gain,
                      phase_start_deg=phase_start % 360, display_cycles=MODAL_CYCLES,
                      display_cycles_per_second=1, phase_reference=field['reference']['label'],
                      camera_reference_subtracted=field['reference_last'],
                      interpretation='Fitted camera-plane operating response; not an identified structural mode')
    else:
        result.update(band_hz=[render_info['low'], render_info['high']],
                      magnification_gain=render_info['gain'],
                      response_reference_rms=render_info['response']['display_reference_rms'],
                      interpretation='Bandpassed luminance RMS; texture dependent, not displacement amplitude')
    return result


def annotate_tap(rgb, metadata, time_s):
    """Include model provenance, time cursor and simulated probes in shared video."""
    h, w = rgb.shape[:2]
    scale = min(640/w, 480/h)
    iw, ih = round(w*scale), round(h*scale)
    height = 64+ih+240
    height += height % 2
    output = np.full((height,640,3),(8,17,24),np.uint8)
    output[64:64+ih,(640-iw)//2:(640-iw)//2+iw] = cv2.resize(rgb,(iw,ih))
    config, model = metadata['tap_settings'], metadata['tap_model']
    predicted = model.get('kind') == 'plate'
    title = 'PREDICTED MODE' if predicted and config['motion'] == 'mode' else 'PREDICTED COMBINED TAP' if predicted else 'VIRTUAL TAP'
    frequency = config.get('clock_hz', model['frequency_hz'])
    text_line(output, f"{title} | {frequency:.3f} Hz | ASSUMED MODEL", 26,(54,207,238),.6)
    if predicted and config['motion'] == 'mode':
        text_line(output, f"Continuous shape animation | Relative amplitude {config['strength']:g}x | Display gain {metadata['modal_gain']:g}x",48)
    else:
        text_line(output, f"Assumed damping {config['damping_percent']:g}% | Relative strength {config['strength']:g}x | Display gain {metadata['modal_gain']:g}x",48)
    base = 64+ih
    text_line(output, f"Simulation {time_s:.4f} s | {metadata['playback_slowdown']:.1f}x slower playback | {model['axis'].upper()} axis",base+22)
    prediction = metadata['_tap_traces']
    times = np.asarray(prediction['time_s'])
    peak = max(1e-6,max(abs(v) for tr in prediction['traces'] for v in tr['displacement_source_px']))*1.1
    left, right, top, bottom = 62,620,base+53,base+145
    cv2.line(output,(left,(top+bottom)//2),(right,(top+bottom)//2),(35,61,75),1)
    for trace, color in zip(prediction['traces'],[(54,207,238),(255,201,134)]):
        values = np.asarray(trace['displacement_source_px'])
        pts = np.column_stack([left+times/prediction['duration_s']*(right-left),
                               (top+bottom)/2-values/peak*(bottom-top)/2]).astype(np.int32)
        cv2.polylines(output,[pts],False,color,1,cv2.LINE_AA)
    cursor = int(left+time_s/prediction['duration_s']*(right-left))
    cv2.line(output,(cursor,top),(cursor,bottom),(235,242,247),1)
    text_line(output,f"+/- {peak:.3g} simulated source px (gain excluded)",base+45,scale=.4)
    a,b = prediction['traces']
    text_line(output,f"A: Grid {a['node']+1} (cyan) | B: Grid {b['node']+1} (amber) | 0-{prediction['duration_s']:.4f} simulation s",base+166)
    text_line(output,'Normalized mass; assumed damping and natural frequency; no force calibration.',base+190)
    if predicted:
        frequencies = ', '.join(f"{model['modes'][i]['frequency_hz']:.1f}" for i in config['active_modes'])
        text_line(output, f"Model modes: {frequencies} Hz | Not measured higher modes.", base+212)
    else:
        text_line(output,'Operating-response shape approximation; not a measured impulse response.',base+212)
    text_line(output,f"Source time: {metadata['analysis_fps']:g} analysis fps | {metadata['timing_basis']}",base+233,scale=.38)
    return output


def text_line(image, text, y, color=(185, 205, 219), scale=.46):
    # ASCII avoids unavailable glyphs in OpenCV's built-in font.
    text = text.encode('ascii', 'replace').decode('ascii')
    width = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, 1)[0][0]
    if width > image.shape[1]-28:
        scale *= (image.shape[1]-28) / width
    cv2.putText(image, text, (14, y), cv2.FONT_HERSHEY_SIMPLEX, scale, color, 1, cv2.LINE_AA)


def annotate(rgb, metadata, progress):
    h, w = rgb.shape[:2]
    scale = min(640/w, 480/h)
    iw, ih = max(1, round(w*scale)), max(1, round(h*scale))
    height = 64 + ih + 152
    height += height % 2  # H.264 4:2:0 needs even dimensions; never crop image pixels.
    output = np.empty((height, 640, 3), np.uint8)
    output[:] = (16, 24, 32)
    x = (640-iw)//2
    output[64:64+ih, x:x+iw] = cv2.resize(rgb, (iw, ih), interpolation=cv2.INTER_LINEAR)
    modal = metadata['view'] == 'modal'
    if modal:
        title = f"Fitted response | {metadata['frequency_hz']:g} Hz | {metadata['axis'].upper()} axis"
        settings = f"Sensitivity {metadata['sensitivity']:g}% | Displacement display gain {metadata['modal_gain']:g}x"
    else:
        low, high = metadata['band_hz']
        title = f"{'Frequency heatmap' if metadata['view']=='heatmap' else 'Isolated response'} | {low:g}-{high:g} Hz band"
        settings = (f"Sensitivity {metadata['sensitivity']:g}% | Original band RMS (gain independent)"
                    if metadata['view'] == 'heatmap' else
                    f"Sensitivity {metadata['sensitivity']:g}% | Added magnification gain {metadata['magnification_gain']:g}")
    text_line(output, title, 26, (118, 224, 194), .63)
    text_line(output, settings, 48)
    base = 64 + ih
    if 'user-assumed' in metadata['timing_basis']:
        timing = f"Timing: user-assumed {metadata['analysis_fps']:g} capture fps; frame mapping unverified"
    else:
        timing = f"Timing: encoded video time ({metadata['analysis_fps']:g} fps); physical Hz unverified"
    text_line(output, timing, base+22)
    if modal:
        text_line(output, f"Playback: 1 display cycle/s (slowed) | Cycle phase {progress%360:.0f} deg", base+44)
        text_line(output, f"Phase 0 = positive reference maximum | {metadata['phase_reference']}", base+66)
        text_line(output, 'Blue: negative / Orange: positive selected-axis displacement', base+90)
        text_line(output, 'Sampled operating response; not an identified structural mode.', base+112)
        if metadata['camera_reference_subtracted']:
            text_line(output, 'Stationary-reference translation subtracted; image not stabilized.', base+136)
        else:
            text_line(output, 'Original source-pixel fits; display gain does not change measurements.', base+136)
    else:
        analysis_time = progress / metadata['analysis_fps']
        playback_time = progress / metadata['encoded_fps']
        text_line(output, f"Playback: {metadata['encoded_fps']:g} encoded fps | {playback_time:.2f} playback s / {analysis_time:.3f} analysis s", base+44)
        reference = metadata['response_reference_rms']
        cutoff = reference*(1-metadata['sensitivity']/100)*.75
        text_line(output, f"Band luminance RMS 0-{reference:.3f} | Threshold {cutoff:.3f} | 99th-percentile scale", base+66)
        if metadata['view'] == 'heatmap':
            gradient = np.linspace(0, 255, 300).astype(np.uint8)[None, :]
            colors = response_layers(gradient, 100)[0].astype(np.uint8)
            output[base+78:base+86, 14:314] = colors
            text_line(output, 'Weaker                               Stronger', base+104)
        else:
            text_line(output, 'Stable response mask applied to magnified frames.', base+96)
        text_line(output, 'Brightness response depends on texture; not displacement amplitude.', base+136)
    return output


def export_frames(video, metadata, rendered=None, response_display=None, field=None, maps=None, tap_maps=None):
    if metadata['view'] == 'tap':
        for i in range(metadata['export_frames']):
            t = min(i/metadata['export_fps']/metadata['playback_slowdown'],metadata['simulation_duration_s'])
            rgb = tap_display_frame(video,metadata.get('_tap_model',metadata['tap_model']),tap_maps,metadata['tap_settings'],t,metadata['modal_gain'])
            yield annotate_tap(rgb,metadata,t)
    elif metadata['view'] == 'modal':
        for i in range(metadata['export_frames']):
            phase = (metadata['phase_start_deg'] + i/MODAL_FPS*360) % 360
            rgb = modal_display_frame(video, field, maps, phase, metadata['modal_gain'], metadata['sensitivity'])
            yield annotate(rgb, metadata, phase)
    else:
        layers = response_layers(response_display, metadata['sensitivity'])
        for i, original in enumerate(video.frames):
            yield annotate(band_frame(original, rendered[i], layers, metadata['view']), metadata, i)


def write_mp4(path, frames, metadata):
    """Stream RGB frames to a local encoder; fail rather than serve a partial file."""
    try:
        import imageio_ffmpeg
        binary = imageio_ffmpeg.get_ffmpeg_exe()
    except (ImportError, RuntimeError) as exc:
        raise ValueError('Video export needs the bundled FFmpeg dependency. Install requirements.txt and retry.') from exc
    frames = iter(frames)
    first = next(frames)
    h, w = first.shape[:2]
    command = [binary, '-hide_banner', '-loglevel', 'error', '-y', '-f', 'rawvideo',
               '-pix_fmt', 'rgb24', '-s', f'{w}x{h}', '-r', f"{metadata['export_fps']:.12g}",
               '-i', 'pipe:0', '-an', '-c:v', 'libx264', '-preset', 'fast', '-crf', '18',
               '-pix_fmt', 'yuv420p', '-threads', '2', '-movflags', '+faststart',
               '-metadata', 'comment='+json.dumps({k:v for k,v in metadata.items() if not k.startswith('_')}), str(path)]
    with TemporaryFile() as diagnostics:
        try:
            process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                       stderr=diagnostics)
        except OSError as exc:
            raise ValueError('Could not start the local video encoder. Reinstall requirements.txt and retry.') from exc
        deadline = Timer(120, process.kill)
        deadline.start()
        try:
            process.stdin.write(first.tobytes())
            for rgb in frames:
                if rgb.shape != first.shape:
                    raise ValueError('Export frame dimensions changed.')
                process.stdin.write(rgb.tobytes())
            process.stdin.close()
            if process.wait(timeout=15) != 0:
                raise ValueError('Video encoding failed. Try a shorter clip or reinstall the FFmpeg dependency.')
            if not Path(path).exists() or Path(path).stat().st_size == 0:
                raise ValueError('Video encoder produced an empty file.')
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ValueError('Video encoding failed or timed out. Try a shorter clip and retry.') from exc
        finally:
            deadline.cancel()
            if process.poll() is None:
                process.kill()
            process.wait()
            if not process.stdin.closed:
                try:
                    process.stdin.close()
                except OSError:
                    pass


def export_filename(metadata):
    frequency = (f"{metadata['frequency_hz']:g}" if metadata['view'] in ('modal','tap')
                 else '-'.join(f'{f:g}' for f in metadata['band_hz']))
    return f"modal-camera-{frequency.replace('.', 'p')}Hz-{metadata['view']}.mp4"
