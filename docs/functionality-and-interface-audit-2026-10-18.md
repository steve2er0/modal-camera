# Modal Camera functionality and interface audit

Audit date: October 18, 2026. Application revision: `0543852`.

Modal Camera has a working analysis and video-export core, but its interface requires the user to coordinate several independent result states. The first priority is to make calibration, result freshness, export readiness, and recovery reliable. The main workflow should then be organized around selecting a response frequency and exploring the result.

For the plate experiment, the intended task is straightforward: load the recording, establish its analysis timing, select approximately 95 Hz, see the responding regions and fitted displacement, and export a useful view. The current interface spreads these decisions across several panels and separate processing buttons.

## Validation results

| Area | Result |
| --- | --- |
| Automated functionality | All 59 tests passed in 31.17 seconds. Coverage includes tracking, spectra, amplitude and phase, dropout, spatial fits, timebase scaling, input rejection, API state, and exports. |
| Known motion in Chrome | Recovered 0.3977 and 0.5989 source-pixel peak amplitudes and 60.2 degrees relative phase, compared with synthetic inputs of 0.40, 0.60, and 60 degrees. |
| Tracking failures | The dropout demo withheld P2 amplitude and phase and disclosed 72 rejected frames out of 360. |
| Spatial workflow in Chrome | Building the demo field produced 50 accepted amplitude fits and 50 usable relative phases out of 84 samples, with 28.8 percent interpolation support. Amplitude, phase, sensitivity, and modal animation controls operated. |
| Video exports | Tests encoded and decoded H.264 files for all three views, checked playback timing, modal repetition, sensitivity, snapshot isolation, and encoder failure handling. A fresh Chrome modal-export request produced a working HTTP attachment containing 291046 bytes. |
| Capture timing | Chrome rejected an unconfirmed capture-rate override. After confirmation, changing 60 to 240 analysis fps scaled band and fit frequencies by four and cleared dependent results. |
| Source checks | Both JavaScript files passed syntax checks. Git whitespace checks passed. |
| Responsive layout | At 390 by 844, the page had no horizontal document overflow, but was 4781 pixels tall. The loaded desktop demo was 2908 pixels tall at 1728 by 1084, with 40 visible controls and links. |

These results validate the synthetic examples and the tested local application behavior. They do not establish the physical capture rate of the plate recording, validate real displacement against an instrument, or identify a structural eigenmode. Browser filesystem saving and Windows execution were not established by this audit.

## Findings requiring correction

### High priority Calibration carries into another clip

Reproduction: load the known-motion demo, enter a calibration of 2 mm per source pixel, then load the tracking-dropout demo. Calibration remains 2, and the new recording immediately displays a 0.7954 mm P1 amplitude.

A length scale belongs to the recording and object plane. Reusing it without an explicit choice can produce incorrect engineering units after a camera, distance, resolution, or specimen change.

Clear calibration on clip replacement, or offer an explicit reuse choice identifying the previous scale. Bind calibration and its provenance to the saved clip state.

Source: `static/app.js`, `load`, lines 25–41; calibration formatting, lines 113–119.

### High priority Spatial exports can retain a map discarded by the interface

Reproduction: build a displacement map at 3 Hz, change the fit frequency to 7 Hz, and analyze the original points. The interface says the spatial map must be rebuilt. The JSON export nevertheless contains a 7 Hz point analysis and the previous 3 Hz spatial map; spatial CSV still returns all 84 old 3 Hz samples.

Each exported result includes its own frequency, so the numbers are not simply relabeled as 7 Hz. The failure is that export still includes a spatial result the interface has declared invalid, with no explicit previous-result status.

Use result identities covering the clip, timing, frequency, axis, points, ROI, and reference settings. Clear stale results consistently or expose them as deliberately retained snapshots. Apply the same readiness rules to JSON and CSV as to MP4.

Source: `static/response.js`, `invalidateField`, lines 7–10; `app.py`, analysis JSON export at line 225, spatial CSV export at line 293.

### High priority Unready data exports navigate away from the workspace

Reproduction: change the analysis timebase, which clears the spatial map, then click Export spatial samples CSV. The link is still available. Instead of a download, the browser navigates to a JSON error page. Returning with Back showed the initial landing screen with an empty workspace.

Disable or explain unavailable exports. Handle download errors within the app and keep the workspace intact. Session recovery should make an accidental navigation or refresh inexpensive.

Source: `templates/index.html`, data export links at lines 15–16; `static/response.js`, `updateExportLinks`, lines 41–43; `app.py`, spatial CSV readiness check at line 293.

### Medium priority Previous point results remain visible after settings change

Reproduction: load the known-motion demo, then change Fit frequency from 3 to 7. The previous 0.3977 and 0.5989 px amplitudes and 60.2 degree phase remain in the table. Its header still correctly says 3 Hz, while the controls and plot selection say 7 Hz. The update warning appears only in the status message.

Retaining a previous fit can be useful, but it needs a prominent Previous result or Needs update state adjacent to the result. Frequency, axis, reference, and point changes should follow one consistent rule. Point selection currently clears results, while other measurement changes retain them.

Source: `static/app.js`, `invalidateAnalysis`, line 79; `measurementSettingsChanged`, lines 110–112.

### Medium priority Errors and progress are separated from the active controls

Reproduction: enter added gain 21 and click Apply band and gain. The app rejects the value correctly, but the error appears more than 1000 pixels above the viewport while the action button remains visible. It can look as though processing did nothing.

Show validation next to the field and processing control. Keep an accessible global announcement, with a compact persistent status area. Expensive operations should show their current stage and offer cancellation where practical; current tasks disable all form controls and have no UI cancellation.

Source: `static/app.js`, `showError` and `task`, lines 7–18; `templates/index.html`, status and error containers at lines 7–8.

### Medium priority Point and sample interaction requires a pointer

The original-image and spatial-view canvases have descriptive labels but no keyboard focus or keyboard selection model. Adding a measurement point, drawing an ROI, and inspecting a spatial sample depend on pointer handlers. The spectrum does have numeric frequency controls, which partially mitigates its pointer dependence.

Provide an accessible sample table or sample selector, editable point coordinates, and keyboard selection. Keep phase and amplitude values available as text, with color as an additional cue.

Source: `templates/index.html`, canvases at lines 12–14; `static/app.js`, point and ROI handlers at lines 82–85; `static/response.js`, sample inspection at lines 132–144.

## What makes the workflow complicated

The loaded demo exposes 40 controls and links. The user must distinguish the visualization band, single-frequency fit, image magnification gain, animation displacement gain, analysis fps, encoded playback fps, point phase reference, spatial phase reference, and stationary-camera reference. These distinctions have physical meaning, but they should be introduced when needed.

Three separate actions produce different outputs: Apply band and gain, Analyze original points, and Build displacement and phase map. The six response views share a selector even though their prerequisites differ. A new recording asks the user to select manual points, although heatmap filtering and automatic spatial sampling can run without them. Choosing an unavailable view shows instructions to find another control farther down the page.

The capture-time decision is particularly consequential for the 95 Hz use case, yet its controls are inside Measurement settings, below the video and spectrum. The default view exposes a sensitivity slider even though sensitivity does not change the magnified-video view. The two video images also start at different vertical positions because the response selector is placed above only the right image.

Desktop and narrow layouts fit their widths. Their vertical length, repeated explanatory text, and small controls still make it difficult to see the selected settings, current result, and next action together. The persistent introductory block occupies substantial space after a clip is loaded.

## Proposed main workflow

1. **Load the recording.** Show duration, retained frames, analysis resolution, and import problems. Collapse the introductory content after loading. Offer trim and frame-order-preserving import assistance for recordings that exceed limits or have irregular timing; do not silently drop or synthesize samples.
2. **Confirm analysis timing.** Put encoded playback fps and any assumed capture fps together. Explain that physical frequency depends on capture timing. At 240 capture fps, the current 600-frame limit permits only 2.5 seconds of captured motion, which is more useful than an unexplained frame count.
3. **Choose the response.** Offer Target frequency, initially 95 Hz for this experiment, and Bandwidth. Link the band center and fit frequency by default. Allow independent frequencies under Advanced. Show the applied settings separately from pending edits.
4. **Analyze response.** One main action should coordinate band filtering and a displacement map when required, reuse valid tracking, and explain progress. Manual point selection should be optional unless the user wants point-specific traces or a selected reference.
5. **Explore views.** Keep the videos aligned and put Heatmap, Isolated, Amplitude, Phase, and Animation beside the preview. Retain magnified playback as another available view. Show Sensitivity where relevant and Display motion gain for the active visualization. Keep interpolation coverage and timing status visible.
6. **Export.** Use one Export control with video and data choices. Identify the view, applied frequency, timing, and settings being exported. Prevent unready choices and handle failures without navigation.

Advanced settings can retain PSD versus amplitude spectra, detailed tracking diagnostics, calibration, independent fit and band frequencies, ROI, camera translation subtraction, and reference selection. Scientific assumptions should remain accessible, with the few conditions that affect the current result shown beside it.

## Engineering interpretation to preserve

The heatmap measures selected-band image-brightness variation, not displacement. Sensitivity is a display threshold relative to a reference scale, not a confidence percentage or a measured noise floor. Isolation applies a spatial response mask to magnified frames; motion at other frequencies can remain inside those regions.

Spatial amplitudes and phases come from tracked original-image patches. Unsupported cells remain unsupported. Modal playback is a slowed fitted operating response, rather than a measured movie of only an identified eigenmode. The current separation between measured values and enlarged display motion should remain explicit.

The current support for source-pixel units, quality-gated tracking, withheld weak phase, explicit timebase assumptions, original-frame measurement, and annotated exports is valuable and should survive the simplification.

## Recommended implementation order

First correct calibration ownership, stale-result identities, export readiness, and in-app error recovery. Add targeted browser regression checks for those transitions; the existing 59-test Python suite does not exercise them, and the optional browser smoke script does not cover the full spatial and MP4 workflow.

Then consolidate timing and frequency selection, introduce one main processing action, and group view controls around the preview. Add session save and reopen, keyboard sample access, clearer import assistance, and cancellable processing as the next improvements.

This audit changes documentation only. Application behavior and Git commits remain unchanged. Browser checks used a separate local process on port 8766; the existing service on port 8765 was left untouched.

## Implementation followup

The October 18 followup implements the calibration reset, consistent result invalidation, guarded data exports, visible errors, keyboard point/sample access, and refresh recovery. The main interface now follows timing, target and bandwidth, one analysis action, aligned response views, and a unified export control. Detailed settings are under Advanced. See [the current workflow guide](../README.md#main-workflow) and [validation evidence](../evidence/VALIDATION.md).

Recovery currently lasts while the local server remains running. Stop after this step waits for the current computation. Import trimming/conversion and a persistent project-file format remain future enhancements; existing import limits remain explicit.
