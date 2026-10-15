"""
AnyHealth — Media Convert Lambda.

Normalizes both image-ingress paths to browser/RCS-displayable JPEG:

* Secure webview uploads land under raw-uploads/{phone_hash}/{upload_id}.*.
  Their completion state is stored on the UPLOAD# DynamoDB record the webview
  polls.
* Native RCS media lands under inbound/rcs/* through AWS End User Messaging.
  The converter joins the S3 event to the source-key reference written by the
  channel adapter, stores a converted JPEG pointer on the original chat
  message, and calls the adapter back to send a bot-mode confirmation card.

Pillow + pillow-heif handles iPhone HEIC/HEIF. ImageOps.exif_transpose applies
EXIF orientation before re-encoding, so the JPEG's pixels have the same
orientation the sender saw in Photos even when the output viewer ignores EXIF.

Both paths carry untrusted bytes, so only JPEG, PNG, GIF and HEIF files within
the size and pixel limits below are decoded. Anything else is refused: a
webview upload is marked FAILED and a native RCS file is skipped.

Bedrock vision calls (the orientation probe and the classification) receive a
downscaled copy of the image, never the stored JPEG. When no description can be
produced, the stored classification stays empty: member-facing text (the
webview's "What we see" line, the RCS receipt card) omits the line, and the
dashboard's Demo tab labels the gap "(classification unavailable)".
"""

import hashlib
import io
import json
import os
import re
import time
import urllib.parse

import boto3
from PIL import Image, ImageOps
import pillow_heif

import common as c

pillow_heif.register_heif_opener()

# Pillow raises DecompressionBombError above 2x this (52 MP): fits 50 MP phone sensors, and a
# 52 MP HEIC peaked near 830 MB in a local test against this function's 1024 MB.
Image.MAX_IMAGE_PIXELS = 26_000_000

s3 = boto3.client("s3", region_name=c.REGION)
lambda_client = boto3.client("lambda", region_name=c.REGION)
CHANNEL_ADAPTER_FN = os.environ.get("CHANNEL_ADAPTER_FN", "")

# raw-uploads/{phone_hash}/{upload_id}.{ext}
_UPLOAD_KEY_RE = re.compile(
    rf"^{re.escape(c.UPLOAD_RAW_PREFIX)}/(?P<phone_hash>[^/]+)/(?P<upload_id>[^/.]+)\.[^.]+$"
)
# Native EUM media is deliberately scoped to inbound/rcs/ rather than the
# broader inbound/ prefix, which also contains AWS setup-notification objects.
_NATIVE_RCS_PREFIX = f"{c.S3_INBOUND_MEDIA_PREFIX}/rcs/"
_NATIVE_CONVERTED_PREFIX = "converted-inbound"
# Pillow format IDs the converter will decode (JPEG also covers MPO; HEIF is pillow-heif's ID
# for HEIC/HEIF). Webview uploads are HEIC/JPEG/PNG; native RCS media adds GIF
# (common.CONVERTIBLE_IMAGE_MIME_TYPES).
_ALLOWED_IMAGE_FORMATS = ("JPEG", "PNG", "GIF", "HEIF")
# Larger S3 objects are refused before the body is read into memory.
_MAX_SOURCE_BYTES = 50 * 1024 * 1024
# Bedrock Converse accepts image blocks up to 3.75 MB and 8,000 px per image (the 5 MB in
# its "image exceeds 5 MB maximum" message is the base64-encoded size of 3.75 MB of JPEG).
# The converted JPEG of a detailed 12 MP or 48 MP photo can be larger than that, so the
# vision calls get a downscaled copy. 1568 px on the long edge is ample for a
# one-sentence description or an upright check, and even pure noise at this size and
# quality encodes to about 1.6 MB.
_BEDROCK_MAX_EDGE = 1568
_BEDROCK_JPEG_QUALITY = 80


class _UnsupportedMedia(ValueError):
    """A file this converter refuses to decode (format, size, or pixel count).
    Permanent, so retrying the S3 notification cannot change the outcome."""


def handler(event, context):
    """Handle either an S3 ObjectCreated notification or a direct test event."""
    if event.get("native_media"):
        native = event["native_media"]
        return _process_native(native["bucket"], native["key"])

    for record in event.get("Records", []):
        bucket = record["s3"]["bucket"]["name"]
        # S3 event keys encode spaces as '+'.
        key = urllib.parse.unquote(record["s3"]["object"]["key"].replace("+", " "))
        if key.startswith(f"{c.UPLOAD_RAW_PREFIX}/"):
            _process_webview_upload(bucket, key)
        elif key.startswith(_NATIVE_RCS_PREFIX):
            _process_native(bucket, key)
        else:
            print(f"skip: unsupported media key: {key}")
    return {"statusCode": 200}


def _open_normalized_jpeg(bucket: str, key: str) -> bytes:
    """Load an S3 image, bake any EXIF orientation into its pixels, and
    return an RGB JPEG.

    Some iOS in-app browser selections arrive with the original photo's EXIF
    orientation stripped or incorrectly reset to 1 even though the raw pixels
    are upside down. For those ambiguous files only, ask the same vision model
    used for classification whether the image is inverted, and apply a half
    turn only when a second look confirms it. HEIF and images with a real EXIF
    orientation remain purely deterministic and do not pay for the model calls.
    """
    obj = s3.get_object(Bucket=bucket, Key=key)
    if obj["ContentLength"] > _MAX_SOURCE_BYTES:
        obj["Body"].close()
        raise _UnsupportedMedia(f"file is larger than {_MAX_SOURCE_BYTES // (1024 * 1024)} MB")
    raw_bytes = obj["Body"].read()
    try:
        image = Image.open(io.BytesIO(raw_bytes), formats=_ALLOWED_IMAGE_FORMATS)
    except Image.UnidentifiedImageError:
        raise _UnsupportedMedia("unsupported image format") from None
    except Image.DecompressionBombError:
        raise _UnsupportedMedia("image dimensions are too large") from None
    # exif_transpose returns a new image with no .format, so read it first.
    source_format = image.format
    source_orientation = image.getexif().get(0x0112)
    image = ImageOps.exif_transpose(image)
    image = image.convert("RGB")

    # Orientation 1/absent on a JPEG/PNG/GIF carries no usable camera-rotation
    # signal; this is the observed path for the upside-down iOS webview boat
    # upload. HEIF is excluded because its rotation lives in the container
    # (irot), which the decoder has already applied, and pillow-heif resets
    # the EXIF orientation to 1 at open. Every HEIC would otherwise look
    # "ambiguous" here and an upright photo could be turned by mistake.
    if source_format != "HEIF" and source_orientation in (None, 1):
        clockwise_rotation = _infer_upright_rotation(image)
        if clockwise_rotation:
            # PIL rotates counter-clockwise for positive values; the
            # correction is expressed in clockwise degrees.
            image = image.rotate(-clockwise_rotation, expand=True)

    return _save_jpeg(image)


def _save_jpeg(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=88)
    return buffer.getvalue()


def _process_webview_upload(bucket: str, key: str):
    match = _UPLOAD_KEY_RE.match(key)
    if not match:
        print(f"skip: key doesn't match expected webview upload shape: {key}")
        return
    phone_hash, upload_id = match["phone_hash"], match["upload_id"]

    try:
        c.set_upload_status(phone_hash, upload_id, "PROCESSING")
        jpeg_bytes = _open_normalized_jpeg(bucket, key)
        converted_key = f"{c.UPLOAD_CONVERTED_PREFIX}/{phone_hash}/{upload_id}.jpg"
        s3.put_object(Bucket=bucket, Key=converted_key, Body=jpeg_bytes, ContentType="image/jpeg")

        classification = _classify(jpeg_bytes)
        c.set_upload_status(
            phone_hash, upload_id, "READY", converted_key=converted_key, classification=classification,
        )
        print(f"converted webview upload {key} -> {converted_key}")
    except Exception as exc:  # noqa: BLE001
        # _UnsupportedMedia carries one of this module's own fixed reasons, so it
        # is logged as written. Anything else is logged by error code or class
        # only: an SDK error can echo its request, and the requests in this
        # block carry the member's photo and its description.
        reason = str(exc) if isinstance(exc, _UnsupportedMedia) else c.error_code(exc)
        print(f"webview conversion failed for {key}: {reason}")
        # The upload page shows this text to the member, so a fixed reason is
        # stored for unsupported media and a generic one for every other failure
        # (the code is in the log line above).
        shown = str(exc) if isinstance(exc, _UnsupportedMedia) else "the file could not be processed"
        c.set_upload_status(phone_hash, upload_id, "FAILED", error=shown)


def _process_native(bucket: str, key: str):
    """Normalize an EUM-delivered native RCS file, then update the exact
    inbound conversation message it originated from.

    S3 may publish this event milliseconds before EUM publishes the matching
    SNS message. The channel adapter writes the source-key reference from that
    SNS message; raise when it isn't available yet so Lambda/S3 retries rather
    than silently losing a photo conversion.
    """
    reference = c.get_native_media_reference(key)
    if not reference:
        raise RuntimeError(f"native media reference not available yet for {key}")

    try:
        jpeg_bytes = _open_normalized_jpeg(bucket, key)
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        converted_key = f"{_NATIVE_CONVERTED_PREFIX}/{digest}.jpg"
        s3.put_object(Bucket=bucket, Key=converted_key, Body=jpeg_bytes, ContentType="image/jpeg")
        classification = _classify(jpeg_bytes)
        callback = c.record_native_media_conversion(key, converted_key, classification)
        if callback:
            _notify_channel_adapter(callback)
        print(f"converted native RCS media {key} -> {converted_key}")
        return {"statusCode": 200, "media": callback.get("media", {}), "classification": classification}
    except _UnsupportedMedia as exc:
        print(f"skip: native media refused for {key}: {exc}")
        return {"statusCode": 200, "skipped": str(exc)}
    except Exception as exc:  # noqa: BLE001
        # Error code or class only, as in _process_webview_upload. The exception
        # is re-raised below, so Lambda logs it in full; a Bedrock failure cannot
        # get that far because _classify handles its own.
        print(f"native conversion failed for {key}: {c.error_code(exc)}")
        # Re-raise: an async S3 notification should retry a transient join,
        # S3 read, Pillow, or Bedrock failure instead of leaving raw HEIC as
        # the only dashboard representation.
        raise


def _notify_channel_adapter(callback: dict):
    if not CHANNEL_ADAPTER_FN:
        print("CHANNEL_ADAPTER_FN is not configured; conversion persisted without RCS callback")
        return
    lambda_client.invoke(
        FunctionName=CHANNEL_ADAPTER_FN,
        InvocationType="Event",
        Payload=json.dumps({"native_media_ready": callback}).encode("utf-8"),
    )


def _downscaled(image: Image.Image) -> Image.Image:
    """`image` shrunk so its long edge is at most _BEDROCK_MAX_EDGE. Never
    upscales, and returns `image` itself when it is already small enough, so
    treat the result as read-only."""
    long_edge = max(image.size)
    if long_edge <= _BEDROCK_MAX_EDGE:
        return image
    scale = _BEDROCK_MAX_EDGE / long_edge
    size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
    # reducing_gap shrinks by whole-number factors first, which keeps a 50 MP
    # source fast; the small quality trade-off does not matter for model input.
    return image.resize(size, Image.Resampling.LANCZOS, reducing_gap=2.0)


def _bedrock_jpeg(image: Image.Image) -> bytes:
    """JPEG of a downscaled copy of `image`, sized for a Bedrock image block."""
    buffer = io.BytesIO()
    _downscaled(image).save(buffer, format="JPEG", quality=_BEDROCK_JPEG_QUALITY)
    return buffer.getvalue()


def _bedrock_jpeg_from_bytes(jpeg_bytes: bytes) -> bytes:
    """Same as _bedrock_jpeg for an already-encoded JPEG, which is left as is."""
    with Image.open(io.BytesIO(jpeg_bytes), formats=("JPEG",)) as image:
        # draft() has the decoder scale by 1/2, 1/4 or 1/8 while decoding, so a
        # 50 MP JPEG is not expanded to full size just to be shrunk again.
        image.draft("RGB", (_BEDROCK_MAX_EDGE, _BEDROCK_MAX_EDGE))
        return _bedrock_jpeg(image)


def _infer_upright_rotation(image: Image.Image) -> int:
    """For images whose EXIF gives no useful orientation, ask the vision model
    whether the image is upside down. Returns the clockwise correction in
    degrees: 180, or 0 for "leave it alone".

    Only a half turn is ever applied, and only when two looks agree: the image
    is reported as needing 180, and a copy turned by 180 is reported as already
    upright. Quarter turns are never applied: a wrong turn of a member's
    upright insurance card is worse than leaving a sideways one, and a half
    turn has no direction to choose. The agreement check between two looks
    catches a one-off wrong answer but not a consistent one, so quarter turns
    stay off.
    Malformed, uncertain or failed responses fall back to 0 rather than
    randomly rotating a member's document."""
    small = _downscaled(image)
    if _ask_clockwise_rotation(_bedrock_jpeg(small)) != 180:
        return 0
    if _ask_clockwise_rotation(_bedrock_jpeg(small.transpose(Image.Transpose.ROTATE_180))) != 0:
        return 0
    return 180


def _ask_clockwise_rotation(jpeg_bytes: bytes) -> int:
    """One orientation probe. Returns the model's clockwise correction in
    {0, 90, 180, 270}, or 0 when the call or its answer is unusable."""
    try:
        bedrock = boto3.client("bedrock-runtime", region_name=c.BEDROCK_REGION)
        response = bedrock.converse(
            modelId=c.BEDROCK_MODEL_ID,
            messages=[{
                "role": "user",
                "content": [
                    {"image": {"format": "jpeg", "source": {"bytes": jpeg_bytes}}},
                    {"text": (
                        "Determine whether this image is upright for natural viewing. "
                        "Return exactly one JSON object and nothing else: "
                        "{\"clockwise_rotation\": N}, where N is 0, 90, 180, or 270 "
                        "and is the clockwise rotation needed to make the image upright. "
                        "Do not transcribe or describe any visible content."
                    )},
                ],
            }],
            inferenceConfig={"maxTokens": 30, "temperature": 0},
        )
        raw = response["output"]["message"]["content"][0]["text"].strip()
        candidate = raw[raw.find("{"): raw.rfind("}") + 1] if "{" in raw else raw
        rotation = json.loads(candidate).get("clockwise_rotation", 0)
        return int(rotation) if rotation in (0, 90, 180, 270) else 0
    except Exception as exc:  # noqa: BLE001
        # Error code or class only: the request carries the member's photo, and an
        # SDK error can echo its request.
        print(f"orientation inference failed: {c.error_code(exc)}")
        return 0


def _classify(jpeg_bytes: bytes) -> str:
    """Return a one-sentence, non-diagnostic description, or "" when Bedrock
    could not produce one. The empty string is deliberate: the webview and the
    RCS receipt card print "What we see: {classification}" for any non-empty
    value, so a placeholder phrase would be shown to the member as if the
    model had said it. The prompt deliberately prohibits transcribing PII, IDs,
    names, numbers, or medical details visible in the source image. The model
    sees a downscaled copy; `jpeg_bytes` (the stored image) is not modified."""
    try:
        bedrock_jpeg = _bedrock_jpeg_from_bytes(jpeg_bytes)
        bedrock = boto3.client("bedrock-runtime", region_name=c.BEDROCK_REGION)
        response = bedrock.converse(
            modelId=c.BEDROCK_MODEL_ID,
            messages=[{
                "role": "user",
                "content": [
                    {"image": {"format": "jpeg", "source": {"bytes": bedrock_jpeg}}},
                    {"text": (
                        "In one short plain-language sentence, describe what this photo "
                        "shows in general terms (for example, 'an insurance card', 'a boat', "
                        "or 'a document'). Do not read or repeat any personal information, "
                        "names, numbers, ID details, or medical details visible in the image; "
                        "describe only the general subject."
                    )},
                ],
            }],
            inferenceConfig={"maxTokens": 100, "temperature": 0.1},
        )
        description = _clean_description(response["output"]["message"]["content"][0]["text"])
        if not description:
            print("image classification returned no text")
        return description
    except Exception as exc:  # noqa: BLE001
        # Error code or class only: the request carries the member's photo, and an
        # SDK error can echo its request.
        print(f"image classification failed: {c.error_code(exc)}")
        return ""


def _clean_description(value: str) -> str:
    """The dashboard UI and the RCS receipt card both render this as plain text,
    so flatten any Markdown in the vision model's output (for example,
    **boat**) via the shared helper used for all model-generated copy."""
    return c.strip_markdown(value.strip())[:300]
