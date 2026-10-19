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

## Main workflow

1. **Open video.** New recordings start at a **95 Hz target with a 4 Hz bandwidth**. Calibration and manual points reset for each recording. The introductory panel collapses after loading. **Try the 3 Hz demo** starts a deterministic example and runs the complete analysis automatically.
2. **Confirm timing.** Choose encoded playback timing or a known original capture rate. A capture override requires the explicit one-encoded-frame-per-captured-sample assumption. Confirmed timing collapses to a summary; **Change** reopens its controls. This does not independently verify physical timing. Your target frequency stays unchanged when the timebase changes.
3. **Choose the response.** The original-displacement PSD appears here after timing confirmation. By default, with no manual measurement points, it averages the individual PSDs of complete, quality-accepted spatial-grid tracks; opposite-phase motion does not cancel. Click a peak button or the plot to set the target and linked band, or enter a frequency. **Measure PSD / Refresh PSD** updates it after axis, ROI, point or camera-reference changes. The PSD stays visible when you change the target, bandwidth or magnification. **Analyze response** then filters the band, analyzes any optional original points, and builds the sampled displacement/phase field. Manual points are not required. The band follows target ± half the bandwidth by default. For the plate experiment, 95 Hz and 4 Hz width selects 93–97 Hz. The current analysis rate must support that band; a 30 fps encoded clip cannot represent 95 analysis-time Hz without an appropriate capture-time assumption.
4. **Explore.** Aligned previews offer Heatmap, Isolated, Amplitude, Phase, Animation, and Magnified views. **Show weaker responses** changes the display threshold. Animation has a separate display gain and a one-second fitted cycle. Select a measured patch from the accessible sample selector, hover/click it, or focus the response image and use arrow keys to inspect amplitude, relative phase, accepted frames and residuals.
5. **Export.** Choose an available MP4 or data format and click **Export**. A permanent **Save** link is provided for the prepared file. Errors stay in the workspace. Point traces CSV becomes available only when manual points have been analyzed.

### Choose the PSD sampling location

Sampling centers are overlaid on **Original** by default. Dots mark fixed **frame-0 reference positions**, rather than moving per-frame tracking markers. Green means a complete track usable for the current PSD; a cross marks an incomplete selected track, and gray marks another available location. **Show samples** hides or shows this overlay. The source caption above the PSD names the active selection, and Analysis JSON includes each sample's coordinates, selection and quality eligibility.

- **Click a dot** to compute the PSD from that patch. **Point PSD** provides the same selection with a keyboard-accessible list. **Pick a point** lets you choose any textured location, or use arrow keys and Enter on the original canvas. A white outline shows the selected nominal 31-pixel reference window.
- **Select plate / region** pauses at frame zero; drag a rectangle around the plate. **Region coordinates** is the numeric alternative. The region must be at least 32 by 32 analysis pixels. Nominal 31-pixel reference windows fit inside it; the pyramidal tracker can use broader image context, and a rectangle does not segment the plate's outline. Escape cancels an unfinished selection.
- **Whole frame** restores the automatic full-frame grid. Selecting a point or region updates the PSD automatically, preserving the target, high-pass cutoff, measurement points, response ROI, magnified video and amplitude/phase results. These are PSD-only selections. Until an explicit PSD source is chosen, Advanced measurement points (or the Advanced ROI when no points exist) retain their earlier behavior.

Selection and sample quality recover on reload while the local session is running. Selecting geometry uses frame zero so the click locations correspond to the displayed reference image. Rejected samples are never filled to obtain a spectrum.

### PSD high-pass and layout

In **Choose the response**, enable **High-pass PSD** to suppress slow displacement components before estimating the spectrum. The initial cutoff is **5 Hz**; edit **Cutoff / Hz** and click **Apply PSD** to use another value. Turning the checkbox off restores the original spectrum. The filter defaults off for new recordings and its applied value is shown in the PSD summary. Peak selection, response fitting and the linked band remain independent of this cutoff.

This filters complete original displacement traces after linear detrending, using a fourth-order Butterworth high-pass in second-order-section form, applied forward and backward with odd reflection padding. The two-pass amplitude gain at the cutoff is **−6.02 dB**; expect attenuation near the cutoff and finite-record edge effects. The cutoff must span at least two record bins and remain below Nyquist. Changing timing disables a cutoff that becomes invalid. Low-frequency structural motion is suppressed too; the filter does not establish that it was camera jitter. Gaps remain rejected. **Amplitude/phase fits, point traces, response previews and MP4s continue using their existing original-motion pipeline**. Analysis JSON records the spectrum filter and method.

Confirmed timing occupies a compact full-width strip. On desktop the PSD sits beside target/band controls, avoiding a tall spectrum tile next to a short timing tile. Narrow screens stack these sections. Original and response video tiles retain equal dimensions and the recording's aspect ratio.

The **Cyan Lab** theme adds near-black surfaces, cyan/violet action gradients, restrained glow and a little translucent panel depth. The existing step-by-step layout and equal-sized previews remain in place. Scientific heatmap, amplitude, phase and signed-displacement color scales are unchanged. Hover effects respect reduced-motion preferences.

### Advanced

Expand **Advanced** for X/Y axis, calibration in mm per source pixel, phase reference, stationary-camera translation subtraction, independent band edges, added magnification gain, manual points, ROI, spectral display options and method details, quality notes and point traces. Turn off **Center the band on the target frequency** to use an independent visualization band. Measurements always use original frames.

For points, enable **Add points**, then click textured corners or focus the original image, move its cursor with arrow keys (Shift moves ten analysis pixels), and press Enter. Numeric X/Y inputs provide another keyboard path. ROI can be drawn or entered numerically. Points must be at least 16 analysis pixels from each image edge; up to eight are supported. Camera subtraction needs a stationary last point and at least one other point. Calibration belongs to the recording and plane; opening another clip clears it.

The known-motion demo has 3 Hz Y motion of 0.40/0.60 source-pixel peak amplitude, with P2 leading P1 by 60 degrees, plus 7 Hz motion at 0.12/0.10 pixels. Set target 7 and bandwidth 1, then analyze again to compare. The dropout demo is available under Advanced and withholds P2 measurements when its accepted coverage is insufficient.

### Result freshness and recovery

Scientific-setting edits immediately clear affected response results and disable their exports. The target-independent PSD remains available across target, band, gain, phase-reference and calibration edits; axis, sampling, camera-reference, PSD high-pass and timebase changes invalidate it. Changing only the PSD high-pass preserves response fits and rendered views. Analysis JSON includes this spectrum even before a response fit has been computed. Settings and result dependencies are checked on the local server using a revision; an older tab cannot overwrite a newer session. Data exports cannot silently include an incompatible spatial map. Display-only settings and calibration can change without recomputing original traces. Prepared downloads are immutable snapshots of their export settings.

Refreshing the page recovers the active clip, settings, calibration, playback frame and available results **while the same local server remains running**. One shared session is held in RAM. Replacing the clip or stopping the server ends that recovery; this is not a persistent project-file format. The app reports processing stages. **Stop after this step** waits for the current calculation, then skips later stages and clears partial results. Video encoding retains its two-minute limit.

### Interpretation and video exports

Heatmap and isolation use a stable RMS map of the **unamplified** bandpassed Laplacian luminance, excluding the filter edge guard. Its reference is the 99th percentile; the normalized display map is quantized to 8 bits. Sensitivity selects a threshold between 75 percent of that reference and zero, with a smooth 12-percent transition. It is a display selection, not a measured noise floor or confidence. Brightness response depends on texture and illumination. Isolation masks magnified frames, so other frequencies can remain inside the selected regions.

The displacement field samples original frames on a grid, normally 24 analysis pixels apart, capped at 256 overlapping tracking windows. Fits use the same quality gates, 80-percent accepted coverage, 24 accepted samples, three-cycle minimum and one-cycle edge exclusion as point measurements. Weak phases are withheld. Positive relative phase leads the reference. Animation synthesizes fitted X/Y motion about frame zero and interpolates only inside supported four-sample cells. Dark or rejected regions are not proof of a structural node. The result is a **sampled camera-plane operating response**, not an identified eigenmode or a displacement measurement at every pixel. The reported harmonic power fraction is descriptive, not statistical coherence.

Heatmap and isolated MP4s retain **every decoded frame at encoded playback fps**, independently of assumed capture fps, current scrub position or preview speed. Animation MP4s contain **four cycles at one display cycle per second, 30 fps**, beginning at the selected phase. All files are silent H.264/yuv420p, annotated with frequency/band, sensitivity, display gain and timing assumptions. Analysis images fit within 640×480, with separate annotation space. Compression is for sharing; exported pixels are not displacement measurements.

The pinned [imageio-ffmpeg](https://github.com/imageio/imageio-ffmpeg) dependency supplies the encoder in standard platform wheels. Reinstall requirements when upgrading an older copy. MP4 uses [FFmpeg fast start](https://ffmpeg.org/ffmpeg-formats.html#MOV_002fMPEG_002d4_002fISOMBFF-muxers). One encoding runs at a time; temporary files are cleaned on success/failure. The latest prepared video and data download are held in RAM until replaced, a new clip loads, or the app stops. Windows execution remains untested here.

## Timebase matters — especially slow-motion or archival clips

The default frequency is **encoded video-time Hz**. Frame rate metadata cannot establish a physical capture rate, absence of aliasing, absence of synthesized frames, or real-time playback. Adjacent identical frames are flagged; irregular decoder timestamps are rejected; unavailable timestamps are disclosed. Interpolated or missing frames are not reliably detected.

If you know a documented original capture frame rate, choose **Known original capture rate**, enter it, accept the explicit one-frame-per-captured-sample assumption, and **Confirm timing**. The checkbox records an assumption; it does not establish a verified frame mapping. The target frequency and bandwidth remain at your selected values; analyze again after the timing change. Playback uses the encoded rate. Choose **Encoded playback rate** to restore encoded analysis time.

For the Shuttle rear-wing recording, an expected **4–6 Hz** is a hypothesis: first inspect the full measured spectrum and stationary-reference motion. Do not select a peak solely because it falls in that range. Original capture/playback rate must be established to interpret physical Hz. That recording was not available and has not been validated.

## Methods and boundaries

**Visualization:** a locally implemented **linear Eulerian Laplacian-pyramid luminance magnifier**, inspired by [Wu et al., SIGGRAPH 2012](https://people.csail.mit.edu/mrub/evm/). Each original frame is decomposed into up to four Laplacian levels. A zero-phase FFT temporal bandpass is applied at fixed spatial locations to each level; added gain `α` times each filtered level is reconstructed and added to the original luminance. The coarsest Gaussian residual is excluded; chroma is retained. The filter has unit response inside the selected band, one-record-bin raised-cosine shoulders outside, and reflection padding. Padding does **not** improve true frequency resolution. ROI edges are feathered inside the selection. Gain is capped at 20; start with 2–4 or lower. Clipped luminance is counted and flagged. Ideal small-motion displacement factor is approximately `1+α`, with spatial-scale and scene dependence.

This is **not dense phase-based magnification**. The authors' [phase-based method](https://people.csail.mit.edu/mrub/vidmag/) is a possible future improvement. This linear implementation amplifies lighting fluctuations too; large amplified motion violates its first-order approximation, causing halos, ghosting, saturation and inaccurate apparent displacement. It does not replace magnification with global video wobble or warp from a few tracked points. Magnified images are visualization only.

**Measurement:** [pyramidal Lucas–Kanade](https://docs.opencv.org/4.x/d4/dee/tutorial_optical_flow.html) registers each selected point from the fixed first original frame to each later original frame. This avoids accumulating interframe drift and can reacquire after an occlusion, but is intended for small bounded motion, approximately rigid texture within the window, stable lighting and a fixed camera. Quality acceptance requires:

- Both forward and reverse LK status, inside-image patch, **forward/backward error <0.35 analysis px**.
- **Normalized patch correlation >0.85**, **raw brightness RMS residual <22 gray levels**.
- Reference and current patch **mean minimum gradient eigenvalue >0.0001** (texture in two directions).

These heuristic metrics are exposed per frame; they are useful warnings, **not uncertainty bounds or guarantees**. Changing texture, repeated patterns, motion blur, compression, rolling shutter, occlusion, exposure changes and camera motion can fool or invalidate tracking. Thin strings with a strong aperture problem may be rejected or biased; use edges/intersections with two-direction texture or treat quantitative results cautiously.

Fully accepted original displacement traces have two spectral views. The default **PSD** uses a one-sided, full-record periodic-Hann periodogram with linear detrending and density scaling in **source pixels²/Hz** (`scipy.signal.periodogram`). Its bin spacing is `fps/N`, Hann equivalent noise bandwidth is `1.5*fps/N`, and there is no zero padding or Welch averaging. The displayed integrated PSD RMS is the square root of the density sum times bin width (window-weighted, detrended RMS). Log plotting shows six decades; its display floor is not a measured noise floor. Selected points have their own colors. Without manual points, the plot shows a spatial mean of individual PSDs, with accepted/total track counts. Clickable peak buttons list the strongest local bins of the mean PSD. The last stationary camera-reference point, when enabled, is subtracted and excluded from this mean. This full-band spectrum is independent of the response target and magnification; changing the target does not filter it. For the assumed 600 fps guitar recording, the 0.5 s record gives 2 Hz bins and 3 Hz Hann ENBW; this short transient record is a descriptive spectral estimate, not a stationary-process confidence bound. Optional calibration changes the displayed PSD by the square of mm-per-source-pixel; JSON preserves the source-pixel PSD and method metadata. The alternate **peak amplitude spectrum** retains the detrended Hann FFT, scaled to approximate peak sinusoidal pixels. Rejected traces are withheld in both views; gaps are never interpolated for spectra. If camera-reference subtraction is enabled, spectra use those explicitly corrected original displacement traces. Fits at the explicitly selected frequency use accepted original displacement samples and least squares: `x(t)=a*cos(2πft)+b*sin(2πft)+offset+drift`. Peak amplitude is `hypot(a,b)`; phase is `atan2(-b,a)`; relative phase references P1, positive = leads P1. At least three cycles and 24 accepted samples after excluding one cycle at each end are required; accepted coverage must be ≥80%. Weak motion has its phase withheld. A dominant FFT bin is not a sub-bin resonance estimate. Fitting one frequency in a multicomponent signal can leave a significant residual.

Measurements are **camera-plane projections** in source pixels, rescaled if analysis was downsampled. Motion patterns from an operating video, filtered or otherwise, are **not identified structural modes**. Modal identification requires additional assumptions and validation beyond this prototype.

**Input and resource limits:** 512 MiB per upload request (file plus multipart overhead), at least 32 and at most 600 decoded frames; max analysis width 640 and temporal pixel budget 24 million. The upload limit bounds the encoded file transfer; the frame and pixel limits bound decoded processing memory. Larger spatial inputs are downsampled with a visible warning; longer clips are rejected with instructions to trim, never silently truncated. No audio is processed. Supported file containers do not guarantee every codec is supported. OpenCV decodes MP4/MOV/AVI/MKV/WebM/M4V where the installed codec backend permits. Frames are replayed as local JPEGs using a shared frame index; the browser may skip display frames to keep time and is not a precision playback/capture instrument. Only one clip is retained in RAM, and a new load invalidates old analysis/render state. Uploaded inputs use a temporary local file which is deleted after decoding; originals on disk are never modified.

## Guitar example

The requested original MIT guitar file is in `data/examples/guitar.mp4` with a source/inspection JSON beside it. It is an optional external research example, **excluded from git/redistribution by default**. Source: [MIT guitar original](https://people.csail.mit.edu/mrub/evm/video/guitar.mp4). Consult the source's terms before sharing it.

The [paper's Table 1](https://people.csail.mit.edu/mrub/papers/vidmag.pdf#page=6) reports **600 fps capture**, and amplification bands **72–92 Hz / 100–120 Hz**. The actual downloaded file is **432×192, 300 frames, 29.970 fps encoded playback**: default video-time frequencies are smaller by approximately `600/29.970 ≈20.02` under the one-frame-per-sample assumption. At 600 assumed analysis fps, the 300 samples span only **0.5 s**, with **2 Hz** frequency-bin resolution. Enter 600 only when accepting that timing assumption. The paper's bands are useful comparison ranges, not preselected measured peaks. Thin guitar strings and plucking transients are challenging for this point tracker; synthetic clips remain the quantitative ground truth.

## Tests and source layout

```sh
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
node --check static/app.js  # optional syntax checks if Node is installed
node --check static/response.js
node --check static/workflow.js
node --check static/sampling.js
```

Windows equivalents use `.\.venv\Scripts\python.exe`. Node is not needed to run the app.

- `modal_camera/processing.py`: bounded decode, temporal filtering, pyramid magnification, tracking/quality and harmonic analysis.
- `modal_camera/spectrum.py`: target-independent original-displacement PSDs, spatial power averaging and peak bins.
- `modal_camera/sampling.py`: independent PSD selection geometry, reference sample positions and quality membership.
- `modal_camera/response.py`: sampled original-displacement harmonic field, phase references and supported-cell animation warping.
- `modal_camera/video_export.py`: annotated heatmap/isolation/modal rendering and local H.264 MP4 encoding.
- `modal_camera/session.py`: validated clip settings, display state and result dependencies.
- `static/workflow.js`: coordinated processing, revision synchronization, recovery and prepared downloads.
- `modal_camera/synthetic.py`: continuous translated seeded textures and lossless FFV1 demo generation; regenerate with `python app.py --make-demos`.
- `app.py`: loopback-only API, state, local import and exports.
- `static/`, `templates/`: dependency-free browser interface; no build step.
- `tests/`: known frequency/amplitude/phase, X/Y, dropout, low texture, band rejection/display response, ROI, gain, input errors, repeated loads, timing and export checks.
- `evidence/`: local test report, numerical results and UI screenshots/check notes.

The implementation is original prototype code; no MIT source code or archive was downloaded or incorporated.
