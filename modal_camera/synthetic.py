"""Seeded lossless synthetic videos, with analytic ground truth in source pixels."""
from pathlib import Path
import json
import cv2
import numpy as np


def synthesize(dropout=False, fps=60., seconds=6.):
    h,w = 200,320
    n = int(fps*seconds)
    yy,xx = np.mgrid[:h,:w].astype(np.float32)
    frames = []
    centers = [(90,94),(230,94)]
    rng = np.random.default_rng(20261005)
    phases = rng.uniform(-np.pi,np.pi,(2,3))
    for i in range(n):
        t = i/fps
        frame = np.zeros((h,w,3),np.uint8)
        frame[:] = [29,40,53]
        for j,(cx,cy) in enumerate(centers):
            phi = np.deg2rad(60*j)
            dx = (.18 if j==0 else .28)*np.cos(2*np.pi*3*t+phi)
            dy = (.40 if j==0 else .60)*np.cos(2*np.pi*3*t+phi) + (.12 if j==0 else .10)*np.cos(2*np.pi*7*t-.3)
            # Evaluate the continuous texture at displaced coordinates, avoiding
            # interpolation-kernel bias in the analytic subpixel ground truth.
            u,v = xx-dx,yy-dy
            moved = 130 + 27*np.sin(u*.38)*np.cos(v*.32)
            moved += 7*np.sin(.19*u+.27*v+phases[j,0])
            moved += 7*np.sin(.31*u-.17*v+phases[j,1])
            moved += 5*np.cos(.11*u+.13*v+phases[j,2])
            mask = ((np.abs(xx-cx-dx)<48)&(np.abs(yy-cy-dy)<52))
            rgb = np.stack([moved*.88,moved,moved*.96],axis=-1)
            frame[mask] = np.clip(rgb[mask],0,255).astype(np.uint8)
            if dropout and j==1 and 2.0 <= t < 3.2:
                frame[42:147,181:280] = [110,110,110]
        frames.append(frame)
    truth = dict(seed=20261005,fps=fps,seconds=seconds,frequencies_hz=[3,7],points=centers,
                 amplitude_3hz_y_px=[.4,.6],amplitude_7hz_y_px=[.12,.10],amplitude_3hz_x_px=[.18,.28],relative_phase_3hz_deg=60,
                 low_texture_point=[160,170],dropout_interval_s=[2,3.2] if dropout else None,
                 signal='dy=A3*cos(2π*3*t+φ)+A7*cos(2π*7*t-0.3); φ=[0,π/3]',codec='FFV1 lossless; uint8 rasterization')
    return np.stack(frames), truth


def write_demos(directory):
    directory = Path(directory)
    directory.mkdir(parents=True,exist_ok=True)
    for dropout in (False,True):
        name = 'tracking_dropout' if dropout else 'known_motion'
        frames,truth = synthesize(dropout)
        writer = cv2.VideoWriter(str(directory/(name+'.avi')),cv2.VideoWriter_fourcc(*'FFV1'),truth['fps'],(320,200))
        if not writer.isOpened():
            raise RuntimeError('Lossless FFV1 writer unavailable in this OpenCV build.')
        for frame in frames:
            writer.write(cv2.cvtColor(frame,cv2.COLOR_RGB2BGR))
        writer.release()
        (directory/(name+'.json')).write_text(json.dumps(truth,indent=2)+'\n')
