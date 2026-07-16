# Gallery Video Uploads + Fullscreen Lightbox — Implementation Notes

## Setup
1. `pip install -r requirements.txt --break-system-packages`
2. `python manage.py migrate` (applies `booking/migrations/0013_galleryimage_video_support.py`).
3. That's it — no manual folder setup needed.

## What changed

**`GalleryImage` (booking/models.py)** now supports two kinds of entries instead of just
photos:
- `media_type` — "Photo" or "Video"
- `image` — used for Photo entries (unchanged behaviour: auto-resized to 1600px, saved as
  85%-quality JPEG)
- `video` — used for Video entries (`.mp4`, `.webm`, `.mov`, `.m4v` only). Video files are
  **not** re-encoded/compressed (no ffmpeg available in this environment) — ask whoever is
  uploading to keep clips short (~30s or less) and already compressed before uploading, so
  the public Gallery page stays fast.
- `video_poster` — optional cover image for a video, shown before it's played. If left
  blank, the browser just shows the video's first frame.

`GalleryImage.clean()` enforces that a Photo entry has an image and a Video entry has a
video file, so the admin form errors clearly if either is missing.

**Django Admin (booking/admin.py + static/js/admin/gallery_media_toggle.js):** the
Gallery Items add/change form now shows a Media Type dropdown at the top. Picking
"Photo" or "Video" shows/hides the relevant upload field via a small JS toggle, so staff
aren't stuck looking at both an image and a video field at once. The changelist thumbnail
column shows a video's poster (or a plain play-icon placeholder if no poster was set) so
photos and videos are easy to tell apart at a glance.

**Public site (templates/booking/_gallery_item.html):** both the homepage's gallery
preview and the full `/gallery/` page now render through one shared partial that outputs
either an `<img>` or a muted, looping `<video>` preview depending on the entry's type, with
a play-icon badge over video thumbnails.

**Fullscreen lightbox (static/js/gallery.js + static/css/style.css):** clicking (or
pressing Enter/Space on) any gallery item — photo or video — opens it full-viewport with:
- Left/right arrows (and arrow keys) to move between the other items on that page
- A close button and Escape-to-close
- A fullscreen toggle button that uses the browser's native Fullscreen API
- Videos autoplay with controls once opened, and are paused/unloaded again on close

No markup changes are needed elsewhere to pick this up — every element with a
`.gallery-item[data-src]` on a page that loads `gallery.js` is wired in automatically.

## Unrelated fix bundled in
While testing uploads, found that `STORAGES` in `decisivesounds/settings.py` only defined
a `staticfiles` backend and no `default` one. Since Django 5+ treats `STORAGES` as a full
override rather than a patch, this meant `django.core.files.storage.handler.InvalidStorageError`
would be raised on ANY `ImageField`/`FileField` save — including the existing photo gallery,
quotation/invoice PDFs, etc. Added the missing `default` entry (`FileSystemStorage`) back in.
Worth double-checking uploads work in whatever environment this gets deployed to, in case
something there was silently relying on the old (broken) behaviour.
