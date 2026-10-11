# Modal Camera — local recorded-video prototype

A Python + Flask + OpenCV app for selecting a recorded video, exploring an original-motion spectrum, magnifying a temporal frequency band, and measuring peak amplitude and relative phase at selected locations. Runs on `127.0.0.1`, with all assets and video processing on your computer. No camera/NI hardware control, external uploads, CDN, telemetry or deployment.

## Launch on this Mac

The installed environment is already in this folder:

```zsh
cd /Users/stephenwells/Documents/DevOps/modal-camera
.venv/bin/python app.py
```

Open **http://127.0.0.1:8765**. Stop with Ctrl+C. If that port is in use, run `app.py --port 8766` and open that port. `start.command` is an optional Finder launcher.

For a fresh macOS/Linux installation, use company-approved Python 3.9–3.12 (3.11 recommended), then:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python app.py
```

## Transfer to a Windows work PC

Copy this project folder, including `demo_videos`, but **omit `.venv`, caches and your private videos**. Virtual environments cannot be transferred between operating systems. Use an approved Python **3.11** installation. Setup downloads only Python packages; subsequent application use works offline. No admin rights are required by the project, but follow your company's software policy.

In PowerShell from the copied folder:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
```

Open **http://127.0.0.1:8765** in Edge or Chrome. No PowerShell activation or execution-policy change is needed. Windows execution has not been tested here; the code uses portable Python/OpenCV and local HTTP, with no macOS runtime dependency.

## First session

1. Click **Known-motion demo**. P1/P2 are selected, analyzed and amplified automatically. The deterministic 60 fps, 6 s clip has Y motion at **3 Hz**, peak **0.40/0.60 source pixels**, with P2 leading P1 by **60°**, plus **7 Hz** motion at **0.12/0.10 pixels**.
2. Drag the green spectrum edges or the entire band; click a spectrum position to choose the fit frequency. Click **Apply band & gain** to reconstruct the visualization. For the 7 Hz motion, use approximately **6.5–7.5 Hz**, set the fit frequency to **7**, then **Analyze original points**. This keeps visualization band and measurement frequency explicit.
3. **Choose a recorded video**. Mark textured corners in the original image, then analyze. Select X (right) or Y (down), and a fit frequency. Raw source-pixel traces and sinusoidal fits never use the amplified video.
4. Use **Amplification ROI** and drag a rectangle to localize visualization; **Full frame** clears it. ROI does not crop or alter point measurements. Points must be at least 16 analysis pixels from the edges; up to eight points use a 31 px registration window.
5. Try **Tracking dropout demo**: P2 is occluded from 2.0–3.2 s. Rejected samples appear as gaps, the affected FFT is withheld, and amplitude/phase are withheld when accepted fit coverage falls below 80%.
6. For camera-translation diagnostics, mark a textured point on **stationary structure last**, then check **Subtract last point as stationary camera reference** and analyze. Raw traces are retained in JSON. This is translation subtraction only; it does not stabilize images or correct rotation/perspective. A moving reference would subtract real motion.
7. Optional calibration is **mm per source pixel**, determined independently at the relevant plane. The table then displays mm as well as pixels. JSON/CSV retain source-pixel values; record your calibration separately. A single scale cannot resolve perspective/depth or out-of-plane motion.
8. Export analysis JSON (metadata, accepted traces, per-frame quality metrics, fits and render settings) or CSV (time, displacement, acceptance, forward/backward error and correlation). Exports are browser downloads to your computer.

### Frequency response views and fitted animation

After **Apply band & gain**, use **Response view** above the right-hand video:

- **Frequency heatmap** overlays selected-band strength on the original video.
- **Isolated responding regions** keeps the magnified video visible only where the selected-band signal passes the sensitivity threshold. Increase **Sensitivity** to include weaker regions.

Both use a stable, full-clip RMS map of the **unamplified** reconstructed bandpassed Laplacian luminance, excluding the filter's edge guard. Changing magnification gain does not change the map. The display reference is the map's 99th percentile, with color saturation above it. Sensitivity sets a threshold from 75% of this reference at 0 sensitivity to zero at 100, with a smooth transition of 12% of the reference. The PNG used for display quantizes this normalized map to 8 bits. This threshold is a display selection, not a measured noise floor or detection confidence. The mask does not blink at each oscillation's zero crossing. Brightness response depends on texture and can include illumination changes; dark regions are not proof of zero displacement.

For displacement, choose **Fit frequency** (e.g. 95 Hz with the appropriate capture timebase) and **Displacement axis**, then click **Build displacement & phase map**. No manually selected points are required. The map samples a regular grid, normally 24 analysis pixels apart, with at most 256 locations and 31 px tracking windows. An ROI limits grid centers; windows can extend beyond the ROI. Fits use original X/Y displacement and source-pixel scaling, with the same tracking gates, 80% accepted coverage, 24 accepted samples, three-cycle minimum, and one-cycle edge exclusion as point measurements. Changing the fit frequency reuses original grid traces when possible.

- **Local displacement amplitude** shows selected-axis peak amplitudes at measured patches. Hover/click a circle for amplitude, relative phase, accepted frames and fit residual. Optional calibration also displays mm. Crosses indicate withheld fits.
- **Local relative phase** shows cyclic phase color relative to P1 if usable, otherwise the strongest measurable selected-axis grid response. You can explicitly select P1 or strongest sample. Positive phase leads the reference. Weak phases are withheld; a valid low-amplitude fit is not automatically a valid phase measurement. The reported harmonic power fraction `A²/(A²+2*residual_RMS²)` is descriptive, not statistical coherence or uncertainty.
- **Modal animation · fitted response** synthesizes just the fitted harmonic X/Y motion, using frame 0 as the texture. **Animate** plays a one-second cycle independent of capture fps. Scrub cycle phase or change **Animation displacement gain** (0–20×). The reference's selected-axis response reaches its positive maximum at phase 0°. Arrows show sampled motion; a first-order inverse image warp interpolates only inside cells with four accepted fits carrying measurable X or Y motion. Missing cells are not filled or extrapolated. Sensitivity also suppresses weak selected-axis responses in the animation. Large display gains can distort the interpolated warp.

The spatial view is a **sampled camera-plane operating deflection pattern at one frequency**, not a structural eigenmode identification or an independently measured displacement at every pixel. Zero/weak response, low texture, out-of-plane projection and rejected tracking remain distinct limitations. Camera-reference subtraction uses the last selected original point and corrects X/Y translation only; images are not stabilized. Frequency/axis/reference/point/ROI/timebase changes invalidate the browser's spatial map until rebuilt. Band visualization and single-frequency displacement fitting remain independent.

**Export analysis JSON** now also includes spatial nodes, X/Y cosine/sine coefficients, fit residuals, phase reference, ROI, timing basis and display settings; it can be used with a spatial map alone. **Export spatial samples CSV** exports one row per grid sample in source pixels. The original point-trace CSV remains available separately.

## Timebase matters — especially slow-motion or archival clips

The default frequency is **encoded video-time Hz**. Frame rate metadata cannot establish a physical capture rate, absence of aliasing, absence of synthesized frames, or real-time playback. Adjacent identical frames are flagged; irregular decoder timestamps are rejected; unavailable timestamps are disclosed. Interpolated or missing frames are not reliably detected.

If you know a documented original capture frame rate, enter **Known original capture fps**, check the explicit one-frame-per-captured-sample assumption, and click **Set analysis timebase**. The checkbox records an assumption; it does not claim that the frame mapping was independently verified. Physical-frequency validation still requires verifying that mapping. Bands and fit frequency scale with the rate change; analyze and apply again. Playback still uses the encoded rate. This is an explicit user assumption, preserved in exported metadata, not an automatically verified physical timebase. Leave the override blank to restore encoded time.

For the Shuttle rear-wing recording, an expected **4–6 Hz** is a hypothesis: first inspect the full measured spectrum and stationary-reference motion. Do not select a peak solely because it falls in that range. Original capture/playback rate must be established to interpret physical Hz. That recording was not available and has not been validated.

## Methods and boundaries

**Visualization:** a locally implemented **linear Eulerian Laplacian-pyramid luminance magnifier**, inspired by [Wu et al., SIGGRAPH 2012](https://people.csail.mit.edu/mrub/evm/). Each original frame is decomposed into up to four Laplacian levels. A zero-phase FFT temporal bandpass is applied at fixed spatial locations to each level; added gain `α` times each filtered level is reconstructed and added to the original luminance. The coarsest Gaussian residual is excluded; chroma is retained. The filter has unit response inside the selected band, one-record-bin raised-cosine shoulders outside, and reflection padding. Padding does **not** improve true frequency resolution. ROI edges are feathered inside the selection. Gain is capped at 20; start with 2–4 or lower. Clipped luminance is counted and flagged. Ideal small-motion displacement factor is approximately `1+α`, with spatial-scale and scene dependence.

This is **not dense phase-based magnification**. The authors' [phase-based method](https://people.csail.mit.edu/mrub/vidmag/) is a possible future improvement. This linear implementation amplifies lighting fluctuations too; large amplified motion violates its first-order approximation, causing halos, ghosting, saturation and inaccurate apparent displacement. It does not replace magnification with global video wobble or warp from a few tracked points. Magnified images are visualization only.

**Measurement:** [pyramidal Lucas–Kanade](https://docs.opencv.org/4.x/d4/dee/tutorial_optical_flow.html) registers each selected point from the fixed first original frame to each later original frame. This avoids accumulating interframe drift and can reacquire after an occlusion, but is intended for small bounded motion, approximately rigid texture within the window, stable lighting and a fixed camera. Quality acceptance requires:

- Both forward and reverse LK status, inside-image patch, **forward/backward error <0.35 analysis px**.
- **Normalized patch correlation >0.85**, **raw brightness RMS residual <22 gray levels**.
- Reference and current patch **mean minimum gradient eigenvalue >0.0001** (texture in two directions).

These heuristic metrics are exposed per frame; they are useful warnings, **not uncertainty bounds or guarantees**. Changing texture, repeated patterns, motion blur, compression, rolling shutter, occlusion, exposure changes and camera motion can fool or invalidate tracking. Thin strings with a strong aperture problem may be rejected or biased; use edges/intersections with two-direction texture or treat quantitative results cautiously.

Fully accepted original displacement traces have two spectral views. The default **PSD** uses a one-sided, full-record periodic-Hann periodogram with linear detrending and density scaling in **source pixels²/Hz** (`scipy.signal.periodogram`). Its bin spacing is `fps/N`, Hann equivalent noise bandwidth is `1.5*fps/N`, and there is no zero padding or Welch averaging. The displayed integrated PSD RMS is the square root of the density sum times bin width (window-weighted, detrended RMS). Log plotting shows six decades; its display floor is not a measured noise floor. Each point has its own color and clickable strongest local peak bins. For the assumed 600 fps guitar recording, the 0.5 s record gives 2 Hz bins and 3 Hz Hann ENBW; this short transient record is a descriptive spectral estimate, not a stationary-process confidence bound. Optional calibration changes the displayed PSD by the square of mm-per-source-pixel; JSON preserves the source-pixel PSD and method metadata. The alternate **peak amplitude spectrum** retains the detrended Hann FFT, scaled to approximate peak sinusoidal pixels. Rejected traces are withheld in both views; gaps are never interpolated for spectra. If camera-reference subtraction is enabled, spectra use those explicitly corrected original displacement traces. Fits at the explicitly selected frequency use accepted original displacement samples and least squares: `x(t)=a*cos(2πft)+b*sin(2πft)+offset+drift`. Peak amplitude is `hypot(a,b)`; phase is `atan2(-b,a)`; relative phase references P1, positive = leads P1. At least three cycles and 24 accepted samples after excluding one cycle at each end are required; accepted coverage must be ≥80%. Weak motion has its phase withheld. A dominant FFT bin is not a sub-bin resonance estimate. Fitting one frequency in a multicomponent signal can leave a significant residual.

Measurements are **camera-plane projections** in source pixels, rescaled if analysis was downsampled. Motion patterns from an operating video, filtered or otherwise, are **not identified structural modes**. Modal identification requires additional assumptions and validation beyond this prototype.

**Input and resource limits:** 512 MiB per upload request (file plus multipart overhead), at least 32 and at most 600 decoded frames; max analysis width 640 and temporal pixel budget 24 million. The upload limit bounds the encoded file transfer; the frame and pixel limits bound decoded processing memory. Larger spatial inputs are downsampled with a visible warning; longer clips are rejected with instructions to trim, never silently truncated. No audio is processed. Supported file containers do not guarantee every codec is supported. OpenCV decodes MP4/MOV/AVI/MKV/WebM/M4V where the installed codec backend permits. Frames are replayed as local JPEGs using a shared frame index; the browser may skip display frames to keep time and is not a precision playback/capture instrument. Only one clip is retained in RAM, and a new load invalidates old analysis/render state. Uploaded inputs use a temporary local file which is deleted after decoding; originals on disk are never modified.

## Guitar example

The requested original MIT guitar file is in `data/examples/guitar.mp4` with a source/inspection JSON beside it. It is an optional external research example, **excluded from git/redistribution by default**. Source: [MIT guitar original](https://people.csail.mit.edu/mrub/evm/video/guitar.mp4). Consult the source's terms before sharing it.

The [paper's Table 1](https://people.csail.mit.edu/mrub/papers/vidmag.pdf#page=6) reports **600 fps capture**, and amplification bands **72–92 Hz / 100–120 Hz**. The actual downloaded file is **432×192, 300 frames, 29.970 fps encoded playback**: default video-time frequencies are smaller by approximately `600/29.970 ≈20.02` under the one-frame-per-sample assumption. At 600 assumed analysis fps, the 300 samples span only **0.5 s**, with **2 Hz** frequency-bin resolution. Enter 600 only when accepting that timing assumption. The paper's bands are useful comparison ranges, not preselected measured peaks. Thin guitar strings and plucking transients are challenging for this point tracker; synthetic clips remain the quantitative ground truth.

## Tests and source layout

```sh
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
node --check static/app.js  # optional syntax check if Node is installed
```

Windows equivalents use `.\.venv\Scripts\python.exe`. Node is not needed to run the app.

- `modal_camera/processing.py`: bounded decode, temporal filtering, pyramid magnification, tracking/quality and harmonic analysis.
- `modal_camera/response.py`: sampled original-displacement harmonic field, phase references and supported-cell animation warping.
- `modal_camera/synthetic.py`: continuous translated seeded textures and lossless FFV1 demo generation; regenerate with `python app.py --make-demos`.
- `app.py`: loopback-only API, state, local import and exports.
- `static/`, `templates/`: dependency-free browser interface; no build step.
- `tests/`: known frequency/amplitude/phase, X/Y, dropout, low texture, band rejection/display response, ROI, gain, input errors, repeated loads, timing and export checks.
- `evidence/`: local test report, numerical results and UI screenshots/check notes.

The implementation is original prototype code; no MIT source code or archive was downloaded or incorporated.
