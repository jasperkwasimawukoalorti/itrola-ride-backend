"""
File uploads used during onboarding.

Public endpoint: a driver has no account/JWT yet at the point they take
their onboarding photo, so this can't sit behind require_self_driver.
Kept separate from drivers.py since it isn't scoped to a driver_id yet
(the driver row doesn't exist until /drivers/onboard runs).

MVP approach: files are written to local disk under static/. Fine for a
single-instance dev/preview server; move to S3/Cloudinary/Supabase Storage
before running multiple backend instances or redeploying without a
persistent volume, since local disk storage won't survive either.
"""
import os
import uuid

from fastapi import APIRouter, UploadFile, File

router = APIRouter(prefix="/uploads", tags=["uploads"])

# Matches API_BASE_URL in src/api/client.js. Update both together if the
# backend's network address changes (new WiFi, ngrok tunnel, Cloud Run URL).
PUBLIC_BASE_URL = "http://192.168.0.3:8001"

STATIC_ROOT = "static"
ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png"}


async def _save_upload(file: UploadFile, subdir: str) -> str:
    upload_dir = os.path.join(STATIC_ROOT, subdir)
    os.makedirs(upload_dir, exist_ok=True)

    ext = (file.filename or "").rsplit(".", 1)[-1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        ext = "jpg"  # client always sends a .jpg name, but guard anyway

    filename = f"{uuid.uuid4()}.{ext}"
    filepath = os.path.join(upload_dir, filename)

    contents = await file.read()
    with open(filepath, "wb") as f:
        f.write(contents)

    # Full URL, not a relative path — the mobile app loads this directly
    # into an <Image>, so it needs the backend's public base URL baked in.
    return f"{PUBLIC_BASE_URL}/static/{subdir}/{filename}"


@router.post("/driver-photo")
async def upload_driver_photo(file: UploadFile = File(...)):
    url = await _save_upload(file, "driver_photos")
    return {"url": url}


@router.post("/vehicle-photo")
async def upload_vehicle_photo(file: UploadFile = File(...)):
    url = await _save_upload(file, "vehicle_photos")
    return {"url": url}
