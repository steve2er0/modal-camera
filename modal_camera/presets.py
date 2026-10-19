"""Settings-only presets. Never decode, replace or resample a recording."""
from dataclasses import replace

from .session import defaults, validate_settings, validate_ui


def plate_demo_settings(video):
    """Restore the original 95 Hz plate experiment's explicit assumptions.

    The outline/PSD locations scale from its 301 x 169 analysis image. These
    are a preset for that recording, not automatically detected object bounds.
    """
    width,height = video.metadata['width'],video.metadata['height']
    sx,sy = width/301,height/169
    warnings = [w for w in video.warnings if not w.startswith((
        'Frequencies use encoded video time.', 'Analysis frequencies use'))]
    warnings.append('Analysis frequencies use the plate preset\'s assumed 240 fps capture rate. '
                    'One encoded frame per captured sample and physical timing remain unverified.')
    assumed = replace(video,fps=240.,encoded_fps=video.encoded_fps or video.fps,
                      timing_basis='user-assumed capture time: one frame per captured sample',warnings=warnings)
    settings = validate_settings(dict(defaults(),frequency=94.872,linked=False,low=91.883,high=97.092,
                                      spectrum_highpass_hz=10.,spectrum_source='point',
                                      spectrum_point=[112*sx,64*sy],spectrum_region=[35*sx,50*sy,235*sx,55*sy]),assumed)
    ui = validate_ui(dict(view='tap',frame=0,sensitivity=76.,modal_gain=8.,phase=28.,
                          timing_mode='capture',timing_confirmed=True,
                          tap=dict(model_source='plate',motion='tap',cycles=40.,damping_percent=1.,strength=1.,
                                   direction=1.,display_cps=2.,cursor_cycle=0.,enabled_modes=[0,1,2,3],
                                   plate=dict(corners=[[45*sx,55*sy],[236*sx,52*sy],[269*sx,96*sy],[20*sx,99*sy]],
                                              aspect_ratio=2.,taper_ratio=1.,sweep_offset=0.,poisson=.33,
                                              mounting='free',projection_angle_deg=90.,anchor_mode=None))),len(video.frames))
    return assumed,settings,ui
