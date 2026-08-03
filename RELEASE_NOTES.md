# ImgTrans 0.1.0 — V1 release candidate

## Highlights

- Windows 10/11 x64 desktop candidate and macOS 13+ Apple Silicon build flow.
- Single-image and bounded-memory batch OCR, translation, inpainting, layout, editing and selective export.
- RapidOCR and LaMa run locally; Microsoft Translator credentials remain server-side.
- Automatic source-language handling, specified-language filtering, brand protection and language-pair terminology overrides.
- Persistent brand and terminology preferences with corrupt-file backup, safe recovery and legacy schema migration.
- Low-confidence OCR enters REVIEW_REQUIRED without translation, erasure or rendering.
- Overflowing translated layers are not rendered; exact RGB/RGBA source pixels are restored.
- Font color, size, stretch, rotation and conservative 400/600/700 weight reconstruction with weight-aware fitting.
- Manual OCR/source/final-translation regions, geometry and style editing, undo/redo, curved-text controls and five export formats.
- Backend health/readiness, client configuration, model manifest, translation proxy, activation, admin console, audit and rate-limit foundations.

## Verified candidate

- Automated suite: 430 tests passed before documentation-only finalization.
- Six customer images: 6/6 completed, 175 OCR regions, no failed translation regions.
- Safety checks: 18/18 review polygons and 20/20 overflow polygons preserved source pixels across all channels.
- Windows portable directory: 345.1 MiB; verified ZIP: approximately 140.4 MiB.

## Known V1 limitations

- Automatic high-fidelity recovery of arbitrary artistic word clouds, gradients, texture-filled glyphs, mesh distortion and 3D typography is not guaranteed.
- Circular and strongly rotated text can be missed by OCR. V1 keeps unsafe results unchanged and provides manual OCR/translation/layer editing.
- Complex texture inpainting can still require manual mask adjustment, retry, undo or preservation of the original image.
- GIF export is static single-frame; TIFF export is single-page.
- The application does not save reopenable project files.
- The Windows candidate is unsigned until the commercial signing action is completed.
- The macOS build flow has not been accepted on a real Apple Silicon device and has not received production Developer ID signing or notarization.

## V1.1 candidates

- Multi-angle/high-recall OCR for circular and highly rotated text.
- More advanced automatic artistic typography reconstruction.
- Shared multi-instance backend rate limiting.
- Payment, order and automatic activation-code issuance.

## Desktop editor completion

- Added a complete manual-region confirmation flow with separate OCR, erase and text geometry.
- Added mask-based local AI erase with rectangle, brush, eraser, preview and exact outside-mask preservation.
- Added undoable crop with text/path/watermark coordinate transformation.
- Added text and image watermarks, tiling, opacity, visibility, locking, duplication and same-type ordering.
- Added unified background/text/repair/watermark layer state and export quality/alpha/background options.
- Removed matting from the confirmed product scope. Watermark removal is not included.
- Automated suite after editor completion: 551 tests passed.
