# Validation — 2026-10-04 (America/New_York)

Project: `/Users/stephenwells/Documents/DevOps/modal-camera`.

## Automated checks

`24 passed in 10.64s` from `.venv/bin/python -m pytest -q --tb=short`; full output in `pytest.txt`. `node --check static/app.js` and `node --check scripts/ui_smoke.cjs` passed.

Coverage includes lossless decoded clips, frequency/amplitude/relative phase on X/Y, the secondary tone, temporal band rejection, reconstructed display response, gain/ROI limits, low texture, dropout/reacquisition, source-pixel scaling, explicit timebase changes, malformed/unsupported and short/long input, variable timing/truncation, repeated loads, stale render IDs, exports and loopback/origin guards.

## Quantitative results

| Quantity | Known input | Measured original |
|---|---:|---:|
| Dominant frequency | 3.000 Hz | 3.000 Hz |
| P1 Y peak, 3 Hz | 0.400000 px | 0.397684 px |
| P2 Y peak, 3 Hz | 0.600000 px | 0.598912 px |
| P2 phase relative to P1, 3 Hz | +60.000° | +60.152° |
| P1 Y peak, 7 Hz | 0.120000 px | 0.122785 px |
| P2 Y peak, 7 Hz | 0.100000 px | 0.100899 px |
| P1 3 Hz display response, added gain 1 | ideal 0.800000 px | 0.780116 px |

Both clean points accepted 100% of frames. Display-response tracking is a **test of the reconstructed visualization**, not the application's scientific measurement input. The application always measures original frames.

The dropout case rejects all **72/72 occluded frames** at P2, leaves gaps, withholds its FFT and fit, and reacquires afterward. P1 remains measurable. The blank point rejects **360/360 frames**, reports low texture, and has no fit or phase. Per-frame metrics and fit residuals are in `numerical-validation.json`.

## Browser exercise

Twelve checks passed with local Playwright Chromium, with **zero JavaScript errors**. The CUA tool transport was unavailable; an existing local Playwright installation was used instead. A transient executor disconnect also interrupted the initial long-running preview, recovered by a test-owned local server. These tooling interruptions did not leave implementation blockers.

- Known demo loads, tracks and renders; measured table values displayed correctly.
- Whole-band dragging changes rendered frames; independent fit at 7 Hz updates correctly.
- Gain 21 is rejected, then a valid retry recovers.
- ROI drawing and full-frame reset work.
- Shared replay clock and scrubbing work.
- Dropout gaps/warnings/withheld fit are visible.
- Low-texture selection shows warnings and no fit.
- Malformed input gives a visible error and allows subsequent loading.
- Guitar imports; the capture-rate verification gate rejects an unconfirmed override, then an explicit **assumed** 600 fps timebase allows a 72–92 Hz render.
- Repeated same-file imports clear selections, timebase override, analysis and render.
- JSON export downloads locally.
- No JavaScript errors.

See `ui-validation.json`, `ui-known-motion.png`, `ui-tracking-dropout.png`, `ui-guitar-example.png`, and `ui-final-full-page.png`. Optional reproduction:

```sh
UI_START_SERVER=1 UI_PORT=8766 PLAYWRIGHT_MODULE=/path/to/approved/playwright node scripts/ui_smoke.cjs
```

Python core validation is reproducible with `.venv/bin/python validate.py`. Playwright/Node are optional QA dependencies, not application runtime dependencies.

## Guitar example: verified and unverified

Requested file: `data/examples/guitar.mp4`, **1,198,956 bytes**. SHA-256 `05ec305c9224c9374114642d29e7519e77e282147a25dce1e502426331d153a4`. All **300 frames** decoded, source **432×192**, encoded **29.97002997 fps**, **10.01 s** playback. Analysis is resized to 424×188 to meet the temporal memory budget, and displacement is rescaled to source pixels.

The paper reports 600 fps capture. Under an explicitly **unverified one-encoded-frame-per-capture-sample assumption**, this is 0.5 s and 2 Hz bin resolution. Import, assumed-timebase changes, point-tracking UI and 72–92 Hz linear Eulerian rendering passed. The selected raw point spectrum's strongest average bin was 4 Hz under that assumed timebase; this is **not** a claimed string resonance. A smaller component around 80 Hz appears at the first selected patch; two other patches had weak harmonic signal and their relative phases were withheld. Patch confidence does not prove that a thin string's displacement is isolated from the guitar body. No physical frequency or amplitude truth was independently established for this footage.

Source/capture references and decoder metadata are saved in `data/examples/guitar.source.json`; detailed smoke results in `guitar-smoke-analysis.json`. The external clip is excluded from git/redistribution by default. No MIT source code was downloaded or used.

## Remaining limits

No validation on the user's Shuttle/work-PC footage, no Windows execution test, no identified modes or hardware integration. Linear Eulerian intensity magnification can amplify lighting and generate halos/clipping. Tracking needs stable, textured, locally rigid surfaces; it has heuristic confidence gates rather than a calibrated uncertainty model. Camera-reference subtraction corrects translation in measurements only; images are not stabilized. Physical Hz requires a verified capture timebase. The localhost development server is for one local user; it keeps one active clip in RAM and is not a production/multiuser service.

## Tracked-displacement PSD extension

The complete suite now passes **28 tests in 10.61 s** (`pytest-psd.txt`). New checks validate full-record Hann density normalization by integrated known sinusoidal power, two-tone peaks, the one-sided Nyquist endpoint, displacement-squared scaling, capture-rate/density scaling with invariant integrated RMS, stationary zero power, and PSD withholding for dropout/low texture. JavaScript syntax passes.

The current in-app browser was exercised via CUA. PSD/amplitude selection, linear/log PSD scaling, calibration units, clickable peak selection, band-edge dragging, and reconstruction all worked; there were **no browser JavaScript errors**. Two selected original guitar locations, P1 (180,50) and P2 (150,52) in analysis coordinates, each accepted 100% of frames and have strongest local PSD bins at 80 and 82 Hz under the explicitly assumed 600 fps timebase. This selection differs from the initial guitar smoke check above. Neither point isolates a validated pure string displacement, and these weak harmonic fits withhold relative phase.

PSD uses original Y displacement, linear detrending and a one-sided periodic-Hann full-record periodogram in source pixels²/Hz. The record is 0.500 s, bins 2 Hz, Hann ENBW 3 Hz, with no Welch averaging, zero padding or filled rejected samples. The plotted floor is only a display limit. Magnification band/gain does not affect PSD. Detailed metadata/densities are saved in `guitar-psd-analysis.json`, and UI checks/results in `psd-validation.json`. Native in-app download-event observation timed out; a read-only loopback export request succeeded and preserved the scientific evidence.

Screenshots: `ui-guitar-psd.jpg` (visible PSD/settings) and `ui-guitar-psd-full-page.jpg` (full application context). The local app remains available on port 8765.

## Frequency response views and fitted spatial animation — October 10, 2026

41 tests pass, including original-frame spatial amplitude/phase recovery, wrong-tone rejection, source-unit/timebase scaling, dropout and weak-phase withholding, analytic 0/60/90/180 degree phase cases, camera-reference subtraction, harmonic-warp sign/gain and unsupported-cell exclusion, stale API keys and exports. Both JavaScript modules pass `node --check`.

Chrome desktop QA covered heatmap, isolation/sensitivity, amplitude/phase sample inspection, fitted playback and frequency-change invalidation. The existing plate recording is loaded at a 95 Hz fit using the prior user-assumed 240 fps capture timebase: 59/72 amplitude fits, 29 relative phases, 13.6% image support for interpolation. This does not independently validate physical frequency, a structural mode or full-field displacement. Browser file import used the native picker; the automated export download was canceled, and live JSON/CSV API exports were separately verified. No mobile or Windows execution is claimed. See `response-view-validation.json`, the `plate-95hz-*` exports and `ui-plate-95hz-*.png` screenshots.
