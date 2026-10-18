"""Loopback-only Flask prototype. No CDN, telemetry, cloud or hardware calls."""
from pathlib import Path
from dataclasses import replace
from tempfile import TemporaryDirectory
from threading import RLock, Lock
import argparse
import csv
import io
import json
import math
import secrets

import cv2
from flask import Flask, jsonify, render_template, request, Response, send_file
import numpy as np
from werkzeug.exceptions import HTTPException
from modal_camera.processing import decode_video, magnify, track_points, analyze_tracks
from modal_camera.synthetic import write_demos
from modal_camera.response import measure_field, modal_frame
from modal_camera.video_export import export_metadata, export_frames, write_mp4, export_filename
from modal_camera.session import defaults, validate_settings, validate_ui, signature

ROOT = Path(__file__).resolve().parent
app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 512 * 1024 * 1024
app.config['TEMPLATES_AUTO_RELOAD'] = True
state = {}
lock = RLock()
video_export_lock = Lock()
latest_video_export = {}
latest_data_export = {}
ALLOWED_EXTENSIONS = {'.mp4','.m4v','.mov','.avi','.mkv','.webm'}


def numeric(value, name):
    try:
        v = float(value)
    except (TypeError,ValueError):
        raise ValueError(f'{name} must be a finite number.')
    if not math.isfinite(v):
        raise ValueError(f'{name} must be a finite number.')
    return v


def current(clip_id):
    if state.get('id') != clip_id:
        raise ValueError('Clip is no longer loaded. Load a video and try again.')
    return state['video']


def json_object():
    data = request.get_json()
    if not isinstance(data,dict):
        raise ValueError('Settings must be a JSON object.')
    return data


def check_revision(data):
    if 'revision' in data and data['revision'] != state.get('revision'):
        raise ValueError('Settings changed in another tab. Reload to recover the current session.')


def change_settings(settings, force=False):
    previous = state['settings']
    for kind, extras in [('analysis',()),('field',('field_maps',)),
                         ('render',('render_info','response_display'))]:
        if force or signature(previous,kind) != signature(settings,kind):
            state[kind] = None
            state[kind+'_key'] = None
            for extra in extras:
                state[extra] = None
    if force or previous != settings:
        state['revision'] = secrets.token_hex(8)
    state['settings'] = settings


def adopt_settings(data,kind):
    check_revision(data)
    keys = signature(state['settings'],kind)
    fallback = dict(axis='y',reference_last=False,reference='auto',roi=None,points=[])
    incoming = {key:data.get(key,fallback.get(key)) for key in keys}
    proposed = dict(state['settings'],**incoming)
    # Existing API clients can still choose independent bands explicitly.
    if kind == 'render':
        proposed['linked'] = False
    proposed = validate_settings(proposed,state['video'])
    if 'revision' in data:
        if signature(proposed,kind) != signature(state['settings'],kind):
            raise ValueError('Processing settings do not match the saved session. Update settings first.')
    else:
        change_settings(proposed)


def session_payload():
    if 'video' not in state:
        return dict(clip=None)
    video = state['video']
    return dict(clip=dict(id=state['id'],metadata=video.metadata),settings=state['settings'],
                revision=state['revision'],ui=state['ui'],analysis=state.get('analysis'),
                analysis_key=state.get('analysis_key'),render_info=state.get('render_info'),
                render_key=state.get('render_key'),field=state.get('field'),field_key=state.get('field_key'))


@app.before_request
def local_only():
    host = request.host.split(':')[0]
    if host not in ('127.0.0.1','localhost'):
        return jsonify(error='Use the loopback address 127.0.0.1.'),403
    if request.method == 'POST':
        origin = request.headers.get('Origin')
        if origin and origin not in ('http://'+request.host,):
            return jsonify(error='Cross-origin requests are disabled.'),403


@app.errorhandler(Exception)
def error(exc):
    if isinstance(exc,(ValueError,TypeError,KeyError)):
        return jsonify(error=str(exc)),400
    if isinstance(exc,HTTPException):
        if exc.code == 413:
            limit = app.config['MAX_CONTENT_LENGTH'] // (1024 * 1024)
            return jsonify(error=f'Upload exceeds the {limit} MiB request limit. Choose a smaller file.'),413
        return jsonify(error=exc.description),exc.code
    app.logger.exception('Local processing failed')
    return jsonify(error='Processing failed. See the local terminal for details; try a shorter constant-frame-rate clip.'),500


@app.after_request
def headers(response):
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Content-Security-Policy'] = "default-src 'self'; img-src 'self' blob: data:; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'"
    return response


@app.get('/')
def index():
    return render_template('index.html',upload_limit_mib=app.config['MAX_CONTENT_LENGTH'] // (1024 * 1024))


def install_clip(video, demo=False):
    # Only one clip kept in RAM; replacement invalidates render and tracking state.
    state.clear()
    state.update(id=secrets.token_hex(8),video=video,render=None,traces=None,analysis=None,field=None,
                 revision=secrets.token_hex(8),settings=defaults(demo),
                 ui=validate_ui(dict(timing_mode='encoded' if demo else '',timing_confirmed=demo),len(video.frames)))
    latest_video_export.clear()
    latest_data_export.clear()
    return jsonify(id=state['id'],metadata=video.metadata,default_points=state['settings']['points'],
                   default_band=[state['settings']['low'],state['settings']['high']],
                   revision=state['revision'],settings=state['settings'],ui=state['ui'])


@app.get('/api/session')
def session():
    with lock:
        return jsonify(session_payload())


@app.post('/api/settings')
def settings():
    data = json_object()
    with lock:
        video = current(data.get('id'))
        check_revision(data)
        proposed = validate_settings(data.get('settings',state['settings']),video)
        ui = validate_ui(data.get('ui',state['ui']),len(video.frames))
        change_settings(proposed,force=data.get('invalidate') is True)
        state['ui'] = ui
        return jsonify(revision=state['revision'])


@app.post('/api/load')
def load():
    upload = request.files.get('video')
    if upload is None or not upload.filename:
        raise ValueError('Select a video file.')
    extension = Path(upload.filename).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise ValueError('Unsupported file type. Use MP4, MOV, AVI, MKV, M4V or WebM with a supported decoder codec.')
    with lock, TemporaryDirectory(prefix='modal-camera-') as temp:
        path = Path(temp)/('input'+extension)
        upload.save(path)
        video = decode_video(path,Path(upload.filename).name)
        return install_clip(video)


@app.post('/api/demo')
def demo():
    kind = (request.get_json(silent=True) or {}).get('kind','clean')
    if kind not in ('clean','dropout'):
        raise ValueError('Unknown demo.')
    with lock:
        demos = ROOT/'demo_videos'
        if not (demos/'known_motion.avi').exists():
            write_demos(demos)
        name = 'known_motion' if kind=='clean' else 'tracking_dropout'
        return install_clip(decode_video(demos/(name+'.avi')),True)


@app.post('/api/analyze')
def analyze():
    data = json_object()
    with lock:
        video = current(data.get('id'))
        check_revision(data)
        points = data.get('points')
        axis = data.get('axis','y')
        f = data.get('frequency')
        f = numeric(f,'Frequency') if f is not None else None
        if state.get('point_coordinates') != points:
            traces = track_points(video,points)
            state.update(traces=traces,point_coordinates=points)
        result = analyze_tracks(video,state['traces'],axis,f,reference_last=bool(data.get('reference_last',False)))
        adopt_settings(dict(data,frequency=result['frequency_hz'],axis=axis,points=points,
                            reference_last=result['reference_last']),'analysis')
        state['analysis'] = result
        state['analysis_key'] = secrets.token_hex(8)
        return jsonify(key=state['analysis_key'],revision=state['revision'],**result)


@app.post('/api/render')
def render():
    data = json_object()
    with lock:
        video = current(data.get('id'))
        check_revision(data)
        low,high,gain = [numeric(data.get(k),k) for k in ('low','high','gain')]
        roi = data.get('roi')
        if roi is not None and (not isinstance(roi,list) or len(roi)!=4 or not all(isinstance(x,(int,float)) and math.isfinite(x) for x in roi)):
            raise ValueError('ROI must be four finite coordinates.')
        rendered, info, response = magnify(video,low,high,gain,roi,return_response=True)
        reference = info['response']['display_reference_rms']
        response_display = np.clip(response / max(reference,1e-6)*255,0,255).astype(np.uint8)
        adopt_settings(data,'render')
        state.update(render=rendered,render_key=secrets.token_hex(8),render_info=info,response_display=response_display)
        return jsonify(key=state['render_key'],revision=state['revision'],**info)


@app.get('/api/response/<clip_id>')
def response_image(clip_id):
    with lock:
        current(clip_id)
        if state.get('render') is None or request.args.get('key') != state.get('render_key'):
            raise ValueError('Response map is not current. Apply the selected band first.')
        ok, encoded = cv2.imencode('.png',state['response_display'])
        if not ok:
            raise ValueError('Response map encoder failed.')
        return Response(encoded.tobytes(),mimetype='image/png')


@app.post('/api/field')
def spatial_field():
    data = json_object()
    with lock:
        video = current(data.get('id'))
        check_revision(data)
        result, cache, maps = measure_field(video,numeric(data.get('frequency'),'Frequency'),
                                           axis=data.get('axis','y'),roi=data.get('roi'),points=data.get('points'),
                                           reference=data.get('reference','auto'),reference_last=bool(data.get('reference_last',False)),
                                           cached=state.get('field_cache'))
        adopt_settings(dict(data,points=data.get('points') or [],reference_last=result['reference_last']),'field')
        state.update(field=result,field_cache=cache,field_maps=maps,field_key=secrets.token_hex(8))
        return jsonify(key=state['field_key'],revision=state['revision'],**result)


@app.post('/api/timebase')
def timebase():
    data = json_object()
    with lock:
        video = current(data.get('id'))
        check_revision(data)
        encoded = video.encoded_fps or video.fps
        override = data.get('capture_fps')
        fps = numeric(override,'Capture fps') if override is not None else encoded
        if not 1 <= fps <= 2000:
            raise ValueError('Capture frame rate must be 1–2000 fps.')
        if override is not None and data.get('one_frame_per_sample') is not True:
            raise ValueError('Confirm one encoded frame per captured sample before using a capture-rate override.')
        basis = 'user-assumed capture time: one frame per captured sample' if override is not None else 'encoded video time'
        warnings = [w for w in video.warnings if not w.startswith(('Frequencies use encoded video time.',
                    'Analysis frequencies use a user-assumed capture rate.'))]
        warnings.append('Analysis frequencies use a user-assumed capture rate. Verify one encoded frame per captured sample; physical timing remains unverified.'
                        if override is not None else
                        'Frequencies use encoded video time. Original capture/playback speed must be verified for physical Hz.')
        state['video'] = replace(video,fps=fps,encoded_fps=encoded,timing_basis=basis,warnings=warnings)
        change_settings(state['settings'],force=True)
        state['ui'].update(timing_mode='capture' if override is not None else 'encoded',timing_confirmed=True)
        return jsonify(id=state['id'],metadata=state['video'].metadata,revision=state['revision'])


@app.get('/api/frame/<clip_id>/<int:frame>')
def frame(clip_id,frame):
    with lock:
        video = current(clip_id)
        if frame >= len(video.frames):
            raise ValueError('Frame outside the clip.')
        view = request.args.get('view','original')
        if view == 'amplified':
            if state.get('render') is None or request.args.get('key') != state.get('render_key'):
                raise ValueError('Amplification is not current. Apply the selected band first.')
            rgb = state['render'][frame]
        elif view=='original':
            rgb = video.frames[frame]
        elif view=='modal':
            if state.get('field') is None or request.args.get('key') != state.get('field_key'):
                raise ValueError('Spatial response is not current. Build the displacement map first.')
            rgb = modal_frame(video,state['field'],state['field_maps'],
                              numeric(request.args.get('phase',0),'Phase'),numeric(request.args.get('gain',10),'Modal gain'),
                              numeric(request.args.get('threshold',0),'Response threshold'))
        else:
            raise ValueError('Unknown frame view.')
        ok,encoded = cv2.imencode('.jpg',cv2.cvtColor(rgb,cv2.COLOR_RGB2BGR),[cv2.IMWRITE_JPEG_QUALITY,92])
        if not ok:
            raise ValueError('Frame encoder failed.')
        return Response(encoded.tobytes(),mimetype='image/jpeg')


@app.get('/api/export/<clip_id>')
def export(clip_id):
    with lock:
        video = current(clip_id)
        check_revision(request.args)
        analysis = state.get('analysis')
        if analysis is None and state.get('field') is None:
            raise ValueError('Analyze points or build the displacement map before exporting.')
        sensitivity = numeric(request.args.get('sensitivity',state['ui']['sensitivity']),'Sensitivity')
        modal_gain = numeric(request.args.get('modal_gain',state['ui']['modal_gain']),'Modal gain')
        if not 0 <= sensitivity <= 100 or not 0 <= modal_gain <= 20:
            raise ValueError('Sensitivity must be 0–100 and modal gain 0–20.')
        output = dict(video=video.metadata,measurement=analysis,magnification=state.get('render_info'),
                      spatial_response=state.get('field'),display=dict(sensitivity=sensitivity,modal_gain=modal_gain,
                      view=request.args.get('view',state['ui']['view']),calibration_mm_per_source_px=state['settings']['calibration']),
                      method='Original-frame fixed-reference pyramidal LK; magnification linear Eulerian Laplacian luminance',
                      caveat='Frequency is video-time Hz; verify original capture/playback speed. This is not an identified mode.')
        return Response(json.dumps(output,indent=2),mimetype='application/json',headers={'Content-Disposition':'attachment; filename=modal-camera-analysis.json'})


@app.post('/api/export-video')
def export_video():
    data = request.get_json()
    if not isinstance(data,dict):
        raise ValueError('Export settings must be a JSON object.')
    with lock:
        video = current(data.get('id'))
        check_revision(data)
        view = data.get('view')
        key_name = 'field_key' if view == 'modal' else 'render_key'
        if not state.get(key_name) or data.get('key') != state.get(key_name):
            raise ValueError('Export settings are no longer current. Rebuild the spatial map or apply the band first.')
        metadata = export_metadata(video,view,numeric(data.get('sensitivity',85),'Sensitivity'),
                                   numeric(data.get('modal_gain',10),'Modal gain'),
                                   numeric(data.get('phase_start',0),'Start phase'),
                                   state.get('render_info'),state.get('field'))
        # Immutable arrays/results remain owned by this export if another tab
        # replaces the clip or settings. Encoding does not hold the state lock.
        frames = export_frames(video,metadata,state.get('render'),state.get('response_display'),
                               state.get('field'),state.get('field_maps'))
    if not video_export_lock.acquire(blocking=False):
        raise ValueError('Another video export is in progress. Wait for it to finish and retry.')
    try:
        with TemporaryDirectory(prefix='modal-camera-export-') as temp:
            path = Path(temp)/'response.mp4'
            write_mp4(path,frames,metadata)
            payload = path.read_bytes()
        filename = export_filename(metadata)
        if request.args.get('prepare') == '1':
            export_key = secrets.token_hex(16)
            with lock:
                # Only the latest completed download is cached, as immutable
                # compressed bytes. Active downloads keep their own file handle.
                latest_video_export.clear()
                latest_video_export.update(key=export_key,data=payload,filename=filename)
            return jsonify(url=f'/api/export-video/{export_key}/{filename}',filename=filename)
        return send_file(io.BytesIO(payload),mimetype='video/mp4',as_attachment=True,download_name=filename)
    finally:
        video_export_lock.release()


@app.get('/api/export-video/<export_key>/<filename>')
def download_exported_video(export_key,filename):
    with lock:
        if export_key != latest_video_export.get('key') or filename != latest_video_export.get('filename'):
            raise ValueError('This video download has expired. Export the view again.')
        payload = latest_video_export['data']
    return send_file(io.BytesIO(payload),mimetype='video/mp4',as_attachment=True,download_name=filename)


@app.get('/api/field-csv/<clip_id>')
def field_csv(clip_id):
    with lock:
        current(clip_id)
        check_revision(request.args)
        result = state.get('field')
        if result is None:
            raise ValueError('Build the displacement map before exporting spatial samples.')
        stream = io.StringIO()
        writer = csv.writer(stream)
        writer.writerow(['grid_point','x_analysis_px','y_analysis_px','axis','frequency_analysis_hz','amplitude_peak_source_px',
                         'relative_phase_deg','accepted_frame_fraction','x_cos_source_px','x_sin_source_px','y_cos_source_px','y_sin_source_px',
                         'fit_residual_source_px','harmonic_power_fraction','phase_reference','timing_basis'])
        for node in result['nodes']:
            xfit, yfit, chosen = node['fit']['x'],node['fit']['y'],node['fit'][result['axis']]
            writer.writerow([node['index']+1,node['x'],node['y'],result['axis'],result['frequency_hz'],node['amplitude_peak_px'],
                             node['relative_phase_deg'],node['valid_fraction'],*(xfit['coefficients_px'] if xfit else [None,None]),
                             *(yfit['coefficients_px'] if yfit else [None,None]),chosen['rms_residual_px'] if chosen else None,
                             chosen['harmonic_power_fraction'] if chosen else None,result['reference']['label'],result['timing_basis']])
        return Response(stream.getvalue(),mimetype='text/csv',headers={'Content-Disposition':'attachment; filename=modal-camera-spatial-response.csv'})


@app.get('/api/csv/<clip_id>')
def export_csv(clip_id):
    with lock:
        video = current(clip_id)
        check_revision(request.args)
        result = state.get('analysis')
        if result is None:
            raise ValueError('Analyze points before exporting.')
        stream = io.StringIO()
        writer = csv.writer(stream)
        columns = ['analysis_time_s']
        for p in result['points']:
            columns += [f"P{p['point']}_dx_source_px",f"P{p['point']}_dy_source_px",f"P{p['point']}_accepted",f"P{p['point']}_fb_error_analysis_px",f"P{p['point']}_ncc"]
        writer.writerow(columns)
        for i,t in enumerate(result['time']):
            row = [t]
            for p in result['points']:
                row += [p['dx'][i],p['dy'][i],p['valid'][i],p['quality']['fb_error_px'][i],p['quality']['ncc'][i]]
            writer.writerow(row)
        return Response(stream.getvalue(),mimetype='text/csv',headers={'Content-Disposition':'attachment; filename=modal-camera-traces.csv'})


@app.post('/api/export-data')
def prepare_data_export():
    data = json_object()
    with lock:
        current(data.get('id'))
        if data.get('revision') != state['revision']:
            raise ValueError('Results are no longer current. Analyze the response before exporting.')
        kind = data.get('kind')
        if kind not in ('analysis','samples','traces'):
            raise ValueError('Choose analysis JSON, spatial samples, or point traces.')
        response = {'analysis':export,'samples':field_csv,'traces':export_csv}[kind](state['id'])
        filename = {'analysis':'modal-camera-analysis.json','samples':'modal-camera-spatial-response.csv',
                    'traces':'modal-camera-traces.csv'}[kind]
        token = secrets.token_hex(16)
        latest_data_export.clear()
        latest_data_export.update(key=token,filename=filename,data=response.get_data(),mimetype=response.mimetype)
        return jsonify(url=f'/api/download-data/{token}/{filename}',filename=filename)


@app.get('/api/download-data/<token>/<filename>')
def download_data(token,filename):
    with lock:
        if token != latest_data_export.get('key') or filename != latest_data_export.get('filename'):
            raise ValueError('This data download has expired. Export again.')
        payload,mimetype = latest_data_export['data'],latest_data_export['mimetype']
    return send_file(io.BytesIO(payload),mimetype=mimetype,as_attachment=True,download_name=filename)


if __name__=='__main__':
    parser = argparse.ArgumentParser(description='Offline Modal Camera prototype; local recorded video only.')
    parser.add_argument('--port',type=int,default=8765)
    parser.add_argument('--make-demos',action='store_true')
    args = parser.parse_args()
    if args.make_demos:
        write_demos(ROOT/'demo_videos')
        print('Created lossless deterministic demo videos.')
    else:
        print(f'Open http://127.0.0.1:{args.port} (videos remain local; Ctrl+C stops).')
        app.run(host='127.0.0.1',port=args.port,debug=False,threaded=True)
