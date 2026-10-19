"""Assumed rectangular or swept/tapered Kirchhoff-Love planform.

Rayleigh-Ritz bending energy, not a membrane/spring-grid surrogate. Length is
in units of plate width and D = areal mass = 1 before frequency calibration.
See Leissa, NASA SP-160 (1969): https://ntrs.nasa.gov/citations/19700009156
One operating response cannot identify supports, material, thickness or mass.
"""
import math

import cv2
import numpy as np
from numpy.polynomial import Legendre
from numpy.polynomial.legendre import leggauss
from scipy.linalg import eigh


def validate_plate_settings(data):
    if not isinstance(data, dict):
        raise ValueError('Plate assumptions must be an object.')
    result = {}
    for key, default, low, high in [
        ('aspect_ratio', 2., .5, 12.), ('poisson', .33, 0., .49),
        ('taper_ratio', 1., .2, 2.), ('sweep_offset', 0., -2., 2.),
        ('mount_u', .5, .1, .9), ('mount_v', .5, .1, .9),
        ('mount_radius', .08, .02, .2), ('mount_stiffness', 10000., 10., 100000.),
        ('projection_angle_deg', 90., -180., 180.)]:
        try:
            value = float(data.get(key, default))
        except (TypeError, ValueError):
            raise ValueError(f'Plate {key} must be a finite number.') from None
        if not math.isfinite(value) or not low <= value <= high:
            raise ValueError(f'Plate {key} must be between {low} and {high}.')
        result[key] = value
    result['mounting'] = data.get('mounting', 'free')
    if result['mounting'] not in ('free', 'center', 'simply-supported', 'cantilever'):
        raise ValueError('Choose free edges, an elastic patch, simply supported edges, or a clamped root.')
    result['anchor_mode'] = data.get('anchor_mode')
    if result['anchor_mode'] is not None and (type(result['anchor_mode']) is not int or not 0 <= result['anchor_mode'] < 6):
        raise ValueError('Anchor mode must be automatic or one of the first six flexible modes.')
    corners = data.get('corners')
    if corners is not None:
        try:
            points = np.asarray(corners, dtype=float)
        except (ValueError, TypeError):
            raise ValueError('Choose four plate corners in perimeter order.') from None
        if points.shape != (4, 2) or not np.isfinite(points).all():
            raise ValueError('Choose four finite plate corners in perimeter order.')
        contour = points.astype(np.float32)
        if not cv2.isContourConvex(contour) or cv2.contourArea(contour) < 64:
            raise ValueError('Plate corners must form a convex, non-crossing outline of at least 64 analysis pixels².')
        result['corners'] = points.tolist()
    else:
        result['corners'] = None
    return result


def _basis(x, y, aspect, order, mounting, dx=0, dy=0):
    """Reference tensor polynomials with exact essential edge conditions."""
    def values(coordinate, length, derivative, spanwise):
        u = np.asarray(coordinate)/length
        rows = []
        for degree in range(order):
            p = Legendre.basis(degree)
            value = p.deriv(derivative)(2*u-1)*2**derivative
            if mounting == 'simply-supported':
                value *= u*(1-u)
                if derivative >= 1:
                    value += derivative*p.deriv(derivative-1)(2*u-1)*2**(derivative-1)*(1-2*u)
                if derivative == 2:
                    value -= 2*p(2*u-1)
            elif mounting == 'cantilever' and spanwise:
                # u² imposes w=0 and the entire gradient=0 at the root u=0.
                value *= u*u
                if derivative >= 1:
                    value += derivative*p.deriv(derivative-1)(2*u-1)*2**(derivative-1)*2*u
                if derivative == 2:
                    value += 2*p(2*u-1)
            rows.append(value/length**derivative)
        return rows
    px, py = values(x, aspect, dx, True), values(y, 1., dy, False)
    return np.einsum('ip,jp->pij', px, py).reshape(len(x), order**2)


def planform_xy(settings, uv):
    """Physical plane in root-chord units; camera perspective is separate."""
    uv = np.asarray(uv, dtype=float)
    u,v = uv[...,0],uv[...,1]
    chord = 1+(settings.get('taper_ratio',1.)-1)*u
    return np.stack([settings['aspect_ratio']*u, settings.get('sweep_offset',0.)*u+chord*v],axis=-1)


def planform_uv(settings, xy):
    xy = np.asarray(xy, dtype=float)
    u = xy[...,0]/settings['aspect_ratio']
    chord = 1+(settings.get('taper_ratio',1.)-1)*u
    with np.errstate(divide='ignore',invalid='ignore'):
        v = (xy[...,1]-settings.get('sweep_offset',0.)*u)/chord
    return np.stack([u,np.where(chord>1e-9,v,np.nan)],axis=-1)


def planform_basis(settings, uv, order):
    """Basis and physical Hessian, including the non-affine map derivatives."""
    uv = np.asarray(uv,float)
    a = settings['aspect_ratio']; d = settings.get('taper_ratio',1.)-1
    c = 1+d*uv[:,0]; g = settings.get('sweep_offset',0.)+d*uv[:,1]
    x,y = uv[:,0]*a,uv[:,1]
    def basis(dx=0,dy=0):return _basis(x,y,a,order,settings['mounting'],dx,dy)
    b,by = basis(),basis(dy=1)
    bxx,byy,bxy = basis(dx=2),basis(dy=2),basis(dx=1,dy=1)
    vx = -g/(a*c)
    vxx = 2*d*g/(a*a*c*c)
    vxy = -d/(a*c*c)
    return (b,bxx+2*vx[:,None]*bxy+vx[:,None]**2*byy+vxx[:,None]*by,
            byy/c[:,None]**2,bxy/c[:,None]+(vx/c)[:,None]*byy+vxy[:,None]*by)


def solve_plate(settings, order=11, count=8):
    """Consistent Ritz mass and isotropic plate bending matrices.

    U = D/2 int(w_xx²+w_yy²+2 nu w_xx w_yy+2(1-nu)w_xy²)dA.
    Free-edge moment/shear conditions are natural, not prescribed slopes.
    A finite mounting patch adds positive transverse spring energy, k/2 <w²>.
    """
    a, nu, mounting = settings['aspect_ratio'], settings['poisson'], settings['mounting']
    g, weights = leggauss(order+3)
    uu, vv = np.meshgrid((g+1)/2, (g+1)/2)
    uv = np.column_stack([uu.ravel(),vv.ravel()])
    chord = 1+(settings.get('taper_ratio',1.)-1)*uv[:,0]
    w = np.outer(weights, weights).ravel()*a*chord/4
    b,bx,by,bt = planform_basis(settings,uv,order)
    mass = b.T @ (w[:, None]*b)
    cross = bx.T @ (w[:, None]*by)
    stiffness = (bx.T @ (w[:, None]*bx) + by.T @ (w[:, None]*by)
                 + nu*(cross+cross.T) + 2*(1-nu)*bt.T @ (w[:, None]*bt))
    if mounting == 'center':
        # A square elastic patch, side = 2 radius in width units. Integrate
        # separately so moving a small patch does not jump quadrature cells.
        r = settings['mount_radius']
        cx, cy = planform_xy(settings,[settings['mount_u'],settings['mount_v']])
        patch_uv = planform_uv(settings,[[cx-r,cy-r],[cx+r,cy-r],[cx+r,cy+r],[cx-r,cy+r]])
        if not np.all((patch_uv > 0)&(patch_uv < 1)):
            raise ValueError('The mounting patch must lie inside the plate. Reduce its radius or move it inward.')
        mx, my = np.meshgrid(cx+g*r, cy+g*r)
        patch_uv = planform_uv(settings,np.column_stack([mx.ravel(),my.ravel()]))
        mb = _basis(patch_uv[:,0]*a,patch_uv[:,1],a,order,mounting)
        mw = np.outer(weights, weights).ravel()/4
        stiffness += settings['mount_stiffness'] * mb.T @ (mw[:, None]*mb)
    values, vectors = eigh((stiffness+stiffness.T)/2, mass)
    # Free plates retain exactly three rigid w=1,x,y coordinates, not modes.
    rigid = 3 if mounting == 'free' else 0
    if np.min(values) < -1e-4:
        raise ValueError('Plate eigensolve failed its stiffness positivity check.')
    values, vectors = values[rigid:rigid+count], vectors[:, rigid:rigid+count]
    if len(values) < count or np.any(values <= 1e-7):
        raise ValueError('The assumed plate has an unresolved rigid motion. Adjust mounting assumptions.')
    # Normalize each bending shape by a dense-domain maximum. Its modal mass
    # must change with this scaling; using M=I after peak normalization is wrong.
    gx, gy = np.meshgrid(np.linspace(0, a, 81), np.linspace(0, 1, 41))
    sample = _basis(gx.ravel(), gy.ravel(), a, order, mounting) @ vectors
    maxima = np.max(np.abs(sample), axis=0)
    vectors = vectors/maxima
    area = a*(1+settings.get('taper_ratio',1.))/2
    modal_mass = np.diag(vectors.T @ mass @ vectors)/area
    return dict(eigenvalues=values, vectors=vectors, modal_mass=modal_mass,
                order=order, aspect=a, mounting=mounting, rigid_modes_removed=rigid,
                area=area,taper_ratio=settings.get('taper_ratio',1.),sweep_offset=settings.get('sweep_offset',0.))


def evaluate(solution, uv):
    uv = np.asarray(uv, dtype=float).reshape(-1, 2)
    return _basis(uv[:, 0]*solution['aspect'], uv[:, 1], solution['aspect'],
                  solution['order'], solution['mounting']) @ solution['vectors']


def mac(observed, predicted):
    """Squared shape correlation at matched visible coordinates, not confidence."""
    return (observed @ predicted)**2 / np.maximum(1e-30, (observed @ observed)*np.sum(predicted**2, axis=0))


def build_plate_model(video, field, data):
    cfg = validate_plate_settings(data)
    if cfg['corners'] is None:
        raise ValueError('Set the four plate corners under Advanced before generating predicted modes.')
    h, w = video.frames.shape[1:3]
    corners = np.array(cfg['corners'], np.float32)
    if np.any(corners < 0) or np.any(corners[:, 0] >= w) or np.any(corners[:, 1] >= h):
        raise ValueError('The plate outline must be inside the current analysis image.')
    physical_corners = planform_xy(cfg,[[0,0],[1,0],[1,1],[0,1]]).astype(np.float32)
    homography = cv2.getPerspectiveTransform(corners, physical_corners)
    def uv_for(points):
        physical = cv2.perspectiveTransform(np.array(points, np.float32).reshape(-1, 1, 2), homography)[:, 0]
        return planform_uv(cfg,physical)
    candidates = [n for n in field['nodes'] if n['fit'][field['axis']]
                  and n['fit'][field['axis']]['phase_deg'] is not None]
    if not candidates:
        raise ValueError('Analyze a textured plate response before fitting predicted modes.')
    uv = uv_for([[n['x'], n['y']] for n in candidates])
    inside = np.all((uv >= 0) & (uv <= 1), axis=1)
    candidates = [n for n, good in zip(candidates, inside) if good]
    uv = uv[inside]
    if len(candidates) < 6 or np.ptp(uv[:, 0]) < .3 or np.ptp(uv[:, 1]) < .2:
        raise ValueError('Plate fitting needs six usable phase samples spread across the outline. Check the corners or analyze a larger region.')
    z = np.array([complex(*[n['fit'][field['axis']]['coefficients_px'][0],
                           -n['fit'][field['axis']]['coefficients_px'][1]]) for n in candidates])
    orientation = .5*np.angle(np.sum(z*z))
    observed = (z*np.exp(-1j*orientation)).real
    if np.max(np.abs(observed)) < 1e-8:
        raise ValueError('The plate has no usable standing projection at the anchor frequency.')
    general = cfg['taper_ratio'] != 1 or cfg['sweep_offset'] != 0 or cfg['mounting'] in ('center','cantilever')
    order = 15 if general else 11
    solution = solve_plate(cfg, order=order)
    sampled = evaluate(solution, uv)
    scores = mac(observed, sampled)
    anchor = int(np.argmax(scores[:6])) if cfg['anchor_mode'] is None else cfg['anchor_mode']
    frequencies = field['frequency_hz']*np.sqrt(solution['eigenvalues']/solution['eigenvalues'][anchor])
    coarse = solve_plate(cfg, order=order-2)
    coarse_ratios = np.sqrt(coarse['eigenvalues']/coarse['eigenvalues'][anchor])
    ratio_change = 100*np.abs(coarse_ratios/(frequencies/field['frequency_hz'])-1)
    signs = np.sign(observed @ sampled)
    signs[signs == 0] = 1
    solution['vectors'] *= signs
    grid = field['grid']
    positions = [[n['x'], n['y']] for n in field['nodes']]
    node_uv = uv_for(positions)
    node_inside = np.all((node_uv >= 0) & (node_uv <= 1), axis=1)
    shapes = np.zeros((len(node_uv),len(frequencies)))
    shapes[node_inside] = evaluate(solution,node_uv[node_inside])
    angle = math.radians(cfg['projection_angle_deg'])
    direction = np.array([math.cos(angle), math.sin(angle)])
    component = 0 if field['axis'] == 'x' else 1
    if abs(direction[component]) < .15:
        raise ValueError('Projection direction must include the selected measurement axis. Choose an angle closer to that axis.')
    direction /= direction[component]
    nodes = [dict(index=n['index'], x=n['x'], y=n['y'],
                  shape=(shapes[i, anchor]*direction).tolist() if node_inside[i] else None,
                  modes=shapes[i].tolist() if node_inside[i] else None)
             for i, n in enumerate(field['nodes'])]
    valid = [n for n in nodes if n['shape'] is not None]
    if len(valid) < 2:
        raise ValueError('The outline contains too few grid points for virtual taps.')
    default = max(valid, key=lambda n: abs(n['modes'][anchor]))['index']
    xx, yy = np.meshgrid(np.arange(w, dtype=np.float32), np.arange(h, dtype=np.float32))
    pixel_uv = uv_for(np.column_stack([xx.ravel(), yy.ravel()]))
    support = np.all((pixel_uv >= 0) & (pixel_uv <= 1), axis=1).reshape(h, w)
    dense = np.zeros((h*w, len(frequencies)), np.float32)
    dense[support.ravel()] = evaluate(solution, pixel_uv[support.ravel()])
    # Feather the assumed outline only for display; traces use the unfeathered model.
    feather = np.clip(cv2.distanceTransform(support.astype(np.uint8), cv2.DIST_L2, 3)/1.5, 0, 1)
    dense = dense.reshape(h, w, -1)*feather[:, :, None]
    thumb_u, thumb_v = np.meshgrid(np.linspace(0, 1, 25), np.linspace(0, 1, 13))
    thumbs = evaluate(solution, np.column_stack([thumb_u.ravel(), thumb_v.ravel()]))
    modes = [dict(index=i, frequency_hz=float(f), frequency_ratio=float(f/field['frequency_hz']),
                  anchor=i == anchor, mac=float(scores[i]), modal_mass=float(solution['modal_mass'][i]),
                  basis_change_percent=float(ratio_change[i]),
                  thumbnail=np.round(thumbs[:, i].reshape(13, 25), 3).tolist())
             for i, f in enumerate(frequencies)]
    fraction = float(np.sum(observed**2)/np.sum(abs(z)**2))
    model = dict(kind='plate', frequency_hz=field['frequency_hz'], axis=field['axis'], nodes=nodes,
                 default_node=default, grid=grid, modes=modes, anchor_mode=anchor,
                 fit_mac=float(scores[anchor]), fit_samples=len(candidates),
                 basis_order=order, max_basis_change_percent=float(max(ratio_change)),
                 reference_amplitude_source_px=float(max(abs(z))),
                 standing_phase_fraction=fraction, interpolated_support_fraction=float(support.mean()),
                 plate=cfg, projection=direction.tolist(),
                 interpretation='Predicted thin-plate modes anchored to an assumed 95 Hz operating-response mode; not measured higher modes or a force-calibrated twin',
                 assumptions=[
                     'Uniform isotropic flat thin plate, linear transverse bending; no thickness, material or mass identified.',
                     f"Assumed span/root chord {cfg['aspect_ratio']}, tip/root chord {cfg['taper_ratio']}, tip leading-edge offset/root chord {cfg['sweep_offset']}. Physical planform is user-assumed, separate from camera perspective.",
                     'Corners are root-leading, tip-leading, tip-trailing, root-trailing. The root edge joins corners 4 and 1.',
                     f"Mounting: {cfg['mounting']}. Cantilever means zero displacement and slope along the entire root, with the other three edges free. Mounting and support compliance are not identified.",
                     'A real common-phase projection of visible accepted patches is compared with the first six flexible model modes by squared MAC.',
                     'The chosen anchor is assumed to be a natural mode at the selected frequency; all model frequencies share that one scale factor.',
                     'MAC measures agreement at sparse visible points, not confidence, uniqueness or validation of higher-mode predictions.',
                     f'Only eight flexible modes are retained; free-plate rigid modes are excluded. Ritz orders {order-2} and {order} change frequency ratios by up to {max(ratio_change):.2f}%; this is a convergence indicator, not an error bound.',
                     'Modal masses use chosen total plate mass 1 with uniform areal density. No kilograms, newtons, physical stiffness or force calibration.',
                     'Wing-like planforms remain flat isotropic plates: no spars, ribs, laminate anisotropy, camber, pretwist, fuel/engine masses, aerodynamics or aeroelastic flutter model.',
                     'Each selected mode receives the same relative point impulse weighted by its local shape and divided by its modal mass.',
                     'Damping is the same user-assumed ratio in every mode; no damping is measured here.',
                     'Video texture is warped across the assumed plate outline, including unmeasured areas, along one assumed image projection; background remains fixed.',
                     'Frequencies above camera Nyquist are model predictions, not recovered video content. All modes share one physical clock.',
                     'Display gain, softened outline and automatic playback slowdown affect visualization only. Traces are simulated source pixels.'])
    model['interpretation'] = model['interpretation'].replace('95 Hz', f"{field['frequency_hz']:.3f} Hz")
    maps = dict(xx=xx, yy=yy, support=support, modes=dense, projection=direction)
    return model, maps
