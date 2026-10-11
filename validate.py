"""Reproduce numerical evidence; external guitar is smoke-tested, not ground truth."""
from dataclasses import replace
from pathlib import Path
import hashlib
import json
import platform
import time
import cv2
import numpy as np
import scipy
from modal_camera.processing import decode_video,track_points,analyze_tracks,magnify

root=Path(__file__).resolve().parent
start=time.perf_counter()
video=decode_video(root/'demo_videos/known_motion.avi')
traces=track_points(video,[[90,94],[230,94]])
fits={str(f):analyze_tracks(video,traces,'y',f) for f in [3,7]}
report=dict(platform=platform.platform(),python=platform.python_version(),numpy=np.__version__,scipy=scipy.__version__,opencv=cv2.__version__,
            demo_metadata=video.metadata,expected=dict(frequency_hz=3,amplitude_y_px=[.4,.6],relative_phase_deg=60),
            measured_peak_hz=fits['3']['peak_frequency_hz'],fits={f:[dict(point=p['point'],valid_fraction=p['valid_fraction'],**p['fit']) for p in a['points']] for f,a in fits.items()})
drop=decode_video(root/'demo_videos/tracking_dropout.avi')
drop_a=analyze_tracks(drop,track_points(drop,[[90,94],[230,94]]),'y',3)
report['dropout']=[dict(point=p['point'],valid_fraction=p['valid_fraction'],fit_withheld=p['fit'] is None,warnings=p['warnings']) for p in drop_a['points']]
low=analyze_tracks(video,track_points(video,[[160,170]]),'y',3)['points'][0]
report['low_texture']=dict(valid_fraction=low['valid_fraction'],fit=low['fit'],warnings=low['warnings'])
amplified,info=magnify(video,2.5,3.5,1)
render_a=analyze_tracks(video,track_points(replace(video,frames=amplified),[[90,94]]),'y',3)
report['render_response']=dict(added_gain=1,expected_peak_px=.8,measured_peak_px=render_a['points'][0]['fit']['amplitude_peak_px'],settings=info)
cv2.imwrite(str(root/'evidence/demo-original-frame.png'),cv2.cvtColor(video.frames[45],cv2.COLOR_RGB2BGR))
cv2.imwrite(str(root/'evidence/demo-amplified-frame.png'),cv2.cvtColor(amplified[45],cv2.COLOR_RGB2BGR))
guitar_path=root/'data/examples/guitar.mp4'
if guitar_path.exists():
    guitar=decode_video(guitar_path)
    assumed=replace(guitar,fps=600,encoded_fps=guitar.fps,timing_basis='assumed paper capture fps; one encoded frame per sample unverified')
    output,guitar_info=magnify(assumed,72,92,2)
    samples=track_points(assumed,[[200,57],[220,91],[240,132]])
    guitar_analysis=analyze_tracks(assumed,samples,'y',80)
    source=dict(url='https://people.csail.mit.edu/mrub/evm/video/guitar.mp4',paper='https://people.csail.mit.edu/mrub/papers/vidmag.pdf#page=6',
                bytes=guitar_path.stat().st_size,sha256=hashlib.sha256(guitar_path.read_bytes()).hexdigest(),encoded=guitar.metadata,
                paper_capture_fps=600,paper_bands_hz=[[72,92],[100,120]],timing_assumption='600 fps applies only if every encoded frame corresponds to one captured sample; mapping not independently verified',
                decode_passed=True,render_smoke_test=guitar_info,quantitative_physical_frequency_validated=False)
    (root/'data/examples/guitar.source.json').write_text(json.dumps(source,indent=2)+'\n')
    (root/'evidence/guitar-smoke-analysis.json').write_text(json.dumps(guitar_analysis,indent=2)+'\n')
    report['guitar_smoke']=dict(**source,tracking_valid_fraction=[p['valid_fraction'] for p in guitar_analysis['points']],fit_withheld=[p['fit'] is None for p in guitar_analysis['points']],measured_bin_assumed_hz=guitar_analysis['peak_frequency_hz'])
    cv2.imwrite(str(root/'evidence/guitar-amplified-frame.png'),cv2.cvtColor(output[90],cv2.COLOR_RGB2BGR))
report['elapsed_s']=time.perf_counter()-start
(root/'evidence/numerical-validation.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({k:report[k] for k in ['measured_peak_hz','fits','dropout','low_texture','render_response','elapsed_s']},indent=2))
