# ImgTrans V1 manual release actions

These actions require credentials, external services, physical hardware, or subjective approval and cannot be completed from the current development environment.

## 1. Production backend and domain

1. Provision the production database and object storage.
2. Configure HTTPS and DNS for the backend URL.
3. Inject, through the deployment secret store only:
   - `IMGTRANS_DATABASE_URL`
   - `IMGTRANS_TRANSLATOR_KEY` and optional translator region
   - `IMGTRANS_ACTIVATION_SECRET` with at least 32 characters
   - `IMGTRANS_ADMIN_USERNAME`
   - `IMGTRANS_ADMIN_PASSWORD_HASH`
   - `IMGTRANS_ADMIN_SESSION_SECRET` with at least 32 characters
   - object-storage endpoint, bucket, region and access credentials
4. Run database migrations and verify `/health/live` and `/health/ready` over HTTPS.
5. Configure the desktop deployment with `IMGTRANS_TRANSLATION_MODE=server` and the production `IMGTRANS_API_BASE_URL`.
6. Create a real activation plan/code and verify device activation, model manifest access and translation. Never distribute the Microsoft key to desktop clients.

## 2. Windows commercial signing

The current Windows candidate is unsigned.

1. Obtain an Authenticode code-signing certificate and timestamp service.
2. Sign `ImgTrans.exe` and any installer wrapper with `signtool sign /fd SHA256 /tr <timestamp-url> /td SHA256` using the protected certificate identity.
3. Verify with `signtool verify /pa /all /v ImgTrans.exe` on Windows 10 and Windows 11.
4. Re-run `python -m scripts.verify_desktop_artifact --target windows-x64` and regenerate the ZIP and manifest after signing.
5. Perform SmartScreen and clean-machine installation checks. Do not store certificate files or passwords in the repository.

## 3. macOS 13+ Apple Silicon

Build flow is prepared, but it has not been accepted on a real macOS Apple Silicon device.

1. Run the `m4-desktop-release-build.yml` macOS arm64 job and download the verified artifact.
2. On a real Apple Silicon Mac, verify `uname -m` reports `arm64` and test macOS 13 or newer.
3. Sign with a protected Developer ID Application identity using hardened runtime as required by the final entitlement set.
4. Verify with `codesign --verify --deep --strict --verbose=2 ImgTrans.app`.
5. Submit with `xcrun notarytool`, wait for acceptance, staple with `xcrun stapler staple`, and verify with `spctl --assess --type execute --verbose=2`.
6. Test Gatekeeper launch, Keychain activation token storage, Retina rendering, native file dialogs, first model download, OCR, LaMa/OpenCV fallback, editing, all export formats, upgrade and uninstall.
7. Record the real device model, macOS version, application hash and results without recording credentials.

## 4. Customer visual acceptance

Ask the customer to review representative ordinary e-commerce images and confirm acceptable typography and background restoration. The V1 automatic acceptance scope excludes reliable reconstruction of arbitrary artistic word clouds and circular/strongly rotated text. Confirm that the review/overflow/manual-edit fallback is acceptable for those cases.

